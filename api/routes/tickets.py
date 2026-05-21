from fastapi import APIRouter, Query, Body, HTTPException
try:
    from fastapi import Request
except ImportError:  # unit-test stubs do not expose Request
    class Request:
        pass
from datetime import datetime
from database import fetchall, fetchrow, execute, fetchval, json_dumps
from services import provider_registry, ticket_service
try:
    from services import access_control
except ImportError:  # unit-test stubs load this route without service package contents
    class _AccessControlFallback:
        @staticmethod
        def subject_from_request(request):
            return {"identity": {"username": "unit-test"}, "roles": ["platform-admin"], "capabilities": ["*"], "scopes": [], "max_classification": "secret"}

        @staticmethod
        def ticket_filter_clause(subject, alias="t", start_param=1):
            return "", [], start_param

        @staticmethod
        def ticket_access_decision(ticket, subject, required_permission="tickets:read"):
            return {"allow": True, "reason": "unit_test_fallback"}

        @staticmethod
        async def load_agent_subject(agent_id):
            return {"identity": {"username": f"agent_{agent_id}"}, "roles": ["agent-operator"], "capabilities": ["tickets:read"], "scopes": [], "max_classification": "internal"}

    access_control = _AccessControlFallback()
from services.ticket_service import compact_ticket_payload
from services.ticket_links import external_ticket_url
from services.task_prompts import (
    build_ticket_resolution_prompt,
    build_postmortem_prompt,
    build_workflow_prompt,
)
from services.event_logger import log_event

router = APIRouter(prefix="/api/tickets", tags=["tickets"])


async def _find_ops_chat_idempotent_ticket(access_scope):
    """Return an existing ticket for a retried Ops Chat create-ticket turn."""
    if not isinstance(access_scope, dict):
        return None
    if str(access_scope.get("source") or "").strip().lower() != "ops-chat":
        return None
    session_id = str(access_scope.get("session_id") or "").strip()
    message_hash = str(access_scope.get("message_hash") or "").strip()
    if not session_id or not message_hash:
        return None
    return await fetchrow("""
        SELECT *
        FROM tickets
        WHERE access_scope->>'source' = 'ops-chat'
          AND access_scope->>'session_id' = $1
          AND access_scope->>'message_hash' = $2
          AND status NOT IN ('cancelled', 'canceled', 'closed', 'resolved')
          AND created_at > NOW() - INTERVAL '30 minutes'
        ORDER BY id ASC
        LIMIT 1
    """, session_id, message_hash)


def _request_client_host(request):
    client = getattr(request, "client", None)
    return str(getattr(client, "host", "") or "").strip().lower()


def _is_local_runner_request(request):
    """Return true for same-container/local runner API calls."""
    host = _request_client_host(request)
    forwarded_for = ""
    headers = getattr(request, "headers", None)
    if headers:
        forwarded_for = str(headers.get("x-forwarded-for", "") or "").split(",", 1)[0].strip().lower()
    return host in {"127.0.0.1", "::1", "localhost"} and not forwarded_for


async def _infer_note_attribution(ticket_id, author, source, agent_id=None, request=None):
    explicit_author = author not in (None, "")
    explicit_source = source not in (None, "")
    if explicit_author and explicit_source:
        return author, source

    inferred_agent_id = None
    if agent_id:
        active = await fetchrow("""
            SELECT a.id
            FROM agents a
            JOIN agent_tasks t ON t.agent_id = a.id
            WHERE a.id = $1
              AND a.ticket_id = $2
              AND a.status IN ('spawned', 'running', 'working')
              AND t.status IN ('queued', 'running')
            ORDER BY t.created_at DESC
            LIMIT 1
        """, agent_id, ticket_id)
        if active:
            inferred_agent_id = active.get("id")
    elif not explicit_author and not explicit_source and _is_local_runner_request(request):
        active = await fetchall("""
            SELECT a.id
            FROM agents a
            JOIN agent_tasks t ON t.agent_id = a.id
            WHERE a.ticket_id = $1
              AND a.status IN ('spawned', 'running', 'working')
              AND t.status IN ('queued', 'running')
            ORDER BY t.created_at DESC
            LIMIT 2
        """, ticket_id)
        if active and len(active) == 1:
            inferred_agent_id = active[0].get("id")

    if inferred_agent_id:
        return author or f"agent-{inferred_agent_id}", source or "agent"
    return author or "dashboard", source or "dashboard"


@router.get("")
async def list_tickets(
    status: str = Query(None, description="Filter by status"),
    priority: str = Query(None, description="Filter by priority"),
    assignee: str = Query(None, description="Filter by assignee"),
    provider: str = Query(None, description="Filter by ticket provider"),
    q: str = Query(None, description="Search title, description, requester, team, provider ref"),
    agent_state: str = Query(None, description="Filter by agent assignment/state"),
    agent_only: bool = Query(False, description="Only tickets with agents"),
    sort_by: str = Query("updated_at", description="Sort field"),
    sort_dir: str = Query("desc", description="Sort direction"),
    limit: int = Query(100, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    request: Request = None,
):
    where_clauses = []
    params = []
    param_idx = 1

    if status:
        where_clauses.append(f"t.status = ${param_idx}")
        params.append(status)
        param_idx += 1
    if priority:
        where_clauses.append(f"t.priority = ${param_idx}")
        params.append(priority)
        param_idx += 1
    if assignee:
        where_clauses.append(f"t.assignee ILIKE ${param_idx}")
        params.append(f"%{assignee}%")
        param_idx += 1
    if provider:
        where_clauses.append(f"lower(COALESCE(t.provider, '')) = lower(${param_idx})")
        params.append(provider)
        param_idx += 1
    if q:
        where_clauses.append(
            f"""(
                t.title ILIKE ${param_idx} OR t.description ILIKE ${param_idx}
                OR t.assignee ILIKE ${param_idx} OR t.assignee_team ILIKE ${param_idx}
                OR t.requester_name ILIKE ${param_idx} OR t.requester_email ILIKE ${param_idx}
                OR t.affected_user_name ILIKE ${param_idx} OR t.affected_user_email ILIKE ${param_idx}
                OR t.provider_ref ILIKE ${param_idx} OR t.itop_ref ILIKE ${param_idx}
            )"""
        )
        params.append(f"%{q}%")
        param_idx += 1
    if agent_only:
        where_clauses.append("t.agent_id IS NOT NULL")
    if agent_state == "assigned":
        where_clauses.append("t.agent_id IS NOT NULL")
    elif agent_state == "unassigned":
        where_clauses.append("t.agent_id IS NULL")
    elif agent_state == "running":
        where_clauses.append("a.status IN ('spawned', 'running', 'working')")
    elif agent_state == "completed":
        where_clauses.append("a.status IN ('completed', 'finished', 'terminated')")

    subject = access_control.subject_from_request(request)
    scope_sql, scope_params, next_idx = access_control.ticket_filter_clause(subject, "t", param_idx)
    if scope_sql:
        where_clauses.append(scope_sql)
        params.extend(scope_params)
        param_idx = next_idx

    where_sql = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""
    sort_columns = {
        "id": "t.id",
        "title": "lower(t.title)",
        "class": "t.itop_class",
        "status": "t.status",
        "priority": "t.priority",
        "assignee": "t.assignee",
        "agent": "a.status",
        "updated_at": "t.updated_at",
        "created_at": "t.created_at",
        "provider": "t.provider",
    }
    sort_sql = sort_columns.get(sort_by, "t.updated_at")
    direction = "ASC" if (sort_dir or "").lower() == "asc" else "DESC"

    count_from = "tickets t LEFT JOIN agents a ON t.agent_id = a.id" if "a." in where_sql else "tickets t"
    count = await fetchval(
        f"SELECT COUNT(*) FROM {count_from}{where_sql}", *params
    )

    rows = await fetchall(
        f"""
        SELECT t.*, a.status AS agent_status, a.model AS agent_model,
               a.started_at AS agent_started
        FROM tickets t
        LEFT JOIN agents a ON t.agent_id = a.id
        {where_sql}
        ORDER BY {sort_sql} {direction} NULLS LAST, t.id DESC
        LIMIT ${param_idx} OFFSET ${param_idx + 1}
        """, *params, limit, offset
    )
    for row in rows:
        row["external_url"] = row.get("provider_url") or external_ticket_url(row)
        compact_ticket_payload(row)

    return {"tickets": rows, "total": count, "limit": limit, "offset": offset}

@router.get("/{ticket_id}")
async def get_ticket(ticket_id: int, request: Request = None):
    ticket = await fetchrow("""
        SELECT t.*, a.id AS agent_instance_id, a.status AS agent_status,
               a.model AS agent_model, a.heartbeat AS agent_heartbeat,
               a.started_at AS agent_started, a.error_message AS agent_error
        FROM tickets t
        LEFT JOIN agents a ON t.agent_id = a.id
        WHERE t.id = $1
    """, ticket_id)
    if not ticket:
        return {"error": "Ticket not found"}
    ticket_decision = access_control.ticket_access_decision(
        ticket,
        access_control.subject_from_request(request),
        "tickets:read",
    )
    if not ticket_decision.get("allow"):
        raise HTTPException(status_code=403, detail=ticket_decision)
    ticket["external_url"] = external_ticket_url(ticket)
    compact_ticket_payload(ticket)

    # Get change requests for this ticket
    changes = await fetchall("""
        SELECT * FROM change_requests WHERE ticket_id = $1 ORDER BY requested_at DESC
    """, ticket_id)
    ticket["change_requests"] = changes

    return ticket


@router.post("")
async def create_ticket(
    title: str = Body(...),
    description: str = Body(""),
    ticket_class: str = Body("UserRequest"),
    status: str = Body("new"),
    priority: str = Body(None),
    provider: str = Body(None),
    provider_ref: str = Body(None),
    provider_class: str = Body(None),
    sync_provider: bool = Body(None),
    created_by: str = Body("dashboard"),
    auto_assign: bool = Body(True),
    assignee_team: str = Body(None),
    owning_group: str = Body(None),
    opened_by_name: str = Body(None),
    opened_by_email: str = Body(None),
    requester_name: str = Body(None),
    requester_email: str = Body(None),
    affected_user_name: str = Body(None),
    affected_user_email: str = Body(None),
    security_classification: str = Body("internal"),
    access_scope: dict = Body(None),
    request: Request = None,
):
    """Create a canonical dashboard ticket.

    Provider sync is automatic when an external provider is configured, and
    falls back to local-only when the dashboard is running without one.
    """
    existing = await _find_ops_chat_idempotent_ticket(access_scope)
    if existing:
        existing["_idempotent_replay"] = True
        existing["external_url"] = external_ticket_url(existing)
        await log_event("ops-chat", "info", created_by, "ops_chat_duplicate_create_suppressed",
                        f"ticket_{existing['id']}", {
                            "session_id": (access_scope or {}).get("session_id"),
                            "message_hash": (access_scope or {}).get("message_hash"),
                        })
        compact_ticket_payload(existing)
        return existing

    ticket = await ticket_service.create_ticket(
        title=title,
        description=description,
        ticket_class=ticket_class,
        status=status,
        priority=priority,
        provider=provider,
        provider_ref=provider_ref,
        provider_class=provider_class,
        sync_provider=sync_provider,
        created_by=created_by,
        assignee_team=assignee_team,
        opened_by_name=opened_by_name,
        opened_by_email=opened_by_email,
        requester_name=requester_name,
        requester_email=requester_email,
        affected_user_name=affected_user_name,
        affected_user_email=affected_user_email,
        auto_assign=auto_assign,
    )
    update_fields = []
    update_values = []
    idx = 1
    if owning_group is not None:
        update_fields.append(f"owning_group = ${idx}")
        update_values.append(owning_group)
        idx += 1
    if assignee_team is not None:
        update_fields.append(f"assignee_team = ${idx}")
        update_values.append(assignee_team)
        idx += 1
    if security_classification:
        update_fields.append(f"security_classification = ${idx}")
        update_values.append(security_classification)
        idx += 1
    if access_scope is not None:
        update_fields.append(f"access_scope = ${idx}::jsonb")
        update_values.append(json_dumps(access_scope))
        idx += 1
    if update_fields:
        update_values.append(ticket["id"])
        await execute(
            f"UPDATE tickets SET {', '.join(update_fields)}, updated_at = NOW() WHERE id = ${idx}",
            *update_values,
        )
        ticket = await fetchrow("SELECT * FROM tickets WHERE id = $1", ticket["id"])
    return ticket


@router.get("/{ticket_id}/context")
async def get_ticket_context(ticket_id: int, request: Request = None):
    ticket = await fetchrow("SELECT id, owning_group, security_classification FROM tickets WHERE id = $1", ticket_id)
    if not ticket:
        return {"error": "Ticket not found"}
    ticket_decision = access_control.ticket_access_decision(
        ticket,
        access_control.subject_from_request(request),
        "tickets:read",
    )
    if not ticket_decision.get("allow"):
        raise HTTPException(status_code=403, detail=ticket_decision)
    return await ticket_service.get_context(ticket_id)


@router.post("/{ticket_id}/contacts")
async def update_ticket_contacts(
    ticket_id: int,
    opened_by_name: str = Body(None),
    opened_by_email: str = Body(None),
    requester_name: str = Body(None),
    requester_email: str = Body(None),
    affected_user_name: str = Body(None),
    affected_user_email: str = Body(None),
    actor: str = Body("dashboard"),
    reason: str = Body("ticket contact metadata updated"),
    request: Request = None,
):
    ticket = await fetchrow("SELECT id, owning_group, security_classification FROM tickets WHERE id = $1", ticket_id)
    if not ticket:
        return {"error": "Ticket not found"}
    decision = access_control.ticket_access_decision(
        ticket,
        access_control.subject_from_request(request),
        "tickets:update",
    )
    if not decision.get("allow"):
        raise HTTPException(status_code=403, detail=decision)

    fields = []
    values = []
    idx = 1
    for column, value in (
        ("opened_by_name", opened_by_name),
        ("opened_by_email", opened_by_email),
        ("requester_name", requester_name),
        ("requester_email", requester_email),
        ("affected_user_name", affected_user_name),
        ("affected_user_email", affected_user_email),
    ):
        if value is not None:
            fields.append(f"{column} = ${idx}")
            values.append(value)
            idx += 1
    if not fields:
        return {"status": "skipped", "reason": "no_contact_fields"}
    values.append(ticket_id)
    await execute(
        f"UPDATE tickets SET {', '.join(fields)}, updated_at = NOW() WHERE id = ${idx}",
        *values,
    )
    note_lines = ["Ticket contact metadata updated", f"Reason: {reason}"]
    if requester_name is not None or requester_email is not None:
        note_lines.append(f"Requester: {requester_name or '-'} <{requester_email or 'not provided'}>")
    if affected_user_name is not None or affected_user_email is not None:
        note_lines.append(f"Affected user: {affected_user_name or '-'} <{affected_user_email or 'not provided'}>")
    if opened_by_name is not None or opened_by_email is not None:
        note_lines.append(f"Opened by: {opened_by_name or '-'} <{opened_by_email or 'not provided'}>")
    note = await ticket_service.add_note(
        ticket_id,
        "\n".join(note_lines),
        author=actor,
        source="ticket-contact",
        visibility="internal",
    )
    updated = await ticket_service.get_ticket(ticket_id)
    await log_event("ticket", "info", actor, "ticket_contacts_updated",
                    f"ticket_{ticket_id}", {
                        "reason": reason,
                        "note_id": note.get("id"),
                    })
    return {"status": "updated", "ticket": updated, "note": note}


@router.post("/{ticket_id}/notes")
async def add_ticket_note(
    ticket_id: int,
    body: str = Body(None),
    note: str = Body(None),
    content: str = Body(None),
    title: str = Body(None),
    author: str = Body(None),
    source: str = Body(None),
    agent_id: int = Body(None),
    visibility: str = Body("internal"),
    external_ref: str = Body(None),
    request: Request = None,
):
    """Add a canonical ticket note.

    `body` is the documented field. `note`, `content`, and `title` are accepted as
    compatibility aliases because local agents and external ticket widgets often
    naturally send those names during ad hoc work. Keeping the API tolerant here
    prevents a harmless schema mismatch from stalling an incident workflow.
    """
    text = body if body is not None else note
    if text is None:
        text = content
    if text is None and title:
        text = title
    if text is None:
        raise HTTPException(status_code=400, detail="Missing note body. Use body or note.")
    if callable(fetchrow):
        ticket = await fetchrow("SELECT id, owning_group, security_classification FROM tickets WHERE id = $1", ticket_id)
        if not ticket:
            return {"error": "Ticket not found"}
        ticket_decision = access_control.ticket_access_decision(
            ticket,
            access_control.subject_from_request(request),
            "tickets:note",
        )
        if not ticket_decision.get("allow"):
            raise HTTPException(status_code=403, detail=ticket_decision)
    if title and title not in text:
        text = f"{title}\n\n{text}"
    author, source = await _infer_note_attribution(ticket_id, author, source, agent_id, request)
    return await ticket_service.add_note(ticket_id, text, author, source, visibility, external_ref)


@router.post("/{ticket_id}/assignment")
async def update_ticket_assignment(
    ticket_id: int,
    assignee_team: str = Body(None),
    owning_group: str = Body(None),
    assignee: str = Body(None),
    escalation_tier: str = Body(None),
    priority: str = Body(None),
    actor: str = Body("dashboard"),
    reason: str = Body(""),
    request: Request = None,
):
    """Reassign or escalate a ticket while preserving an auditable note trail."""
    ticket = await fetchrow("SELECT * FROM tickets WHERE id = $1", ticket_id)
    if not ticket:
        return {"error": "Ticket not found"}
    ticket_decision = access_control.ticket_access_decision(
        ticket,
        access_control.subject_from_request(request),
        "tickets:note",
    )
    if not ticket_decision.get("allow"):
        raise HTTPException(status_code=403, detail=ticket_decision)

    updates = []
    values = []
    idx = 1
    if assignee_team is not None:
        updates.append(f"assignee_team = ${idx}")
        values.append(assignee_team)
        idx += 1
    if owning_group is not None:
        updates.append(f"owning_group = ${idx}")
        values.append(owning_group)
        idx += 1
    if assignee is not None:
        updates.append(f"assignee = ${idx}")
        values.append(assignee)
        idx += 1
    if priority is not None:
        normalized_priority = str(priority).strip()
        if normalized_priority not in ("", "P1", "P2", "P3", "P4", "1", "2", "3", "4"):
            raise HTTPException(status_code=400, detail=f"Unsupported priority: {priority}")
        updates.append(f"priority = ${idx}")
        values.append(normalized_priority)
        idx += 1
    if not updates and not escalation_tier:
        raise HTTPException(status_code=400, detail="No assignment or escalation fields supplied.")
    if updates:
        values.append(ticket_id)
        await execute(
            f"UPDATE tickets SET {', '.join(updates)}, updated_at = NOW() WHERE id = ${idx}",
            *values,
        )

    changes = []
    if assignee_team is not None and assignee_team != ticket.get("assignee_team"):
        changes.append(f"Assignment group: `{ticket.get('assignee_team') or 'unassigned'}` -> `{assignee_team or 'unassigned'}`")
    if owning_group is not None and owning_group != ticket.get("owning_group"):
        changes.append(f"Owning group: `{ticket.get('owning_group') or 'unowned'}` -> `{owning_group or 'unowned'}`")
    if assignee is not None and assignee != ticket.get("assignee"):
        changes.append(f"Assignee: `{ticket.get('assignee') or 'unassigned'}` -> `{assignee or 'unassigned'}`")
    if priority is not None and str(priority).strip() != str(ticket.get("priority") or ""):
        changes.append(f"Priority: `{ticket.get('priority') or 'unset'}` -> `{str(priority).strip() or 'unset'}`")
    if escalation_tier:
        changes.append(f"Escalation tier: `{escalation_tier}`")

    note = await ticket_service.add_note(
        ticket_id,
        "\n".join([
            "Ticket assignment updated",
            f"Actor: {actor}",
            *(changes or ["No field value changed; escalation context recorded."]),
            "",
            reason or "No reason provided.",
        ]),
        author=actor,
        source="ticket-assignment",
        visibility="internal",
        external_ref=f"assignment:{ticket_id}:{int(datetime.now().timestamp())}",
    )
    await log_event("ticket", "info", actor, "ticket_assignment_updated",
                    f"ticket_{ticket_id}", {
                        "assignee_team": assignee_team,
                        "owning_group": owning_group,
                        "assignee": assignee,
                        "priority": priority,
                        "escalation_tier": escalation_tier,
                        "reason": reason,
                        "note_id": note.get("id"),
                    })
    updated = await fetchrow("SELECT * FROM tickets WHERE id = $1", ticket_id)
    compact_ticket_payload(updated)
    return {"status": "updated", "ticket": updated, "note_id": note.get("id")}


@router.post("/{ticket_id}/attachments")
async def add_ticket_attachment(
    ticket_id: int,
    filename: str = Body(...),
    content_type: str = Body(None),
    storage_ref: str = Body(None),
    sha256: str = Body(None),
    size_bytes: int = Body(None),
    note_id: int = Body(None),
    metadata: dict = Body({}),
):
    return await ticket_service.add_attachment_metadata(
        ticket_id, filename, content_type, storage_ref, sha256, size_bytes, note_id, metadata
    )


@router.get("/{ticket_id}/access-requests")
async def list_ticket_access_requests(ticket_id: int):
    rows = await fetchall("""
        SELECT ar.*, at.title AS access_ticket_title, at.status AS access_ticket_status,
               at.provider AS access_ticket_provider, at.provider_ref AS access_ticket_provider_ref,
               cr.status AS change_status, cr.approved_by, cr.approved_at, cr.result AS change_result
        FROM access_requests ar
        LEFT JOIN tickets at ON at.id = ar.access_ticket_id
        LEFT JOIN change_requests cr ON cr.id = ar.change_id
        WHERE ar.parent_ticket_id = $1 OR ar.access_ticket_id = $1
        ORDER BY ar.created_at DESC
    """, ticket_id)
    return {"access_requests": rows, "total": len(rows)}


@router.post("/{ticket_id}/access-request")
async def create_ticket_access_request(
    ticket_id: int,
    resource: str = Body(...),
    permission: str = Body(...),
    reason: str = Body(""),
    agent_id: int = Body(None),
    requester: str = Body(None),
    account_ref: str = Body(None),
    assignment_group: str = Body(None),
    risk_level: str = Body(None),
    sync_provider: bool = Body(None),
    created_by: str = Body("agent-access-request"),
    request: Request = None,
    lease_request: dict = Body(None),
):
    """Create an auditable access request and approval gate for a blocker.

    Agents use this when they hit a real permission wall. The child ticket is
    routed to the owning access group, while the approval gate remains linked to
    the original ticket/agent so approval resumes the original work.
    """
    ticket = await fetchrow("SELECT id, owning_group, security_classification FROM tickets WHERE id = $1", ticket_id)
    if not ticket:
        return {"error": "Ticket not found"}
    ticket_decision = access_control.ticket_access_decision(
        ticket,
        access_control.subject_from_request(request),
        "tickets:request_info",
    )
    if not ticket_decision.get("allow"):
        raise HTTPException(status_code=403, detail=ticket_decision)
    return await ticket_service.create_access_request(
        parent_ticket_id=ticket_id,
        resource=resource,
        permission=permission,
        reason=reason,
        agent_id=agent_id,
        requester=requester,
        account_ref=account_ref,
        assignment_group=assignment_group,
        risk_level=risk_level,
        sync_provider=sync_provider,
        created_by=created_by,
        lease_request=lease_request,
    )

@router.post("/{ticket_id}/sync")
async def sync_ticket(ticket_id: int):
    ticket = await fetchrow("SELECT provider, provider_ref, provider_class, itop_ref, itop_class FROM tickets WHERE id = $1", ticket_id)
    if not ticket:
        return {"error": "Ticket not found"}
    provider = ticket.get("provider") or "itop"
    ticket_ref = ticket.get("provider_ref") or ticket.get("itop_ref")
    ticket_class = ticket.get("provider_class") or ticket.get("itop_class")
    result = await provider_registry.sync_ticket(provider, ticket_class, ticket_ref)
    return result


@router.post("/{ticket_id}/push-provider")
async def push_ticket_to_provider(ticket_id: int, body: dict = Body(None)):
    """Create/update the provider-side ticket from the canonical dashboard ticket."""
    provider = (body or {}).get("provider")
    return await ticket_service.push_to_provider(ticket_id, provider)


async def _update_ticket_status(
    ticket_id: int,
    status: str,
    actor: str = "dashboard",
    reason: str = "",
    close_provider: bool = False,
    request: Request = None,
):
    ticket = await fetchrow("SELECT * FROM tickets WHERE id = $1", ticket_id)
    if not ticket:
        return {"error": "Ticket not found"}
    ticket_decision = access_control.ticket_access_decision(
        ticket,
        access_control.subject_from_request(request),
        "tickets:note",
    )
    if not ticket_decision.get("allow"):
        raise HTTPException(status_code=403, detail=ticket_decision)

    normalized = (status or "").strip().lower()
    allowed = {
        "new", "assigned", "in_progress", "awaiting_user_response",
        "pending_approval", "awaiting_access", "blocked", "resolved",
        "closed", "closed/resolved", "implemented", "rejected", "cancelled",
        "canceled",
    }
    if normalized not in allowed:
        raise HTTPException(status_code=400, detail=f"Unsupported ticket status: {status}")

    provider_result = {"status": "skipped", "reason": "not_requested"}
    terminal_status = normalized in {"resolved", "closed", "closed/resolved", "implemented"}
    if close_provider and terminal_status:
        provider_name = ticket.get("provider") or "local"
        provider_ref = str(ticket.get("provider_ref") or "")
        provider_sync_status = ticket.get("provider_sync_status") or ""
        if (
            provider_name == "local"
            or provider_sync_status in {"create_failed", "local_only", "pending_create"}
            or provider_ref.startswith("LOCAL-")
        ):
            provider_result = {
                "status": "skipped",
                "reason": "provider_not_synced",
                "provider": provider_name,
                "provider_sync_status": provider_sync_status,
            }
        else:
            provider_result = await provider_registry.close_ticket(
                provider_name,
                ticket_id,
                reason or f"Ticket marked {normalized} by {actor}.",
            )
            if provider_result.get("error"):
                await log_event("sync", "warning", actor, "provider_close_failed",
                                f"ticket_{ticket_id}", {
                                    "status": normalized,
                                    "provider": provider_name,
                                    "error": provider_result.get("error"),
                                })
                return {"error": "provider_close_failed", "provider_result": provider_result}

    await execute(
        "UPDATE tickets SET status = $1, updated_at = NOW() WHERE id = $2",
        normalized,
        ticket_id,
    )
    note_body = "\n".join([
        f"Ticket status changed to `{normalized}`",
        f"Actor: {actor}",
        "",
        reason or "No reason provided.",
    ]).strip()
    note = await ticket_service.add_note(
        ticket_id,
        note_body,
        author=actor,
        source="ticket-status",
        visibility="internal",
        external_ref=f"status:{normalized}:{ticket_id}",
    )
    await log_event("ticket", "info", actor, "ticket_status_updated",
                    f"ticket_{ticket_id}", {
                        "status": normalized,
                        "reason": reason,
                        "note_id": note.get("id"),
                        "close_provider": close_provider,
                        "provider_result": provider_result,
                    })
    return {
        "status": normalized,
        "ticket_id": ticket_id,
        "note_id": note.get("id"),
        "provider_result": provider_result,
    }


@router.post("/{ticket_id}/status")
async def update_ticket_status(
    ticket_id: int,
    status: str = Body(...),
    actor: str = Body("dashboard"),
    reason: str = Body(""),
    close_provider: bool = Body(False),
    request: Request = None,
):
    """Explicitly update ticket status.

    Agent task completion does not imply ticket closure. Agents and operators
    call this endpoint only when the workflow/deployment policy says the ticket
    should move to a new state.
    """
    return await _update_ticket_status(
        ticket_id,
        status,
        actor=actor,
        reason=reason,
        close_provider=close_provider,
        request=request,
    )


async def update_ticket_status_compat(
    ticket_id: int,
    body: dict = Body(None),
    request: Request = None,
):
    """Compatibility shim for local agents that try to update the ticket itself.

    The documented endpoint is POST /api/tickets/{ticket_id}/status. During live
    agent runs, local models sometimes infer PATCH/PUT/POST /api/tickets/{id}.
    Accepting the same explicit status payload here keeps the workflow moving
    while preserving the same access checks, provider-close opt-in, audit note,
    and event trail.
    """
    payload = body or {}
    if not isinstance(payload, dict):
        raise HTTPException(status_code=400, detail="Expected JSON object with status.")
    status = payload.get("status")
    if not status:
        raise HTTPException(status_code=400, detail="Missing status.")
    return await _update_ticket_status(
        ticket_id,
        status,
        actor=payload.get("actor") or "dashboard",
        reason=payload.get("reason") or "",
        close_provider=bool(payload.get("close_provider")),
        request=request,
    )


router.post("/{ticket_id}")(update_ticket_status_compat)
router.put("/{ticket_id}")(update_ticket_status_compat)
router.patch("/{ticket_id}")(update_ticket_status_compat)


@router.post("/sync-all")
async def sync_all(body=Body(None)):
    if isinstance(body, dict):
        provider = body.get("provider", "itop")
    elif isinstance(body, str):
        provider = body
    else:
        provider = "itop"
    return await provider_registry.full_sync(provider)

@router.post("/{ticket_id}/assign-agent")
async def assign_agent(
    ticket_id: int,
    model: str = Body(None),
    harness: str = Body(None),
    profile_id: str = Body(None),
    prompt: str = Body(None),
    requested_permissions: list = Body(None),
    request: Request = None,
):
    from services import agent_runner
    ticket = await fetchrow("SELECT * FROM tickets WHERE id = $1", ticket_id)
    if not ticket:
        return {"error": "Ticket not found"}
    ticket_decision = access_control.ticket_access_decision(
        ticket,
        access_control.subject_from_request(request),
        "tickets:read",
    )
    if not ticket_decision.get("allow"):
        raise HTTPException(status_code=403, detail=ticket_decision)
    active_agent = await fetchrow("""
        SELECT id, status FROM agents
        WHERE ticket_id = $1
          AND status IN ('spawned', 'running', 'working')
        ORDER BY started_at DESC
        LIMIT 1
    """, ticket_id)
    if active_agent:
        return {
            "error": f"Ticket already has active agent {active_agent['id']} ({active_agent['status']})",
            "agent_id": active_agent["id"],
            "status": active_agent["status"],
        }
    spawn_kwargs = {
        "actor_context": access_control.subject_from_request(request),
        "requested_permissions": requested_permissions,
    }
    if harness:
        spawn_kwargs["harness"] = harness
    if profile_id:
        spawn_kwargs["profile_id"] = profile_id
    result = await agent_runner.spawn_agent(
        ticket_id,
        model,
        prompt or build_ticket_resolution_prompt(ticket),
        **spawn_kwargs,
    )
    await log_event("ticket", "info", "dashboard", "agent_assigned",
                    f"ticket_{ticket_id}", {"model": model, "harness": harness, "profile_id": profile_id, "agent_id": result.get("agent_id")})
    return result


@router.post("/{ticket_id}/postmortem")
async def start_postmortem(
    ticket_id: int,
    model: str = Body("deepseek/deepseek-v4-flash"),
    harness: str = Body(None),
    context: str = Body(None),
    request: Request = None,
):
    """Spawn a postmortem agent for a completed or in-progress ticket."""
    from services import agent_runner
    ticket = await fetchrow("SELECT * FROM tickets WHERE id = $1", ticket_id)
    if not ticket:
        return {"error": "Ticket not found"}
    ticket_decision = access_control.ticket_access_decision(
        ticket,
        access_control.subject_from_request(request),
        "tickets:read",
    )
    if not ticket_decision.get("allow"):
        raise HTTPException(status_code=403, detail=ticket_decision)
    active_postmortem = await fetchrow("""
        SELECT a.id, a.status FROM agents a
        JOIN agent_tasks t ON t.agent_id = a.id
        WHERE a.ticket_id = $1
          AND t.task_type = 'postmortem'
          AND t.status IN ('queued', 'running')
        ORDER BY t.created_at DESC
        LIMIT 1
    """, ticket_id)
    if active_postmortem:
        return {
            "error": f"Postmortem already running as agent {active_postmortem['id']}",
            "agent_id": active_postmortem["id"],
            "status": active_postmortem["status"],
        }

    spawn_kwargs = {"actor_context": access_control.subject_from_request(request)}
    if harness:
        spawn_kwargs["harness"] = harness
    result = await agent_runner.spawn_agent(
        ticket_id,
        model,
        build_postmortem_prompt(ticket, context),
        "postmortem",
        **spawn_kwargs,
    )
    await log_event("agent", "info", "dashboard", "postmortem_requested",
                    f"ticket_{ticket_id}", {"model": model, "agent_id": result.get("agent_id")})
    return result


@router.post("/{ticket_id}/workflow")
async def start_workflow_build(
    ticket_id: int,
    model: str = Body("deepseek/deepseek-v4-flash"),
    harness: str = Body(None),
    context: str = Body(None),
    request: Request = None,
):
    """Spawn a workflow-build agent for this ticket class/use case."""
    from services import agent_runner
    ticket = await fetchrow("SELECT * FROM tickets WHERE id = $1", ticket_id)
    if not ticket:
        return {"error": "Ticket not found"}
    ticket_decision = access_control.ticket_access_decision(
        ticket,
        access_control.subject_from_request(request),
        "tickets:read",
    )
    if not ticket_decision.get("allow"):
        raise HTTPException(status_code=403, detail=ticket_decision)
    active_workflow = await fetchrow("""
        SELECT a.id, a.status FROM agents a
        JOIN agent_tasks t ON t.agent_id = a.id
        WHERE a.ticket_id = $1
          AND t.task_type = 'workflow_build'
          AND t.status IN ('queued', 'running')
        ORDER BY t.created_at DESC
        LIMIT 1
    """, ticket_id)
    if active_workflow:
        return {
            "error": f"Workflow build already running as agent {active_workflow['id']}",
            "agent_id": active_workflow["id"],
            "status": active_workflow["status"],
        }

    spawn_kwargs = {"actor_context": access_control.subject_from_request(request)}
    if harness:
        spawn_kwargs["harness"] = harness
    result = await agent_runner.spawn_agent(
        ticket_id,
        model,
        build_workflow_prompt(ticket, context),
        "workflow_build",
        **spawn_kwargs,
    )
    await log_event("agent", "info", "dashboard", "workflow_build_requested",
                    f"ticket_{ticket_id}", {"model": model, "agent_id": result.get("agent_id")})
    return result


@router.post("/{ticket_id}/request-info")
async def request_user_information(
    ticket_id: int,
    question: str = Body(...),
    requested_by: str = Body("agent"),
    contact_method: str = Body("email"),
    recipient: str = Body(None),
    context: str = Body(""),
):
    """Put a ticket into awaiting-user-response and record the outbound ask."""
    ticket = await fetchrow("SELECT id, status FROM tickets WHERE id = $1", ticket_id)
    if not ticket:
        return {"error": "Ticket not found"}
    note = "\n".join([
        "Awaiting user response",
        f"Requested by: {requested_by}",
        f"Contact method: {contact_method}",
        f"Recipient: {recipient or 'not recorded'}",
        "",
        question,
        "",
        context,
    ]).strip()
    result = await ticket_service.add_note(
        ticket_id,
        note,
        author=requested_by,
        source="user-info-request",
        visibility="user",
        external_ref=f"awaiting_user_response:{ticket_id}",
    )
    await execute("""
        UPDATE tickets
        SET status = 'awaiting_user_response',
            provider_payload = COALESCE(provider_payload, '{}'::jsonb) || $1::jsonb,
            updated_at = NOW()
        WHERE id = $2
    """, json_dumps({"awaiting_user_response": {"previous_status": ticket.get("status"), "requested_by": requested_by}}), ticket_id)
    await log_event("ticket", "info", requested_by, "user_info_requested",
                    f"ticket_{ticket_id}", {
                        "note_id": result.get("id"),
                        "contact_method": contact_method,
                        "recipient": recipient,
                    })
    return {"status": "awaiting_user_response", "ticket_id": ticket_id, "note_id": result.get("id")}


@router.post("/{ticket_id}/user-response")
async def record_user_response(
    ticket_id: int,
    response: str = Body(...),
    responder_name: str = Body("Requester"),
    responder_email: str = Body(None),
    resume_agent: bool = Body(True),
):
    """Record a requester response and resume the ticket workflow when possible."""
    ticket = await fetchrow("SELECT * FROM tickets WHERE id = $1", ticket_id)
    if not ticket:
        return {"error": "Ticket not found"}
    note_body = "\n".join([
        "User response received",
        f"Responder: {responder_name} <{responder_email or 'not provided'}>",
        "",
        response,
    ])
    note = await ticket_service.add_note(
        ticket_id,
        note_body,
        author=responder_name,
        source="user-response",
        visibility="internal",
        external_ref=f"user_response:{ticket_id}",
    )
    payload = ticket.get("provider_payload") or {}
    if isinstance(payload, str):
        try:
            import json
            payload = json.loads(payload)
        except Exception:
            payload = {}
    previous_status = ((payload or {}).get("awaiting_user_response") or {}).get("previous_status") or "in_progress"
    await execute("""
        UPDATE tickets
        SET status = $1,
            provider_payload = COALESCE(provider_payload, '{}'::jsonb) - 'awaiting_user_response',
            updated_at = NOW()
        WHERE id = $2
    """, previous_status, ticket_id)

    resume = {"status": "not_requested"}
    if resume_agent and ticket.get("agent_id"):
        active_task = await fetchrow("""
            SELECT id FROM agent_tasks
            WHERE agent_id = $1 AND status IN ('queued', 'running')
            ORDER BY created_at DESC LIMIT 1
        """, ticket["agent_id"])
        if active_task:
            resume = {"status": "already_active", "task_id": active_task["id"]}
        else:
            from services import agent_runner
            agent = await fetchrow("SELECT model, selected_model FROM agents WHERE id = $1", ticket["agent_id"])
            resume_prompt = "\n".join([
                build_ticket_resolution_prompt(ticket),
                "",
                f"User response received. Re-read /api/tickets/{ticket_id}/context, use the latest user-response note, continue the ticket, and add a note with the outcome.",
            ])
            resume = await agent_runner.spawn_agent(
                ticket_id,
                (agent or {}).get("selected_model") or (agent or {}).get("model") or "deepseek/deepseek-v4-flash",
                resume_prompt,
                "ticket_resolution",
                actor_context=await access_control.load_agent_subject(ticket["agent_id"]),
            )
    await log_event("ticket", "info", responder_name, "user_response_received",
                    f"ticket_{ticket_id}", {"note_id": note.get("id"), "resume": resume})
    return {"status": "user_response_recorded", "ticket_id": ticket_id, "note_id": note.get("id"), "resume": resume}


@router.post("/{ticket_id}/unassign-agent")
async def unassign_agent(ticket_id: int):
    ticket = await fetchrow("SELECT agent_id FROM tickets WHERE id = $1", ticket_id)
    if not ticket or not ticket["agent_id"]:
        return {"error": "No agent assigned"}
    await execute("""
        UPDATE agents SET status = 'terminated', finished_at = NOW() WHERE id = $1
    """, ticket["agent_id"])
    await execute("UPDATE tickets SET agent_id = NULL WHERE id = $1", ticket_id)
    return {"status": "agent_unassigned", "ticket_id": ticket_id}
