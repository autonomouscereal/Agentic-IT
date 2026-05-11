"""iTop Ticket Provider - implements the TicketProvider interface.

Provides real-time sync with fast discovery (quick key scan) + full sync
on new tickets + WebSocket broadcast for live dashboard updates.
"""
import os
import json
import asyncio
from datetime import datetime
from database import fetchall, fetchrow, execute, fetchval, json_dumps
from services.ticket_provider import TicketProvider
from services.event_logger import log_event

ITOP_HOST = os.getenv("ITOP_HOST", "").strip()
ITOP_PORT = os.getenv("ITOP_PORT", "25432").strip()
ITOP_BASE = f"http://{ITOP_HOST}:{ITOP_PORT}/webservices/rest.php" if ITOP_HOST else ""
ITOP_USER = os.getenv("ITOP_USER", "")
ITOP_PASSWORD = os.getenv("ITOP_PASSWORD", "")
ITOP_DEFAULT_ORG_ID = os.getenv("ITOP_DEFAULT_ORG_ID", "").strip()
ITOP_DEFAULT_CALLER_ID = os.getenv("ITOP_DEFAULT_CALLER_ID", "").strip()
ITOP_SECURITY_TEAM_ID = os.getenv("ITOP_SECURITY_TEAM_ID", "").strip()

# Fast discovery interval - how often to check for new tickets
DISCOVERY_INTERVAL = int(os.getenv("ITOP_DISCOVERY_INTERVAL", "2"))
# Full sync interval - how often to refresh all known ticket data
FULL_SYNC_INTERVAL = int(os.getenv("ITOP_FULL_SYNC_INTERVAL", "60"))

TICKET_CLASSES = [
    "Incident",
    "RoutineChange",
    "NormalChange",
    "EmergencyChange",
    "UserRequest",
]

_MAX_KEY_FILE = "/app/data/.itop_max_keys.json"

def _to_int(val):
    """Convert iTop field to int or None."""
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


_async_session = None


def _get_session():
    global _async_session
    if _async_session is None:
        import aiohttp
        _async_session = aiohttp.ClientSession(
            auth=aiohttp.BasicAuth(ITOP_USER, ITOP_PASSWORD),
            timeout=aiohttp.ClientTimeout(total=15),
        )
    return _async_session


async def itop_request(operation: str, **fields):
    """Make an iTop REST API v1.4 request.

    Payload is wrapped in json_data as required by iTop v3.2.1.
    """
    if not ITOP_BASE or not ITOP_USER or not ITOP_PASSWORD:
        return {"code": -1, "error": "iTop is not configured. Set ITOP_HOST, ITOP_USER, and ITOP_PASSWORD or disable iTop sync."}
    session = _get_session()
    payload = {
        "operation": operation,
        "user": ITOP_USER,
        "password": ITOP_PASSWORD,
        **fields,
    }
    form_data = {
        "version": "1.4",
        "json_output": "1",
        "json_data": json.dumps(payload),
    }
    try:
        async with session.post(ITOP_BASE, data=form_data) as resp:
            result = await resp.json()
            return result
    except Exception as e:
        print(f"iTop API error ({operation}): {e}")
        await log_event("sync", "error", "itop_sync", "api_error",
                        operation, {"error": str(e)})
        return {"code": -1, "error": str(e)}


# ---------------------------------------------------------------------------
# Provider state management
# ---------------------------------------------------------------------------

def _load_max_keys() -> dict:
    try:
        with open(_MAX_KEY_FILE, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_max_keys(data: dict):
    os.makedirs(os.path.dirname(_MAX_KEY_FILE), exist_ok=True)
    with open(_MAX_KEY_FILE, "w") as f:
        json.dump(data, f)


# ---------------------------------------------------------------------------
# iTopProvider implementation
# ---------------------------------------------------------------------------

class iTopProvider(TicketProvider):
    name = "itop"
    ticket_classes = TICKET_CLASSES

    async def connect(self):
        result = await itop_request("core/check_credentials")
        self._connected = result.get("code") == 0
        await log_event("sync", "info", "itop_sync", "connection_status",
                        "connected" if self._connected else "disconnected")
        return self._connected

    async def is_connected(self) -> bool:
        if not self._connected:
            await self.connect()
        return self._connected

    async def discover_new(self) -> list:
        """Quick discovery: scan each class for new keys beyond known max.

        Returns list of {"class": str, "key": int} for newly found tickets.
        """
        if not await self.is_connected():
            return []

        new_tickets = []
        max_keys = _load_max_keys()

        for itop_class in self.ticket_classes:
            prev_max = max_keys.get(itop_class, 0)
            scan_start = prev_max + 1 if prev_max > 0 else 1
            consecutive_missing = 0

            for k in range(scan_start, scan_start + 20):
                result = await itop_request("core/get", **{
                    "class": itop_class, "key": str(k), "output_fields": "title"
                })
                if result.get("code") == 0 and result.get("objects"):
                    new_tickets.append({"class": itop_class, "key": k})
                    max_keys[itop_class] = k
                    consecutive_missing = 0
                else:
                    consecutive_missing += 1
                    if consecutive_missing >= 3:
                        break

        _save_max_keys(max_keys)
        if new_tickets:
            await log_event("sync", "info", "itop_sync", "discovery_new_tickets",
                            str(len(new_tickets)))
        return new_tickets

    async def sync_ticket(self, ticket_class: str, ticket_key) -> dict:
        """Sync a single ticket to local DB."""
        result = await itop_request("core/get", **{
            "class": ticket_class, "key": str(ticket_key)
        })
        if result.get("code") != 0:
            return {"error": f"iTop API error: {result.get('message', 'unknown')}"}

        objects = result.get("objects", {})
        if not objects:
            return {"error": "No objects returned"}

        obj_data = list(objects.values())[0]
        fields = obj_data.get("fields", {})
        key_val = fields.get("key") or ticket_key

        ticket_data = {
            "itop_ref": str(key_val),
            "itop_class": ticket_class,
            "provider": "itop",
            "provider_ref": str(key_val),
            "provider_class": ticket_class,
            "title": fields.get("title", ""),
            "description": fields.get("description", ""),
            "status": fields.get("status", ""),
            "priority": fields.get("priority", ""),
            "impact": _to_int(fields.get("impact")),
            "urgency": _to_int(fields.get("urgency")),
            "assignee": fields.get("assignee_name", ""),
            "assignee_team": fields.get("team_name", ""),
        }

        exists = await fetchval(
            "SELECT id FROM tickets WHERE itop_ref = $1 AND itop_class = $2",
            str(key_val), ticket_class
        )
        if exists:
            await execute("""
                UPDATE tickets SET
                    title = $1, description = $2, status = $3, priority = $4,
                    impact = $5, urgency = $6, assignee = $7, assignee_team = $8,
                    provider = 'itop', provider_ref = $9, provider_class = $10,
                    provider_sync_status = 'synced', provider_last_error = NULL,
                    provider_payload = $11, synced_at = NOW(), updated_at = NOW()
                WHERE itop_ref = $9 AND itop_class = $10
            """, ticket_data["title"], ticket_data["description"],
                ticket_data["status"], ticket_data["priority"],
                ticket_data["impact"], ticket_data["urgency"],
                ticket_data["assignee"], ticket_data["assignee_team"],
                str(key_val), ticket_class, json_dumps(obj_data))
        else:
            await execute("""
                INSERT INTO tickets (itop_ref, itop_class, title, description, status,
                                    priority, impact, urgency, assignee, assignee_team,
                                    provider, provider_ref, provider_class, provider_sync_status,
                                    provider_payload, synced_at, created_at, updated_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10,
                        'itop', $1, $2, 'synced', $11, NOW(), NOW(), NOW())
            """, str(key_val), ticket_class, ticket_data["title"],
                ticket_data["description"], ticket_data["status"],
                ticket_data["priority"], ticket_data["impact"],
                ticket_data["urgency"], ticket_data["assignee"],
                ticket_data["assignee_team"], json_dumps(obj_data))

        return {"status": "synced", "itop_ref": str(key_val),
                "itop_class": ticket_class, "is_new": not exists}

    async def full_sync(self) -> dict:
        """Sync all known tickets across all classes."""
        synced = 0
        errors = 0
        new_count = 0
        max_keys = _load_max_keys()

        for itop_class in self.ticket_classes:
            prev_max = max_keys.get(itop_class, 0)

            if prev_max == 0:
                found_keys = await self._scan_keys(itop_class, start=1)
            else:
                new_keys = await self._scan_keys(itop_class, start=prev_max + 1)
                all_keys = list(range(1, prev_max + 1)) + new_keys
                found_keys = all_keys

            if found_keys:
                max_keys[itop_class] = max(found_keys)

            for key in found_keys:
                try:
                    result = await self.sync_ticket(itop_class, key)
                    if "error" not in result:
                        synced += 1
                        if result.get("is_new"):
                            new_count += 1
                    else:
                        errors += 1
                except Exception as e:
                    print(f"Sync error for {itop_class}::{key}: {e}")
                    errors += 1

        _save_max_keys(max_keys)
        await log_event("sync", "info", "itop_sync", "full_sync_complete",
                        f"classes={len(self.ticket_classes)}",
                        {"synced": synced, "new": new_count, "errors": errors})
        return {"synced": synced, "errors": errors, "new": new_count}

    async def create_ticket(self, ticket_id: int, fields: dict) -> dict:
        """Create an iTop ticket from a canonical dashboard ticket.

        iTop requires environment-specific defaults for outbound creation. The
        adapter refuses to create Incident/UserRequest tickets until those
        defaults are configured, so the dashboard can mark the canonical record
        as `create_failed` instead of losing work or claiming a false sync.
        """
        ticket_class = fields.get("provider_class") or fields.get("ticket_class") or "UserRequest"
        create_fields = {
            "title": fields.get("title") or f"SOC Dashboard ticket {ticket_id}",
            "description": fields.get("description") or "",
        }
        if fields.get("priority"):
            create_fields["priority"] = fields["priority"]

        requires_caller = ticket_class in ("Incident", "UserRequest")
        if ITOP_DEFAULT_ORG_ID:
            create_fields["org_id"] = ITOP_DEFAULT_ORG_ID
        if ITOP_DEFAULT_CALLER_ID:
            create_fields["caller_id"] = ITOP_DEFAULT_CALLER_ID
        if ITOP_SECURITY_TEAM_ID:
            create_fields["team_id"] = ITOP_SECURITY_TEAM_ID

        if requires_caller and (not ITOP_DEFAULT_ORG_ID or not ITOP_DEFAULT_CALLER_ID):
            return {
                "error": "Missing ITOP_DEFAULT_ORG_ID or ITOP_DEFAULT_CALLER_ID for outbound iTop ticket creation.",
                "provider": "itop",
                "ticket_id": ticket_id,
                "ticket_class": ticket_class,
            }

        result = await itop_request("core/create", **{
            "class": ticket_class,
            "comment": "Created by SOC Dashboard canonical ticket sync",
            "fields": create_fields,
            "output_fields": "id,friendlyname,title,status",
        })
        if result.get("code") != 0:
            return {
                "error": result.get("message") or result.get("error") or "iTop create failed",
                "provider": "itop",
                "ticket_id": ticket_id,
                "ticket_class": ticket_class,
                "raw": result,
            }

        objects = result.get("objects") or {}
        provider_ref = None
        if objects:
            first_key, first_obj = next(iter(objects.items()))
            obj_fields = (first_obj or {}).get("fields") or {}
            provider_ref = str(obj_fields.get("key") or obj_fields.get("id") or first_key).split("::")[-1]
        if not provider_ref:
            provider_ref = str(result.get("id") or ticket_id)

        await execute("""
            UPDATE tickets
            SET itop_ref = $1,
                itop_class = $2,
                provider = 'itop',
                provider_ref = $1,
                provider_class = $2,
                provider_sync_status = 'synced',
                provider_last_error = NULL,
                provider_payload = $3,
                synced_at = NOW(),
                updated_at = NOW()
            WHERE id = $4
        """, provider_ref, ticket_class, json_dumps(result), ticket_id)
        await log_event("sync", "info", "itop_sync", "ticket_created",
                        f"ticket_{ticket_id}", {"provider_ref": provider_ref, "ticket_class": ticket_class})
        return {
            "status": "created",
            "provider": "itop",
            "ticket_id": ticket_id,
            "provider_ref": provider_ref,
            "provider_class": ticket_class,
        }

    async def _scan_keys(self, itop_class: str, start: int = 1) -> list:
        """Scan for existing keys in a class, stopping after 3 consecutive misses."""
        found = []
        consecutive_missing = 0
        for k in range(start, start + 50):
            result = await itop_request("core/get", **{
                "class": itop_class, "key": str(k), "output_fields": "title"
            })
            if result.get("code") == 0 and result.get("objects"):
                found.append(k)
                consecutive_missing = 0
            else:
                consecutive_missing += 1
                if consecutive_missing >= 3:
                    break
        return found

    async def update_ticket(self, ticket_id: int, fields: dict) -> dict:
        """Push changes back to iTop."""
        ticket = await fetchrow("SELECT itop_ref, itop_class FROM tickets WHERE id = $1",
                               ticket_id)
        if not ticket:
            return {"error": "Ticket not found"}

        update_fields = {}
        if "status" in fields:
            update_fields["status"] = fields["status"]
        if "title" in fields:
            update_fields["title"] = fields["title"]

        result = await itop_request("core/update", **{
            "class": ticket["itop_class"],
            "key": ticket["itop_ref"],
            "comment": "Updated via SOC Dashboard",
            "fields": update_fields,
        })

        if result.get("code") == 0:
            for field, value in fields.items():
                if field in ("status", "title", "description"):
                    await execute(
                        f"UPDATE tickets SET {field} = $1, updated_at = NOW() WHERE id = $2",
                        value, ticket_id
                    )
            await log_event("sync", "info", "itop_sync", "ticket_updated",
                            f"ticket_{ticket_id}", {"fields": list(update_fields.keys())})
            return {"status": "updated"}
        else:
            return {"error": result.get("message", "Update failed")}

    async def close_ticket(self, ticket_id: int, notes: str) -> dict:
        """Close a ticket in iTop via stimulus."""
        ticket = await fetchrow(
            "SELECT itop_ref, itop_class, status FROM tickets WHERE id = $1",
            ticket_id
        )
        if not ticket:
            return {"error": "Ticket not found"}

        stimulus_result = await itop_request("core/apply_stimulus", **{
            "class": ticket["itop_class"],
            "key": ticket["itop_ref"],
            "stimulus": "ev_resolve",
            "comment": notes,
            "fields": {"solution": notes},
        })

        if stimulus_result.get("code") == 0:
            await execute(
                "UPDATE tickets SET status = 'resolved', updated_at = NOW() WHERE id = $1",
                ticket_id
            )
            await log_event("sync", "info", "itop_sync", "ticket_closed",
                            f"ticket_{ticket_id}")
            return {"status": "resolved"}
        else:
            return {"error": stimulus_result.get("message", "Close failed")}

    async def sync_loop(self, broadcast_fn=None):
        """Real-time sync loop with fast discovery + periodic full refresh."""
        if not await self.is_connected():
            print("iTop sync: cannot connect, skipping")
            return

        print(f"iTop real-time sync started (discovery: {DISCOVERY_INTERVAL}s, "
              f"full refresh: {FULL_SYNC_INTERVAL}s, classes: {', '.join(TICKET_CLASSES)})")
        await log_event("sync", "info", "itop_sync", "loop_started",
                        f"classes={len(TICKET_CLASSES)}")

        # Initial full sync
        try:
            result = await self.full_sync()
            print(f"iTop initial sync: {result['synced']} synced, {result['new']} new, "
                  f"{result['errors']} errors")
            if broadcast_fn:
                await broadcast_fn({
                    "type": "sync_complete",
                    "provider": "itop",
                    "synced": result["synced"],
                    "new": result["new"],
                })
        except Exception as e:
            print(f"iTop initial sync error: {e}")
            await log_event("sync", "error", "itop_sync", "initial_sync_error", str(e))

        full_sync_counter = 0
        while True:
            try:
                new_tickets = await self.discover_new()
                if new_tickets:
                    for nt in new_tickets:
                        result = await self.sync_ticket(nt["class"], nt["key"])
                        if "error" not in result:
                            print(f"iTop new ticket: {nt['class']}::{nt['key']} - "
                                  f"{result.get('title', 'synced')}")
                            if broadcast_fn:
                                await broadcast_fn({
                                    "type": "ticket_synced",
                                    "provider": "itop",
                                    "itop_ref": result.get("itop_ref"),
                                    "itop_class": result.get("itop_class"),
                                    "is_new": result.get("is_new"),
                                })

                full_sync_counter += 1
                if full_sync_counter >= (FULL_SYNC_INTERVAL // DISCOVERY_INTERVAL):
                    full_sync_counter = 0
                    result = await self.full_sync()
                    if result["errors"] > 0:
                        print(f"iTop full sync: {result['synced']} synced, "
                              f"{result['errors']} errors")

            except Exception as e:
                print(f"Sync loop error: {e}")
                await log_event("sync", "error", "itop_sync", "loop_error", str(e))

            await asyncio.sleep(DISCOVERY_INTERVAL)


# Global provider instance
_provider = None


async def get_provider() -> iTopProvider:
    global _provider
    if _provider is None:
        _provider = iTopProvider()
        await _provider.connect()
    return _provider


async def sync_single_ticket(itop_class, itop_key):
    provider = await get_provider()
    return await provider.sync_ticket(itop_class, itop_key)


async def full_sync():
    provider = await get_provider()
    return await provider.full_sync()


async def sync_loop(broadcast_fn=None):
    provider = await get_provider()
    await provider.sync_loop(broadcast_fn=broadcast_fn)
