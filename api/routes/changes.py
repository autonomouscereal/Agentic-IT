from fastapi import APIRouter, Query, Body
from datetime import datetime, timedelta
from database import fetchall, fetchrow, execute, fetchval, json_dumps
from services.event_logger import log_event

router = APIRouter(prefix="/api/changes", tags=["changes"])

@router.get("")
async def list_changes(
    status: str = Query(None, description="Filter by status"),
    agent_id: int = Query(None, description="Filter by agent"),
    ticket_id: int = Query(None, description="Filter by ticket"),
):
    where_clauses = []
    params = []
    param_idx = 1

    if status:
        where_clauses.append(f"status = ${param_idx}")
        params.append(status)
        param_idx += 1
    if agent_id:
        where_clauses.append(f"agent_id = ${param_idx}")
        params.append(agent_id)
        param_idx += 1
    if ticket_id:
        where_clauses.append(f"ticket_id = ${param_idx}")
        params.append(ticket_id)
        param_idx += 1

    where_sql = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""

    rows = await fetchall(f"""
        SELECT cr.*, a.model AS agent_model, t.title AS ticket_title
        FROM change_requests cr
        LEFT JOIN agents a ON cr.agent_id = a.id
        LEFT JOIN tickets t ON cr.ticket_id = t.id
        {where_sql}
        ORDER BY cr.requested_at DESC
    """, *params)

    pending = await fetchval(
        "SELECT COUNT(*) FROM change_requests WHERE status = 'pending'"
    ) or 0

    return {"changes": rows, "total": len(rows), "pending": pending}

@router.post("/request")
async def request_change(
    agent_id: int = Body(None),
    ticket_id: int = Body(...),
    action: str = Body(...),
    target: str = Body(...),
    reason: str = Body(""),
    command: str = Body(None),
    risk_level: str = Body("unknown"),
    approval_policy: dict = Body({}),
):
    change_id = await fetchval("""
        INSERT INTO change_requests (agent_id, ticket_id, action, target,
                                     reason, command, risk_level, approval_policy,
                                     status, requested_by,
                                     requested_at, expires_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'pending', $9,
                NOW(), NOW() + INTERVAL '300 seconds')
        RETURNING id
    """, agent_id, ticket_id, action, target, reason, command, risk_level,
        json_dumps(approval_policy or {}), f"agent_{agent_id}" if agent_id else "dashboard")

    actor = f"agent_{agent_id}" if agent_id else "dashboard"
    await execute("""
        INSERT INTO audit_log (actor, action, target, details)
        VALUES ($1, $2, $3, $4)
    """, actor, "change_requested", f"change_{change_id}", json_dumps({
        "change_id": change_id, "action": action, "target": target,
        "agent_id": agent_id, "ticket_id": ticket_id, "risk_level": risk_level
    }))
    await log_event("change", "info", actor, "change_requested",
                    f"change_{change_id}", {"ticket_id": ticket_id, "risk_level": risk_level})

    return {"change_id": change_id, "status": "pending"}

@router.get("/pending")
async def pending_changes():
    rows = await fetchall("""
        SELECT cr.*, a.model AS agent_model, t.title AS ticket_title,
               EXTRACT(EPOCH FROM (NOW() - cr.requested_at)) AS waiting_seconds
        FROM change_requests cr
        LEFT JOIN agents a ON cr.agent_id = a.id
        LEFT JOIN tickets t ON cr.ticket_id = t.id
        WHERE cr.status = 'pending'
        AND (cr.expires_at IS NULL OR cr.expires_at > NOW())
        ORDER BY cr.requested_at ASC
    """)
    return {"changes": rows, "count": len(rows)}

@router.get("/stats")
async def change_stats():
    pending = await fetchval("SELECT COUNT(*) FROM change_requests WHERE status = 'pending'") or 0
    approved = await fetchval("SELECT COUNT(*) FROM change_requests WHERE status = 'approved'") or 0
    rejected = await fetchval("SELECT COUNT(*) FROM change_requests WHERE status = 'rejected'") or 0
    completed = await fetchval("SELECT COUNT(*) FROM change_requests WHERE status = 'completed'") or 0

    return {"pending": pending, "approved": approved, "rejected": rejected, "completed": completed}

@router.get("/{change_id}")
async def get_change(change_id: int):
    change = await fetchrow("""
        SELECT cr.*, a.model AS agent_model, a.status AS agent_status,
               t.title AS ticket_title, t.itop_ref AS ticket_itop_ref
        FROM change_requests cr
        LEFT JOIN agents a ON cr.agent_id = a.id
        LEFT JOIN tickets t ON cr.ticket_id = t.id
        WHERE cr.id = $1
    """, change_id)
    if not change:
        return {"error": "Change request not found"}
    return change


@router.get("/{change_id}/status")
async def change_status(change_id: int):
    change = await fetchrow("""
        SELECT id, status, approved_by, approved_at, rejected_reason, result,
               action, target, risk_level, requested_at, expires_at
        FROM change_requests WHERE id = $1
    """, change_id)
    if not change:
        return {"error": "Change request not found"}
    return change

@router.post("/{change_id}/approve")
async def approve_change(change_id: int, body: dict = Body({})):
    approved_by = (body or {}).get("approved_by", "dashboard")
    change = await fetchrow("SELECT * FROM change_requests WHERE id = $1", change_id)
    if not change:
        return {"error": "Change request not found"}
    if change["status"] != "pending":
        return {"error": f"Change request is {change['status']}, not pending"}

    await execute("""
        UPDATE change_requests SET status = 'approved', approved_by = $1,
                                  approved_at = NOW() WHERE id = $2
    """, approved_by, change_id)

    await execute("""
        INSERT INTO audit_log (actor, action, target, details)
        VALUES ($1, $2, $3, $4)
    """, approved_by, "change_approved", f"change_{change_id}", json_dumps({
        "change_id": change_id, "action": change["action"], "target": change["target"]
    }))
    await log_event("change", "info", approved_by, "change_approved",
                    f"change_{change_id}", {"ticket_id": change["ticket_id"], "agent_id": change["agent_id"]})

    return {"status": "approved", "change_id": change_id}

@router.post("/{change_id}/reject")
async def reject_change(
    change_id: int,
    body: dict = Body({}),
):
    rejected_by = (body or {}).get("rejected_by", "dashboard")
    reason = (body or {}).get("reason", "Rejected")
    change = await fetchrow("SELECT * FROM change_requests WHERE id = $1", change_id)
    if not change:
        return {"error": "Change request not found"}
    if change["status"] != "pending":
        return {"error": f"Change request is {change['status']}, not pending"}

    await execute("""
        UPDATE change_requests SET status = 'rejected', approved_by = $1,
                                  approved_at = NOW(), rejected_reason = $2
        WHERE id = $3
    """, rejected_by, reason, change_id)

    await execute("""
        INSERT INTO audit_log (actor, action, target, details)
        VALUES ($1, $2, $3, $4)
    """, rejected_by, "change_rejected", f"change_{change_id}", json_dumps({
        "change_id": change_id, "reason": reason
    }))
    await log_event("change", "warning", rejected_by, "change_rejected",
                    f"change_{change_id}", {"ticket_id": change["ticket_id"], "agent_id": change["agent_id"]})

    return {"status": "rejected", "change_id": change_id}

@router.post("/{change_id}/complete")
async def complete_change(change_id: int, body: dict = Body({})):
    result = (body or {}).get("result", "")
    change = await fetchrow("SELECT * FROM change_requests WHERE id = $1", change_id)
    if not change:
        return {"error": "Change request not found"}

    await execute("""
        UPDATE change_requests SET status = 'completed', result = $1 WHERE id = $2
    """, result, change_id)
    await log_event("change", "info", "dashboard", "change_completed",
                    f"change_{change_id}", {"result": result[:500] if result else ""})

    return {"status": "completed", "change_id": change_id}
