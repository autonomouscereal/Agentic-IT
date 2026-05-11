from fastapi import APIRouter, Body, Query
from database import fetchall, fetchrow, execute, fetchval, json_dumps
from services.event_logger import log_event

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


@router.get("")
async def list_workflows(
    status: str = Query(None),
    ticket_class: str = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    where = []
    params = []
    idx = 1
    if status:
        where.append(f"status = ${idx}")
        params.append(status)
        idx += 1
    if ticket_class:
        where.append(f"(ticket_class = ${idx} OR ticket_class IS NULL)")
        params.append(ticket_class)
        idx += 1
    where_sql = "WHERE " + " AND ".join(where) if where else ""
    rows = await fetchall(
        f"SELECT * FROM agent_workflows {where_sql} ORDER BY updated_at DESC LIMIT ${idx}",
        *params, limit,
    )
    return {"workflows": rows, "total": len(rows)}


@router.get("/{workflow_id}")
async def get_workflow(workflow_id: int):
    row = await fetchrow("SELECT * FROM agent_workflows WHERE id = $1", workflow_id)
    if not row:
        return {"error": "Workflow not found"}
    runs = await fetchall(
        "SELECT * FROM workflow_runs WHERE workflow_id = $1 ORDER BY created_at DESC LIMIT 25",
        workflow_id,
    )
    row["runs"] = runs
    return row


@router.post("")
async def create_workflow(
    name: str = Body(...),
    blueprint: str = Body(...),
    description: str = Body(""),
    ticket_class: str = Body(None),
    trigger_type: str = Body("manual"),
    status: str = Body("draft"),
    test_plan: str = Body(""),
    test_results: str = Body(""),
    approval_policy: dict = Body({}),
    skill_ids: list = Body([]),
    created_by: str = Body("dashboard"),
):
    workflow_id = await fetchval("""
        INSERT INTO agent_workflows (
            name, description, ticket_class, trigger_type, status, blueprint,
            test_plan, test_results, approval_policy, skill_ids, created_by
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        ON CONFLICT (name) DO UPDATE SET
            description = EXCLUDED.description,
            ticket_class = EXCLUDED.ticket_class,
            trigger_type = EXCLUDED.trigger_type,
            status = EXCLUDED.status,
            version = agent_workflows.version + 1,
            blueprint = EXCLUDED.blueprint,
            test_plan = EXCLUDED.test_plan,
            test_results = EXCLUDED.test_results,
            approval_policy = EXCLUDED.approval_policy,
            skill_ids = EXCLUDED.skill_ids,
            updated_at = NOW()
        RETURNING id
    """, name, description, ticket_class, trigger_type, status, blueprint,
        test_plan, test_results, json_dumps(approval_policy or {}),
        json_dumps(skill_ids or []), created_by)
    await log_event("workflow", "info", created_by, "workflow_saved",
                    f"workflow_{workflow_id}", {"name": name, "status": status})
    return {"id": workflow_id, "status": "saved"}


@router.put("/{workflow_id}")
async def update_workflow(
    workflow_id: int,
    name: str = Body(None),
    description: str = Body(None),
    ticket_class: str = Body(None),
    trigger_type: str = Body(None),
    status: str = Body(None),
    blueprint: str = Body(None),
    test_plan: str = Body(None),
    test_results: str = Body(None),
    approval_policy: dict = Body(None),
    skill_ids: list = Body(None),
):
    values = {
        "name": name,
        "description": description,
        "ticket_class": ticket_class,
        "trigger_type": trigger_type,
        "status": status,
        "blueprint": blueprint,
        "test_plan": test_plan,
        "test_results": test_results,
        "approval_policy": json_dumps(approval_policy) if approval_policy is not None else None,
        "skill_ids": json_dumps(skill_ids) if skill_ids is not None else None,
    }
    fields = []
    params = []
    idx = 1
    for key, value in values.items():
        if value is not None:
            fields.append(f"{key} = ${idx}")
            params.append(value)
            idx += 1
    if not fields:
        return {"error": "No fields to update"}
    fields.append("updated_at = NOW()")
    params.append(workflow_id)
    await execute(f"UPDATE agent_workflows SET {', '.join(fields)} WHERE id = ${idx}", *params)
    await log_event("workflow", "info", "dashboard", "workflow_updated",
                    f"workflow_{workflow_id}", {"fields": [f.split(' = ')[0] for f in fields[:-1]]})
    return {"status": "updated", "id": workflow_id}


@router.post("/{workflow_id}/review")
async def review_workflow(
    workflow_id: int,
    reviewed_by: str = Body("dashboard"),
    approved: bool = Body(False),
    review_notes: str = Body(""),
):
    status = "approved" if approved else "needs_revision"
    await execute("""
        UPDATE agent_workflows
        SET status = $1, reviewed_by = $2, reviewed_at = NOW(),
            test_results = CASE WHEN $3 <> '' THEN COALESCE(test_results, '') || E'\nReview: ' || $3 ELSE test_results END,
            updated_at = NOW()
        WHERE id = $4
    """, status, reviewed_by, review_notes, workflow_id)
    await log_event("workflow", "info", reviewed_by, "workflow_reviewed",
                    f"workflow_{workflow_id}", {"status": status})
    return {"status": status, "id": workflow_id}


@router.post("/{workflow_id}/runs")
async def create_workflow_run(
    workflow_id: int,
    ticket_id: int = Body(None),
    agent_id: int = Body(None),
    task_id: int = Body(None),
    status: str = Body("queued"),
):
    run_id = await fetchval("""
        INSERT INTO workflow_runs (workflow_id, ticket_id, agent_id, task_id, status, started_at)
        VALUES ($1, $2, $3, $4, $5::varchar, CASE WHEN $5::varchar = 'running' THEN NOW() ELSE NULL END)
        RETURNING id
    """, workflow_id, ticket_id, agent_id, task_id, status)
    await log_event("workflow", "info", "dashboard", "workflow_run_created",
                    f"workflow_run_{run_id}", {"workflow_id": workflow_id, "ticket_id": ticket_id})
    return {"id": run_id, "status": "created"}


@router.post("/runs/{run_id}/complete")
async def complete_workflow_run(run_id: int, result: str = Body(""), status: str = Body("completed")):
    await execute("""
        UPDATE workflow_runs
        SET status = $1, result = $2, completed_at = NOW()
        WHERE id = $3
    """, status, result, run_id)
    await log_event("workflow", "info", "dashboard", "workflow_run_completed",
                    f"workflow_run_{run_id}", {"status": status})
    return {"status": status, "id": run_id}
