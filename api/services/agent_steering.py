"""Non-interrupting steering updates for active ticket agents.

Ticket notes are durable context. This service mirrors human/provider notes to
the active agent workspace as a small inbox so agents can incorporate updated
information without being stopped or respawned.
"""
import json
import os
from datetime import datetime, timezone

from database import fetchall, fetchval, execute, json_dumps
from services.event_logger import log_event


CONTROL_PLANE_SOURCES = {
    "access-request",
    "agent-checkpoint",
    "agent-control-plane",
    "approval-gate",
    "postmortem",
    "ticket-status",
}


def should_steer_from_note(author, source):
    """Return true for human/provider notes that should reach active agents."""
    source_value = str(source or "").strip().lower()
    author_value = str(author or "").strip().lower()
    if not source_value:
        source_value = "dashboard"
    if source_value in CONTROL_PLANE_SOURCES:
        return False
    if source_value.startswith("agent"):
        return False
    if author_value == "agent" or author_value.startswith(("agent-", "agent_", "agent ")):
        return False
    return source_value in {
        "dashboard",
        "itop",
        "jira",
        "provider",
        "requester",
        "servicenow",
        "user-response",
    }


def _compact_body(body, limit=2400):
    text = str(body or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + f"... [truncated {len(text) - limit} chars]"


def _event_payload(event):
    return {
        "id": event.get("id"),
        "ticket_id": event.get("ticket_id"),
        "agent_id": event.get("agent_id"),
        "task_id": event.get("task_id"),
        "note_id": event.get("note_id"),
        "source": event.get("source"),
        "author": event.get("author"),
        "body": _compact_body(event.get("body")),
        "created_at": str(event.get("created_at") or ""),
        "status": event.get("status"),
    }


def _write_text_atomic(path, content):
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as handle:
        handle.write(content)
    os.replace(tmp_path, path)


def _write_json_atomic(path, payload):
    _write_text_atomic(path, json.dumps(payload, indent=2, default=str))


def _render_markdown(payload):
    lines = [
        "# Agent Steering Inbox",
        "",
        "Use these updates as additional ticket context. Do not abandon the original ticket objective; incorporate the update, adjust the next steps if needed, and continue toward completion.",
        "",
    ]
    updates = payload.get("updates") or []
    if not updates:
        lines.append("No steering updates have been delivered yet.")
    for event in updates:
        lines.extend([
            f"## Steering Event {event.get('id')}",
            f"- Source: {event.get('source')}",
            f"- Author: {event.get('author')}",
            f"- Note ID: {event.get('note_id')}",
            f"- Created: {event.get('created_at')}",
            "",
            event.get("body") or "",
            "",
        ])
    return "\n".join(lines).strip() + "\n"


def write_inbox_files(work_dir, agent_id, task_id, ticket_id, events):
    os.makedirs(work_dir, exist_ok=True)
    payload = {
        "agent_id": agent_id,
        "task_id": task_id,
        "ticket_id": ticket_id,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "instructions": (
            "These are human/provider ticket-note updates. Keep the original "
            "ticket objective, incorporate the updates as context, document any "
            "changed decision, and continue unless an update creates an approval "
            "or access gate."
        ),
        "updates": [_event_payload(event) for event in events],
    }
    _write_json_atomic(os.path.join(work_dir, "agent_steering_inbox.json"), payload)
    _write_text_atomic(os.path.join(work_dir, "AGENT_STEERING.md"), _render_markdown(payload))
    return payload


async def initialize_agent_inbox(agent_id, task_id, ticket_id, work_dir):
    """Create the empty inbox and deliver any pending pre-run events."""
    write_inbox_files(work_dir, agent_id, task_id, ticket_id, [])
    return await deliver_pending(agent_id, task_id, work_dir)


async def _active_agent_tasks(ticket_id):
    return await fetchall("""
        SELECT a.id AS agent_id, t.id AS task_id, t.work_dir, t.status AS task_status
        FROM agents a
        JOIN agent_tasks t ON t.agent_id = a.id
        WHERE a.ticket_id = $1
          AND a.status IN ('spawned', 'running', 'working')
          AND t.status IN ('queued', 'running')
        ORDER BY t.created_at DESC
    """, ticket_id)


async def record_ticket_note(ticket_id, note_id, body, author="dashboard", source="dashboard", visibility="internal", external_ref=None):
    """Create steering events for active agents after a note is added."""
    if not should_steer_from_note(author, source):
        return {"status": "skipped", "reason": "non_steering_source", "events": []}

    active = await _active_agent_tasks(ticket_id)
    events = []
    for row in active or []:
        event_id = await fetchval("""
            INSERT INTO agent_steering_events (
                ticket_id, agent_id, task_id, note_id, source, author, body, status, metadata
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, 'pending', $8)
            ON CONFLICT (agent_id, note_id) WHERE note_id IS NOT NULL DO UPDATE SET
                body = EXCLUDED.body,
                source = EXCLUDED.source,
                author = EXCLUDED.author,
                status = 'pending',
                metadata = EXCLUDED.metadata
            RETURNING id
        """, ticket_id, row.get("agent_id"), row.get("task_id"), note_id,
            source or "dashboard", author or "dashboard", body or "",
            json_dumps({
                "visibility": visibility,
                "external_ref": external_ref,
                "delivery": "non_interrupting_workspace_inbox",
            }))
        delivered = None
        if row.get("work_dir"):
            delivered = await deliver_pending(row.get("agent_id"), row.get("task_id"), row.get("work_dir"))
        events.append({
            "id": event_id,
            "agent_id": row.get("agent_id"),
            "task_id": row.get("task_id"),
            "delivered": bool(delivered and delivered.get("delivered_count")),
        })

    if events:
        await log_event("agent", "info", author or "dashboard", "agent_steering_note_recorded",
                        f"ticket_{ticket_id}", {
                            "note_id": note_id,
                            "source": source,
                            "events": events,
                        })
    return {"status": "created" if events else "no_active_agent", "events": events}


async def deliver_pending(agent_id, task_id=None, work_dir=None):
    """Write pending/delivered events to the agent workspace inbox."""
    filters = ["agent_id = $1", "status IN ('pending', 'delivered')"]
    params = [agent_id]
    if task_id is not None:
        params.append(task_id)
        filters.append(f"(task_id = ${len(params)} OR task_id IS NULL)")
    where_sql = " AND ".join(filters)
    events = await fetchall(f"""
        SELECT *
        FROM agent_steering_events
        WHERE {where_sql}
        ORDER BY created_at ASC, id ASC
        LIMIT 50
    """, *params)
    if not events:
        return {"status": "empty", "delivered_count": 0}

    effective_work_dir = work_dir
    if not effective_work_dir:
        task = await fetchall("""
            SELECT work_dir, ticket_id
            FROM agent_tasks
            WHERE agent_id = $1
              AND ($2::integer IS NULL OR id = $2)
            ORDER BY created_at DESC
            LIMIT 1
        """, agent_id, task_id)
        if task:
            effective_work_dir = task[0].get("work_dir")
    if not effective_work_dir:
        return {"status": "pending", "delivered_count": 0, "reason": "missing_work_dir"}

    ticket_id = events[-1].get("ticket_id")
    payload = write_inbox_files(effective_work_dir, agent_id, task_id, ticket_id, events)
    pending_ids = [event["id"] for event in events if event.get("status") == "pending"]
    if pending_ids:
        await execute("""
            UPDATE agent_steering_events
            SET status = 'delivered', delivered_at = COALESCE(delivered_at, NOW())
            WHERE id = ANY($1::int[])
        """, pending_ids)
    await log_event("agent", "info", f"agent_{agent_id}", "agent_steering_delivered",
                    f"task_{task_id or 'latest'}", {
                        "event_ids": [event["id"] for event in events],
                        "work_dir": effective_work_dir,
                    })
    return {"status": "delivered", "delivered_count": len(events), "inbox": payload}


async def acknowledge(agent_id, event_id, actor=None):
    updated = await execute("""
        UPDATE agent_steering_events
        SET status = 'acknowledged', acknowledged_at = NOW()
        WHERE id = $1 AND agent_id = $2
    """, event_id, agent_id)
    await log_event("agent", "info", actor or f"agent_{agent_id}", "agent_steering_acknowledged",
                    f"steering_{event_id}", {"agent_id": agent_id, "db_result": updated})
    return {"status": "acknowledged", "event_id": event_id, "agent_id": agent_id}
