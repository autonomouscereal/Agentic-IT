from fastapi import APIRouter, Query, Body, HTTPException
from datetime import datetime
from database import fetchall, fetchrow, execute, fetchval, json_dumps
from services import provider_registry, ticket_service
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
    provider: str = Body("local"),
    provider_ref: str = Body(None),
    provider_class: str = Body(None),
    sync_provider: bool = Body(False),
    created_by: str = Body("dashboard"),
):
    """Create a canonical dashboard ticket.

    Provider sync is explicit so demo/local tasks can stay local-only while
    production adapters can create corresponding iTop/ServiceNow tickets.
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

    result = await agent_runner.spawn_agent(
        ticket_id,
        model,
        build_workflow_prompt(ticket, context),
        "workflow_build",
    )
    await log_event("agent", "info", "dashboard", "workflow_build_requested",
                    f"ticket_{ticket_id}", {"model": model, "agent_id": result.get("agent_id")})
    return result

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
