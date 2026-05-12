from fastapi import APIRouter, Query, Body, HTTPException
from datetime import datetime
from database import fetchall, fetchrow, execute, fetchval, json_dumps
from services import provider_registry, ticket_service
from services.ticket_service import compact_ticket_payload
from services.ticket_links import external_ticket_url
from services.task_prompts import (
    build_ticket_resolution_prompt,
    build_postmortem_prompt,
    build_workflow_prompt,
)
from services.event_logger import log_event

router = APIRouter(prefix="/api/tickets", tags=["tickets"])

@router.get("")
async def list_tickets(
    status: str = Query(None, description="Filter by status"),
    priority: str = Query(None, description="Filter by priority"),
    assignee: str = Query(None, description="Filter by assignee"),
    agent_only: bool = Query(False, description="Only tickets with agents"),
    sort_by: str = Query("updated_at", description="Sort field"),
    sort_dir: str = Query("desc", description="Sort direction"),
    limit: int = Query(100, ge=1, le=1000),
    offset: int = Query(0, ge=0),
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
    if agent_only:
        where_clauses.append("t.agent_id IS NOT NULL")

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

    count = await fetchval(
        f"SELECT COUNT(*) FROM tickets t{where_sql}", *params
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
async def get_ticket(ticket_id: int):
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
):
    """Create a canonical dashboard ticket.

    Provider sync is automatic when an external provider is configured, and
    falls back to local-only when the dashboard is running without one.
    """
    return await ticket_service.create_ticket(
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
        auto_assign=auto_assign,
    )


@router.get("/{ticket_id}/context")
async def get_ticket_context(ticket_id: int):
    return await ticket_service.get_context(ticket_id)


@router.post("/{ticket_id}/notes")
async def add_ticket_note(
    ticket_id: int,
    body: str = Body(None),
    note: str = Body(None),
    title: str = Body(None),
    author: str = Body("dashboard"),
    source: str = Body("dashboard"),
    visibility: str = Body("internal"),
    external_ref: str = Body(None),
):
    """Add a canonical ticket note.

    `body` is the documented field. `note` and `title` are accepted as
    compatibility aliases because local agents and external ticket widgets often
    naturally send those names during ad hoc work. Keeping the API tolerant here
    prevents a harmless schema mismatch from stalling an incident workflow.
    """
    text = body if body is not None else note
    if text is None and title:
        text = title
    if text is None:
        raise HTTPException(status_code=400, detail="Missing note body. Use body or note.")
    if title and title not in text:
        text = f"{title}\n\n{text}"
    return await ticket_service.add_note(ticket_id, text, author, source, visibility, external_ref)


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
    model: str = Body("qwen/qwen3.6-27b"),
    prompt: str = Body(None),
):
    from services import agent_runner
    ticket = await fetchrow("SELECT * FROM tickets WHERE id = $1", ticket_id)
    if not ticket:
        return {"error": "Ticket not found"}
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
    result = await agent_runner.spawn_agent(
        ticket_id,
        model,
        prompt or build_ticket_resolution_prompt(ticket),
    )
    await log_event("ticket", "info", "dashboard", "agent_assigned",
                    f"ticket_{ticket_id}", {"model": model, "agent_id": result.get("agent_id")})
    return result


@router.post("/{ticket_id}/postmortem")
async def start_postmortem(
    ticket_id: int,
    model: str = Body("qwen/qwen3.6-27b"),
    context: str = Body(None),
):
    """Spawn a postmortem agent for a completed or in-progress ticket."""
    from services import agent_runner
    ticket = await fetchrow("SELECT * FROM tickets WHERE id = $1", ticket_id)
    if not ticket:
        return {"error": "Ticket not found"}
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

    result = await agent_runner.spawn_agent(
        ticket_id,
        model,
        build_postmortem_prompt(ticket, context),
        "postmortem",
    )
    await log_event("agent", "info", "dashboard", "postmortem_requested",
                    f"ticket_{ticket_id}", {"model": model, "agent_id": result.get("agent_id")})
    return result


@router.post("/{ticket_id}/workflow")
async def start_workflow_build(
    ticket_id: int,
    model: str = Body("qwen/qwen3.6-27b"),
    context: str = Body(None),
):
    """Spawn a workflow-build agent for this ticket class/use case."""
    from services import agent_runner
    ticket = await fetchrow("SELECT * FROM tickets WHERE id = $1", ticket_id)
    if not ticket:
        return {"error": "Ticket not found"}
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

    result = await agent_runner.spawn_agent(
        ticket_id,
        model,
        build_workflow_prompt(ticket, context),
        "workflow_build",
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
                (agent or {}).get("selected_model") or (agent or {}).get("model") or "qwen/qwen3.6-27b",
                resume_prompt,
                "ticket_resolution",
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
