from fastapi import APIRouter, Body, Query
from database import fetchall, fetchrow, execute, fetchval, json_dumps
from services.event_logger import log_event

router = APIRouter(prefix="/api/postmortems", tags=["postmortems"])


@router.get("")
async def list_postmortems(
    ticket_id: int = Query(None),
    status: str = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    where = []
    params = []
    idx = 1
    if ticket_id:
        where.append(f"pm.ticket_id = ${idx}")
        params.append(ticket_id)
        idx += 1
    if status:
        where.append(f"pm.status = ${idx}")
        params.append(status)
        idx += 1
    where_sql = "WHERE " + " AND ".join(where) if where else ""
    rows = await fetchall(f"""
        SELECT pm.*, t.title AS ticket_title, a.model AS agent_model
        FROM postmortems pm
        LEFT JOIN tickets t ON pm.ticket_id = t.id
        LEFT JOIN agents a ON pm.agent_id = a.id
        {where_sql}
        ORDER BY pm.created_at DESC
        LIMIT ${idx}
    """, *params, limit)
    return {"postmortems": rows, "total": len(rows)}


@router.get("/{postmortem_id}")
async def get_postmortem(postmortem_id: int):
    row = await fetchrow("SELECT * FROM postmortems WHERE id = $1", postmortem_id)
    if not row:
        return {"error": "Postmortem not found"}
    return row


@router.post("")
async def create_postmortem(
    ticket_id: int = Body(None),
    agent_id: int = Body(None),
    task_id: int = Body(None),
    status: str = Body("draft"),
    summary: str = Body(""),
    went_well: str = Body(""),
    improvements: str = Body(""),
    workflow_proposal: str = Body(""),
    skill_proposals: list = Body([]),
    test_cases: list = Body([]),
    guardrails: list = Body([]),
    documentation: str = Body(""),
    created_by: str = Body("dashboard"),
):
    postmortem_id = await fetchval("""
        INSERT INTO postmortems (
            ticket_id, agent_id, task_id, status, summary, went_well,
            improvements, workflow_proposal, skill_proposals, test_cases,
            guardrails, documentation, created_by
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
        RETURNING id
    """, ticket_id, agent_id, task_id, status, summary, went_well,
        improvements, workflow_proposal, json_dumps(skill_proposals or []),
        json_dumps(test_cases or []), json_dumps(guardrails or []),
        documentation, created_by)
    await log_event("postmortem", "info", created_by, "postmortem_created",
                    f"postmortem_{postmortem_id}", {"ticket_id": ticket_id, "status": status})
    return {"id": postmortem_id, "status": "created"}


@router.put("/{postmortem_id}")
async def update_postmortem(
    postmortem_id: int,
    status: str = Body(None),
    summary: str = Body(None),
    went_well: str = Body(None),
    improvements: str = Body(None),
    workflow_proposal: str = Body(None),
    skill_proposals: list = Body(None),
    test_cases: list = Body(None),
    guardrails: list = Body(None),
    documentation: str = Body(None),
    review_notes: str = Body(None),
):
    allowed = {
        "status": status,
        "summary": summary,
        "went_well": went_well,
        "improvements": improvements,
        "workflow_proposal": workflow_proposal,
        "skill_proposals": json_dumps(skill_proposals) if skill_proposals is not None else None,
        "test_cases": json_dumps(test_cases) if test_cases is not None else None,
        "guardrails": json_dumps(guardrails) if guardrails is not None else None,
        "documentation": documentation,
        "review_notes": review_notes,
    }
    fields = []
    params = []
    idx = 1
    for name, value in allowed.items():
        if value is not None:
            fields.append(f"{name} = ${idx}")
            params.append(value)
            idx += 1
    if not fields:
        return {"error": "No fields to update"}
    fields.append("updated_at = NOW()")
    params.append(postmortem_id)
    await execute(f"UPDATE postmortems SET {', '.join(fields)} WHERE id = ${idx}", *params)
    await log_event("postmortem", "info", "dashboard", "postmortem_updated",
                    f"postmortem_{postmortem_id}", {"fields": [f.split(' = ')[0] for f in fields[:-1]]})
    return {"status": "updated", "id": postmortem_id}


@router.post("/{postmortem_id}/review")
async def review_postmortem(
    postmortem_id: int,
    reviewed_by: str = Body("dashboard"),
    review_notes: str = Body(""),
    approved: bool = Body(False),
):
    status = "approved" if approved else "needs_revision"
    await execute("""
        UPDATE postmortems
        SET status = $1, reviewed_by = $2, reviewed_at = NOW(),
            review_notes = $3, updated_at = NOW()
        WHERE id = $4
    """, status, reviewed_by, review_notes, postmortem_id)
    await log_event("postmortem", "info", reviewed_by, "postmortem_reviewed",
                    f"postmortem_{postmortem_id}", {"status": status})
    return {"status": status, "id": postmortem_id}
