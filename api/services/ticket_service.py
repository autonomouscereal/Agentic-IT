"""Provider-agnostic ticket facade.

The dashboard owns a canonical ticket record in PostgreSQL. Provider adapters
mirror that record to or from iTop, ServiceNow, Jira, etc. Route handlers should
prefer this service over calling provider-specific modules directly.
"""
from datetime import datetime
from database import fetchall, fetchrow, execute, fetchval, json_dumps
from services.event_logger import log_event
try:
    from services.lease_inference import infer_lease_request
except ImportError:  # unit-test stubs may load this service without service package contents
    def infer_lease_request(*args, **kwargs):
        return None
from services.ticket_links import external_ticket_url
from services.workflow_keys import workflow_key_for_ticket


def _loads_json(value):
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            import json
            return json.loads(value)
        except Exception:
            return None
    return None


def _truncate_text(value, limit=500):
    if value is None:
        return value
    text = str(value)
    if len(text) <= limit:
        return text
    return text[:limit] + f"... [truncated {len(text) - limit} chars]"


def compact_ticket_payload(ticket, include_provider_payload=False):
    """Keep agent-facing ticket objects small while preserving useful refs."""
    if not ticket:
        return ticket
    if include_provider_payload:
        return ticket

    payload = ticket.get("provider_payload")
    loaded = _loads_json(payload)
    summary = None
    if isinstance(loaded, dict):
        fields = loaded.get("fields") if isinstance(loaded.get("fields"), dict) else {}
        summary = {
            "key": loaded.get("key") or fields.get("id"),
            "class": loaded.get("class") or ticket.get("provider_class"),
            "code": loaded.get("code"),
            "message": _truncate_text(loaded.get("message"), 240),
            "friendlyname": fields.get("friendlyname") or fields.get("ref"),
            "status": fields.get("status"),
            "team_name": fields.get("team_name"),
            "caller_name": fields.get("caller_name"),
            "escalation_flag": fields.get("escalation_flag"),
            "escalation_reason": _truncate_text(fields.get("escalation_reason"), 240),
        }
    elif payload not in (None, "", {}):
        summary = {"raw_preview": _truncate_text(payload, 500)}

    ticket["provider_payload_summary"] = summary
    ticket.pop("provider_payload", None)
    return ticket


def _local_ref():
    return f"LOCAL-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"


PROVIDER_TICKET_CLASSES = {"Incident", "UserRequest", "RoutineChange", "NormalChange", "EmergencyChange"}


def normalize_ticket_class(ticket_class, fallback="UserRequest"):
    """Normalize dashboard work into provider-compatible ticket classes."""
    value = str(ticket_class or fallback or "UserRequest").strip()
    aliases = {
        "Change": "RoutineChange",
        "ServiceRequest": "UserRequest",
        "Service Request": "UserRequest",
        "Request": "UserRequest",
        "Task": "UserRequest",
        "Bug": "Incident",
        "Story": "UserRequest",
    }
    value = aliases.get(value, value)
    if value in PROVIDER_TICKET_CLASSES:
        return value
    lowered = value.lower()
    if "phish" in lowered or "incident" in lowered or "alert" in lowered or "edr" in lowered:
        return "Incident"
    if "change" in lowered or "deploy" in lowered or "cicd" in lowered or "setup" in lowered:
        return "RoutineChange"
    return fallback if fallback in PROVIDER_TICKET_CLASSES else "UserRequest"


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _can_outbound_create(provider, ticket_class):
    return provider != "local"


async def create_ticket(
    title,
    description="",
    ticket_class="UserRequest",
    status="new",
    priority=None,
    provider=None,
    provider_ref=None,
    provider_class=None,
    sync_provider=None,
    assignee=None,
    assignee_team=None,
    created_by="dashboard",
    auto_assign=True,
):
    """Create a canonical local ticket.

    By default the service syncs to the active ticket provider when one is
    configured, and falls back to local-only when no external provider is ready.
    """
    from services import provider_registry

    ticket_class = normalize_ticket_class(ticket_class)
    provider_class = normalize_ticket_class(provider_class, ticket_class) if provider_class else ticket_class
    requested_provider = provider
    provider = provider_registry.default_ticket_provider(provider)
    if provider != "local" and not _can_outbound_create(provider, ticket_class):
        await log_event("sync", "warning", created_by, "provider_auto_sync_unavailable",
                        "ticket_create", {
                            "requested_provider": provider,
                            "ticket_class": ticket_class,
                            "reason": "provider outbound create is not available",
                        })
        provider = "local"
    sync_provider = provider != "local" if sync_provider is None else bool(sync_provider or provider != "local")
    provider_ref = provider_ref or _local_ref()
    provider_class = provider_class or ticket_class
    itop_ref = provider_ref if provider == "itop" else provider_ref
    itop_class = provider_class
    sync_status = "pending_create" if sync_provider else ("local_only" if provider == "local" else "synced")
    synced_at = datetime.now() if sync_status == "synced" else None

    ticket_id = await fetchval("""
        INSERT INTO tickets (
            itop_ref, itop_class, title, description, status, priority,
            assignee, assignee_team, provider, provider_ref, provider_class,
            provider_sync_status,
            synced_at, created_at, updated_at
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, NOW(), NOW())
        ON CONFLICT (itop_ref, itop_class) DO UPDATE SET
            title = EXCLUDED.title,
            description = EXCLUDED.description,
            status = EXCLUDED.status,
            priority = EXCLUDED.priority,
            assignee = COALESCE(EXCLUDED.assignee, tickets.assignee),
            assignee_team = COALESCE(EXCLUDED.assignee_team, tickets.assignee_team),
            provider = EXCLUDED.provider,
            provider_ref = EXCLUDED.provider_ref,
            provider_class = EXCLUDED.provider_class,
            provider_sync_status = EXCLUDED.provider_sync_status,
            updated_at = NOW()
        RETURNING id
    """, itop_ref, itop_class, title, description, status, priority,
        assignee, assignee_team, provider, provider_ref, provider_class,
        sync_status, synced_at)

    await log_event("ticket", "info", created_by, "ticket_created",
                    f"ticket_{ticket_id}", {
                        "provider": provider,
                        "requested_provider": requested_provider,
                        "sync_provider": sync_provider,
                    })

    if sync_provider:
        provider_result = await provider_registry.create_ticket(provider, ticket_id, {
            "title": title,
            "description": description,
            "ticket_class": ticket_class,
            "provider_class": provider_class,
            "priority": priority,
            "created_by": created_by,
        })
        if provider_result.get("error"):
            await execute("""
                UPDATE tickets
                SET provider_sync_status = 'create_failed',
                    provider_last_error = $1,
                    provider_payload = $2,
                    updated_at = NOW()
                WHERE id = $3
            """, provider_result["error"], json_dumps(provider_result), ticket_id)
            await log_event("sync", "error", created_by, "provider_create_failed",
                            f"ticket_{ticket_id}", provider_result)
        elif provider_result.get("status") == "local_only":
            await execute("""
                UPDATE tickets
                SET provider_sync_status = 'local_only',
                    provider_payload = $1,
                    updated_at = NOW()
                WHERE id = $2
            """, json_dumps(provider_result), ticket_id)
        else:
            await execute("""
                UPDATE tickets
                SET provider = $1::varchar,
                    itop_ref = CASE WHEN lower($1::varchar) = 'itop' THEN COALESCE($2, itop_ref) ELSE itop_ref END,
                    itop_class = CASE WHEN lower($1::varchar) = 'itop' THEN COALESCE($3, itop_class) ELSE itop_class END,
                    provider_ref = COALESCE($2, provider_ref),
                    provider_class = COALESCE($3, provider_class),
                    provider_url = COALESCE($4, provider_url),
                    provider_sync_status = 'synced',
                    provider_last_error = NULL,
                    provider_payload = $5,
                    synced_at = NOW(),
                    updated_at = NOW()
                WHERE id = $6
            """, provider_result.get("provider") or provider,
                provider_result.get("provider_ref"),
                provider_result.get("provider_class"),
                provider_result.get("provider_url"),
                json_dumps(provider_result),
                ticket_id)
            await log_event("sync", "info", created_by, "provider_create_complete",
                            f"ticket_{ticket_id}", provider_result)
    ticket = await get_ticket(ticket_id)
    if auto_assign:
        try:
            from services import auto_assignment
            ticket["auto_assignment"] = await auto_assignment.maybe_auto_assign(ticket_id, source=created_by)
        except Exception as exc:
            ticket["auto_assignment"] = {"status": "error", "error": str(exc)}
            await log_event("agent", "error", created_by, "auto_assignment_failed",
                            f"ticket_{ticket_id}", {"error": str(exc)})
    return ticket


async def get_ticket(ticket_id):
    ticket = await fetchrow("SELECT * FROM tickets WHERE id = $1", ticket_id)
    if ticket:
        ticket["external_url"] = ticket.get("provider_url") or external_ticket_url(ticket)
        compact_ticket_payload(ticket)
    return ticket


async def push_to_provider(ticket_id, provider=None):
    ticket = await fetchrow("SELECT * FROM tickets WHERE id = $1", ticket_id)
    if not ticket:
        return {"error": "Ticket not found"}

    target_provider = provider or ticket.get("provider") or "local"
    from services import provider_registry
    result = await provider_registry.create_ticket(target_provider, ticket_id, {
        "title": ticket.get("title"),
        "description": ticket.get("description"),
        "ticket_class": ticket.get("itop_class"),
        "provider_class": ticket.get("provider_class") or ticket.get("itop_class"),
        "priority": ticket.get("priority"),
        "created_by": "dashboard",
    })
    if result.get("error"):
        await execute("""
            UPDATE tickets
            SET provider = $1,
                provider_sync_status = 'create_failed',
                provider_last_error = $2,
                provider_payload = $3,
                updated_at = NOW()
            WHERE id = $4
        """, target_provider, result["error"], json_dumps(result), ticket_id)
        await log_event("sync", "error", "dashboard", "provider_push_failed",
                        f"ticket_{ticket_id}", result)
        return result

    if result.get("status") == "local_only":
        await execute("""
            UPDATE tickets
            SET provider = $1,
                provider_sync_status = 'local_only',
                provider_payload = $2,
                updated_at = NOW()
            WHERE id = $3
        """, target_provider, json_dumps(result), ticket_id)
    else:
        await execute("""
            UPDATE tickets
            SET provider = $1::varchar,
                itop_ref = CASE WHEN lower($1::varchar) = 'itop' THEN COALESCE($2, itop_ref) ELSE itop_ref END,
                itop_class = CASE WHEN lower($1::varchar) = 'itop' THEN COALESCE($3, itop_class) ELSE itop_class END,
                provider_ref = COALESCE($2, provider_ref),
                provider_class = COALESCE($3, provider_class),
                provider_url = COALESCE($4, provider_url),
                provider_sync_status = 'synced',
                provider_last_error = NULL,
                provider_payload = $5,
                synced_at = NOW(),
                updated_at = NOW()
            WHERE id = $6
        """, result.get("provider") or target_provider,
            result.get("provider_ref"),
            result.get("provider_class"),
            result.get("provider_url"),
            json_dumps(result),
            ticket_id)

    await log_event("sync", "info", "dashboard", "provider_push_complete",
                    f"ticket_{ticket_id}", result)
    return result


async def add_note(ticket_id, body, author="dashboard", source="dashboard", visibility="internal", external_ref=None):
    if not await fetchrow("SELECT id FROM tickets WHERE id = $1", ticket_id):
        return {"error": "Ticket not found"}
    note_id = await fetchval("""
        INSERT INTO ticket_notes (ticket_id, source, author, body, visibility, external_ref)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id
    """, ticket_id, source, author, body, visibility, external_ref)
    await execute("UPDATE tickets SET updated_at = NOW() WHERE id = $1", ticket_id)
    await log_event("ticket", "info", author, "ticket_note_added",
                    f"ticket_{ticket_id}", {"note_id": note_id, "visibility": visibility})
    steering = {"status": "not_checked"}
    try:
        from services import agent_steering
        steering = await agent_steering.record_ticket_note(
            ticket_id,
            note_id,
            body,
            author=author,
            source=source,
            visibility=visibility,
            external_ref=external_ref,
        )
    except Exception as exc:
        steering = {"status": "error", "error": str(exc)}
        await log_event("agent", "warning", author, "agent_steering_note_failed",
                        f"ticket_{ticket_id}", {"note_id": note_id, "error": str(exc)})
    return {"id": note_id, "ticket_id": ticket_id, "status": "created", "steering": steering}


async def add_attachment_metadata(
    ticket_id,
    filename,
    content_type=None,
    storage_ref=None,
    sha256=None,
    size_bytes=None,
    note_id=None,
    metadata=None,
):
    if not await fetchrow("SELECT id FROM tickets WHERE id = $1", ticket_id):
        return {"error": "Ticket not found"}
    attachment_id = await fetchval("""
        INSERT INTO ticket_attachments (
            ticket_id, note_id, filename, content_type, storage_ref,
            sha256, size_bytes, metadata
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        RETURNING id
    """, ticket_id, note_id, filename, content_type, storage_ref,
        sha256, size_bytes, json_dumps(metadata or {}))
    await log_event("ticket", "info", "dashboard", "ticket_attachment_added",
                    f"ticket_{ticket_id}", {"attachment_id": attachment_id, "filename": filename})
    return {"id": attachment_id, "ticket_id": ticket_id, "status": "created"}


async def get_context(ticket_id):
    ticket = await get_ticket(ticket_id)
    if not ticket:
        return {"error": "Ticket not found"}

    notes = await fetchall(
        "SELECT * FROM ticket_notes WHERE ticket_id = $1 ORDER BY created_at ASC",
        ticket_id,
    )
    attachments = await fetchall(
        "SELECT * FROM ticket_attachments WHERE ticket_id = $1 ORDER BY created_at ASC",
        ticket_id,
    )
    changes = await fetchall(
        "SELECT * FROM change_requests WHERE ticket_id = $1 ORDER BY requested_at DESC",
        ticket_id,
    )
    access_requests = await fetchall("""
        SELECT ar.*, at.title AS access_ticket_title, at.status AS access_ticket_status,
               at.provider AS access_ticket_provider, at.provider_ref AS access_ticket_provider_ref,
               cr.status AS change_status, cr.approved_by, cr.approved_at
        FROM access_requests ar
        LEFT JOIN tickets at ON at.id = ar.access_ticket_id
        LEFT JOIN change_requests cr ON cr.id = ar.change_id
        WHERE ar.parent_ticket_id = $1 OR ar.access_ticket_id = $1
        ORDER BY ar.created_at DESC
    """, ticket_id)
    tasks = await fetchall(
        "SELECT * FROM agent_tasks WHERE ticket_id = $1 ORDER BY created_at DESC LIMIT 20",
        ticket_id,
    )
    steering_events = await fetchall(
        "SELECT * FROM agent_steering_events WHERE ticket_id = $1 ORDER BY created_at DESC LIMIT 30",
        ticket_id,
    )
    postmortems = await fetchall(
        "SELECT * FROM postmortems WHERE ticket_id = $1 ORDER BY created_at DESC",
        ticket_id,
    )
    related = await fetchall("""
        SELECT id, itop_ref, itop_class, title, status, provider, provider_ref, updated_at
        FROM tickets
        WHERE id <> $1
          AND (
            lower(title) = lower($2)
            OR itop_class = $3
            OR provider_class = $4
          )
        ORDER BY updated_at DESC
        LIMIT 10
    """, ticket_id, ticket.get("title") or "", ticket.get("itop_class"), ticket.get("provider_class"))
    articles = await fetchall("""
        SELECT * FROM knowledge_articles
        WHERE enabled = true
          AND (
            category IS NULL
            OR category ILIKE $1
            OR title ILIKE $2
            OR body ILIKE $2
          )
        ORDER BY updated_at DESC
        LIMIT 10
    """, f"%{ticket.get('itop_class') or ''}%", f"%{(ticket.get('title') or '')[:80]}%")
    workflow_key = workflow_key_for_ticket(ticket)
    workflows = await fetchall("""
        WITH ranked AS (
            SELECT w.*,
                   COALESCE(run_stats.completed_count, 0) AS completed_run_count,
                   ROW_NUMBER() OVER (
                       PARTITION BY COALESCE(w.workflow_key, w.name)
                       ORDER BY
                         CASE
                           WHEN w.workflow_key = $3 AND w.status = 'active' AND w.reviewed_at IS NOT NULL THEN 0
                           WHEN w.workflow_key = $3 AND w.status IN ('active', 'approved') THEN 1
                           WHEN w.workflow_key = $3 AND w.status = 'tested' THEN 2
                           WHEN w.workflow_key = $3 AND w.status = 'ready_for_review' THEN 3
                           WHEN w.status = 'active' AND w.reviewed_at IS NOT NULL THEN 4
                           WHEN w.status IN ('active', 'approved') THEN 5
                           ELSE 6
                         END,
                         COALESCE(run_stats.completed_count, 0) DESC,
                         w.updated_at DESC
                   ) AS rank_num
            FROM agent_workflows w
            LEFT JOIN LATERAL (
                SELECT COUNT(*) FILTER (WHERE status IN ('completed', 'passed')) AS completed_count
                FROM workflow_runs wr
                WHERE wr.workflow_id = w.id
            ) run_stats ON true
            WHERE w.status IN ('draft', 'ready_for_review', 'tested', 'approved', 'active')
              AND (w.ticket_class IS NULL OR w.ticket_class = $1 OR w.ticket_class = $2)
        )
        SELECT *
        FROM ranked
        WHERE rank_num = 1
        ORDER BY
          CASE WHEN workflow_key = $3 THEN 0 ELSE 1 END,
          CASE status WHEN 'active' THEN 0 WHEN 'approved' THEN 1 WHEN 'tested' THEN 2 WHEN 'ready_for_review' THEN 3 ELSE 4 END,
          completed_run_count DESC,
          updated_at DESC
        LIMIT 10
    """, ticket.get("itop_class"), ticket.get("provider_class"), workflow_key)
    skills = await fetchall(
        "SELECT id, name, description, category, prompt_template FROM agent_skills "
        "WHERE enabled = true AND assigned_to_all = true ORDER BY category, name"
    )

    return {
        "ticket": ticket,
        "notes": notes,
        "attachments": attachments,
        "change_requests": changes,
        "access_requests": access_requests,
        "tasks": tasks,
        "steering_events": steering_events,
        "postmortems": postmortems,
        "related_tickets": related,
        "knowledge_articles": articles,
        "workflows": workflows,
        "skills": skills,
    }


async def create_knowledge_article(title, body, category=None, source="dashboard", tags=None, external_ref=None):
    article_id = await fetchval("""
        INSERT INTO knowledge_articles (title, body, category, source, tags, external_ref)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id
    """, title, body, category, source, json_dumps(_as_list(tags)), external_ref)
    await log_event("knowledge", "info", source, "knowledge_article_created",
                    f"article_{article_id}", {"category": category})
    return {"id": article_id, "status": "created"}


async def create_access_request(
    parent_ticket_id,
    resource,
    permission,
    reason,
    agent_id=None,
    requester=None,
    account_ref=None,
    assignment_group="Identity & Access",
    risk_level="medium",
    sync_provider=None,
    created_by="agent-access-request",
    lease_request=None,
):
    """Create a child access request plus an approval gate for the original work.

    The access request ticket is assigned to the RACI/access-owning group. The
    change request stays linked to the original ticket and agent so approval can
    resume the blocked work without creating duplicate ticket agents.
    """
    parent = await fetchrow("SELECT * FROM tickets WHERE id = $1", parent_ticket_id)
    if not parent:
        return {"error": "Parent ticket not found"}
    if not resource or not permission:
        return {"error": "resource and permission are required"}

    requester = requester or (f"agent_{agent_id}" if agent_id else created_by)
    assignment_group = assignment_group or "Identity & Access"
    risk_level = risk_level or "medium"
    title = f"Access request: {permission} for {resource}"
    description = "\n".join([
        f"Parent ticket: {parent_ticket_id} - {parent.get('title')}",
        f"Requester: {requester}",
        f"Account/reference: {account_ref or 'not specified'}",
        f"Resource: {resource}",
        f"Permission needed: {permission}",
        f"Assignment group: {assignment_group}",
        "",
        "Reason:",
        reason or "Agent reported a permission blocker while working the parent ticket.",
        "",
        "Approval requirement:",
        "Grant only the minimum role or group membership needed. Record evidence, owner approval, expiration/review date, and rollback path before marking the gate complete.",
    ])

    access_ticket = await create_ticket(
        title=title,
        description=description,
        ticket_class="UserRequest",
        status="new",
        priority="P3",
        sync_provider=sync_provider,
        assignee_team=assignment_group,
        created_by=created_by,
        auto_assign=False,
    )
    access_ticket_id = access_ticket.get("id")

    approval_policy = {
        "source": "permission-wall-access-request",
        "access_request": True,
        "access_request_ticket_id": access_ticket_id,
        "parent_ticket_id": parent_ticket_id,
        "resource": resource,
        "permission": permission,
        "account_ref": account_ref,
        "assignment_group": assignment_group,
        "auto_complete": False,
    }
    inferred_lease_request = None
    if isinstance(lease_request, dict) and lease_request.get("system"):
        approval_policy["lease_request"] = {
            "system": lease_request.get("system"),
            "resource_type": lease_request.get("resource_type") or "resource",
            "resource_id": lease_request.get("resource_id") or "*",
            "action": lease_request.get("action") or "read",
            "credential_ref": lease_request.get("credential_ref"),
            "expires_at": lease_request.get("expires_at"),
        }
    else:
        inferred_lease_request = infer_lease_request(resource, permission, account_ref)
        if inferred_lease_request:
            approval_policy["lease_request"] = inferred_lease_request
            approval_policy["lease_request_inferred"] = True
    change_id = await fetchval("""
        INSERT INTO change_requests (
            agent_id, ticket_id, action, target, reason, risk_level,
            approval_policy, status, requested_by, requested_at, expires_at
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, 'pending', $8,
                NOW(), NOW() + INTERVAL '7 days')
        RETURNING id
    """, agent_id,
        parent_ticket_id,
        "Grant least-privilege account access",
        resource,
        reason or "Agent cannot continue without approved access.",
        risk_level,
        json_dumps(approval_policy),
        f"agent_{agent_id}" if agent_id else created_by)

    access_request_id = await fetchval("""
        INSERT INTO access_requests (
            parent_ticket_id, access_ticket_id, agent_id, change_id, requester,
            account_ref, resource, permission, reason, assignment_group, status
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, 'pending_approval')
        RETURNING id
    """, parent_ticket_id, access_ticket_id, agent_id, change_id, requester,
        account_ref, resource, permission, reason, assignment_group)

    parent_note = "\n".join([
        "Access request opened",
        f"- Access request id: {access_request_id}",
        f"- Access ticket: {access_ticket_id}",
        f"- Approval gate: {change_id}",
        f"- Resource: {resource}",
        f"- Permission: {permission}",
        f"- Assignment group: {assignment_group}",
        f"- Reason: {reason or 'Permission blocker reported.'}",
        "",
        "The original agent must wait here until the access gate is approved.",
    ])
    await add_note(
        parent_ticket_id,
        parent_note,
        author=f"agent-{agent_id}" if agent_id else created_by,
        source="access-request",
        visibility="internal",
        external_ref=f"access_request:{access_request_id}",
    )
    await add_note(
        access_ticket_id,
        f"Access request `{access_request_id}` was created from parent ticket `{parent_ticket_id}`. Approval gate `{change_id}` controls the parent ticket resume.",
        author=created_by,
        source="access-request",
        visibility="internal",
        external_ref=f"parent_ticket:{parent_ticket_id}",
    )

    await execute("""
        INSERT INTO audit_log (actor, action, target, details)
        VALUES ($1, 'access_request_created', $2, $3)
    """, f"agent_{agent_id}" if agent_id else created_by,
        f"access_request_{access_request_id}",
        json_dumps({
            "parent_ticket_id": parent_ticket_id,
            "access_ticket_id": access_ticket_id,
            "agent_id": agent_id,
            "change_id": change_id,
            "resource": resource,
            "permission": permission,
            "assignment_group": assignment_group,
            "lease_request": approval_policy.get("lease_request"),
            "lease_request_inferred": bool(inferred_lease_request),
        }))
    await log_event("access", "info", f"agent_{agent_id}" if agent_id else created_by,
                    "access_request_created", f"access_request_{access_request_id}", {
                        "parent_ticket_id": parent_ticket_id,
                        "access_ticket_id": access_ticket_id,
                        "agent_id": agent_id,
                        "change_id": change_id,
                        "assignment_group": assignment_group,
                        "lease_request": approval_policy.get("lease_request"),
                        "lease_request_inferred": bool(inferred_lease_request),
                    })

    return {
        "status": "pending_approval",
        "access_request_id": access_request_id,
        "parent_ticket_id": parent_ticket_id,
        "access_ticket_id": access_ticket_id,
        "change_id": change_id,
        "resource": resource,
        "permission": permission,
        "assignment_group": assignment_group,
        "access_ticket": access_ticket,
    }
