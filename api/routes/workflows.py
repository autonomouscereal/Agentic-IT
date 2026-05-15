from fastapi import APIRouter, Body, Query
from database import fetchall, fetchrow, execute, fetchval, json_dumps
from services.event_logger import log_event
from services.workflow_keys import workflow_key_for_fields, policy_with_key, load_policy

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


REVIEW_GATED_STATUSES = {"draft", "ready_for_review", "tested", "needs_revision", "superseded"}


def _review_gated_status(status, fallback="draft"):
    """Keep create/update paths from silently activating reusable automation."""
    value = (status or fallback or "draft").strip()
    if value in ("active", "approved"):
        return "ready_for_review"
    return value if value in REVIEW_GATED_STATUSES else fallback


def _policy(value):
    return load_policy(value)


def _workflow_key(name, description, ticket_class, trigger_type, blueprint, approval_policy):
    policy = _policy(approval_policy)
    explicit_key = policy.get("workflow_key")
    return workflow_key_for_fields(
        ticket_class=ticket_class,
        trigger_type=trigger_type,
        name=name,
        description=description,
        blueprint=blueprint,
        approval_policy=policy,
        explicit_key=explicit_key,
    )


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
        where.append(f"w.status = ${idx}")
        params.append(status)
        idx += 1
    if ticket_class:
        where.append(f"(w.ticket_class = ${idx} OR w.ticket_class IS NULL)")
        params.append(ticket_class)
        idx += 1
    where_sql = "WHERE " + " AND ".join(where) if where else ""
    rows = await fetchall(
        f"""
        SELECT w.*,
               COALESCE(run_stats.run_count, 0) AS run_count,
               COALESCE(run_stats.completed_count, 0) AS completed_run_count,
               COALESCE(run_stats.failed_count, 0) AS failed_run_count,
               run_stats.latest_run_at,
               CASE
                 WHEN w.status IN ('active', 'approved') AND w.reviewed_at IS NOT NULL THEN 'active_approved'
                 WHEN w.status IN ('active', 'approved') THEN 'active_missing_review'
                 WHEN w.status = 'tested' THEN 'tested_needs_approval'
                 WHEN w.status = 'ready_for_review' THEN 'ready_for_review'
                 ELSE w.status
               END AS review_state
        FROM agent_workflows w
        LEFT JOIN LATERAL (
            SELECT COUNT(*) AS run_count,
                   COUNT(*) FILTER (WHERE status IN ('completed', 'passed')) AS completed_count,
                   COUNT(*) FILTER (WHERE status IN ('failed', 'error')) AS failed_count,
                   MAX(created_at) AS latest_run_at
            FROM workflow_runs wr
            WHERE wr.workflow_id = w.id
        ) run_stats ON true
        {where_sql}
        ORDER BY w.updated_at DESC LIMIT ${idx}
        """,
        *params, limit,
    )
    return {"workflows": rows, "total": len(rows)}


@router.get("/{workflow_id}")
async def get_workflow(workflow_id: int):
    row = await fetchrow("SELECT * FROM agent_workflows WHERE id = $1", workflow_id)
    if not row:
        return {"error": "Workflow not found"}
    runs = await fetchall(
        """
        SELECT wr.*, t.title AS ticket_title, t.status AS ticket_status,
               t.provider, t.provider_ref, t.itop_ref, t.itop_class
        FROM workflow_runs wr
        LEFT JOIN tickets t ON t.id = wr.ticket_id
        WHERE wr.workflow_id = $1
        ORDER BY wr.created_at DESC LIMIT 25
        """,
        workflow_id,
    )
    row["runs"] = runs
    row["review_state"] = (
        "active_approved" if row.get("status") in ("active", "approved") and row.get("reviewed_at")
        else "active_missing_review" if row.get("status") in ("active", "approved")
        else "tested_needs_approval" if row.get("status") == "tested"
        else row.get("status")
    )
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
    workflow_key = _workflow_key(name, description, ticket_class, trigger_type, blueprint, approval_policy)
    approval_policy = policy_with_key(_policy(approval_policy), workflow_key)
    status = _review_gated_status(status)
    existing = await fetchrow("""
        SELECT id, name
        FROM agent_workflows
        WHERE workflow_key = $1 AND status <> 'superseded'
        ORDER BY
            CASE WHEN status IN ('active', 'approved') THEN 0
                 WHEN status = 'tested' THEN 1
                 WHEN status = 'ready_for_review' THEN 2
                 ELSE 3 END,
            updated_at DESC
        LIMIT 1
    """, workflow_key)
    action = "updated" if existing else "created"
    if existing:
        rename_on_reuse = bool(approval_policy.get("rename_on_reuse") or approval_policy.get("update_name"))
        workflow_id = await fetchval("""
            UPDATE agent_workflows
            SET name = CASE WHEN $2 THEN $3 ELSE name END,
                description = $4,
                ticket_class = $5,
                trigger_type = $6,
                status = $7,
                version = version + 1,
                blueprint = $8,
                test_plan = $9,
                test_results = $10,
                approval_policy = $11,
                skill_ids = $12,
                workflow_key = $13,
                updated_at = NOW()
            WHERE id = $1
            RETURNING id
        """,
            existing["id"], rename_on_reuse, name, description, ticket_class,
            trigger_type, status, blueprint, test_plan, test_results,
            json_dumps(approval_policy), json_dumps(skill_ids or []), workflow_key,
        )
    else:
        workflow_id = await fetchval("""
            INSERT INTO agent_workflows (
                name, description, ticket_class, trigger_type, status, blueprint,
                test_plan, test_results, approval_policy, skill_ids, created_by, workflow_key
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
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
                workflow_key = EXCLUDED.workflow_key,
                updated_at = NOW()
            RETURNING id
        """, name, description, ticket_class, trigger_type, status, blueprint,
            test_plan, test_results, json_dumps(approval_policy),
            json_dumps(skill_ids or []), created_by, workflow_key)
    await log_event("workflow", "info", created_by, "workflow_saved",
                    f"workflow_{workflow_id}", {"name": name, "status": status, "workflow_key": workflow_key, "action": action})
    return {"id": workflow_id, "status": "saved", "action": action, "workflow_key": workflow_key}


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
    existing = await fetchrow("SELECT * FROM agent_workflows WHERE id = $1", workflow_id)
    if not existing:
        return {"error": "Workflow not found"}
    merged_policy = _policy(approval_policy) if approval_policy is not None else _policy(existing.get("approval_policy"))
    effective = {
        "name": name if name is not None else existing.get("name"),
        "description": description if description is not None else existing.get("description"),
        "ticket_class": ticket_class if ticket_class is not None else existing.get("ticket_class"),
        "trigger_type": trigger_type if trigger_type is not None else existing.get("trigger_type"),
        "blueprint": blueprint if blueprint is not None else existing.get("blueprint"),
    }
    workflow_key = _workflow_key(
        effective["name"],
        effective["description"],
        effective["ticket_class"],
        effective["trigger_type"],
        effective["blueprint"],
        merged_policy,
    )
    merged_policy = policy_with_key(merged_policy, workflow_key)
    safe_status = _review_gated_status(status, existing.get("status")) if status is not None else None
    if (
        status is None
        and workflow_key != existing.get("workflow_key")
        and existing.get("status") in ("active", "approved")
    ):
        safe_status = "ready_for_review"
    values = {
        "name": name,
        "description": description,
        "ticket_class": ticket_class,
        "trigger_type": trigger_type,
        "status": safe_status,
        "blueprint": blueprint,
        "test_plan": test_plan,
        "test_results": test_results,
        "approval_policy": json_dumps(merged_policy),
        "skill_ids": json_dumps(skill_ids) if skill_ids is not None else None,
        "workflow_key": workflow_key,
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
    fields.append("version = version + 1")
    fields.append("updated_at = NOW()")
    params.append(workflow_id)
    await execute(f"UPDATE agent_workflows SET {', '.join(fields)} WHERE id = ${idx}", *params)
    await log_event("workflow", "info", "dashboard", "workflow_updated",
                    f"workflow_{workflow_id}", {"fields": [f.split(' = ')[0] for f in fields[:-1]]})
    return {"status": "updated", "id": workflow_id}


async def _supersede_active_siblings(workflow_id, workflow_key, reviewed_by):
    if not workflow_key:
        return []
    rows = await fetchall("""
        SELECT id
        FROM agent_workflows
        WHERE workflow_key = $1
          AND id <> $2
          AND status IN ('active', 'approved')
        ORDER BY updated_at DESC
    """, workflow_key, workflow_id)
    sibling_ids = [row["id"] for row in rows]
    if not sibling_ids:
        return []
    await execute("""
        UPDATE agent_workflows
        SET status = 'superseded',
            test_results = COALESCE(test_results, '') ||
                CASE WHEN COALESCE(test_results, '') = '' THEN '' ELSE E'\n' END ||
                'Superseded when workflow ' || $2::text || ' was reviewed active for the same workflow_key.',
            updated_at = NOW()
        WHERE id = ANY($1::int[])
    """, sibling_ids, str(workflow_id))
    await log_event(
        "workflow",
        "info",
        reviewed_by,
        "workflow_siblings_superseded",
        f"workflow_{workflow_id}",
        {"workflow_key": workflow_key, "superseded_workflow_ids": sibling_ids},
    )
    return sibling_ids


@router.post("/{workflow_id}/review")
async def review_workflow(
    workflow_id: int,
    reviewed_by: str = Body("dashboard"),
    approved: bool = Body(False),
    review_notes: str = Body(""),
):
    status = "active" if approved else "needs_revision"
    workflow = await fetchrow("SELECT id, workflow_key FROM agent_workflows WHERE id = $1", workflow_id)
    if not workflow:
        return {"error": "Workflow not found"}
    superseded_ids = []
    if approved:
        superseded_ids = await _supersede_active_siblings(
            workflow_id,
            workflow.get("workflow_key"),
            reviewed_by,
        )
    await execute("""
        UPDATE agent_workflows
        SET status = $1, reviewed_by = $2, reviewed_at = NOW(),
            test_results = CASE WHEN $3 <> '' THEN COALESCE(test_results, '') || E'\nReview: ' || $3 ELSE test_results END,
            updated_at = NOW()
        WHERE id = $4
    """, status, reviewed_by, review_notes, workflow_id)
    await log_event("workflow", "info", reviewed_by, "workflow_reviewed",
                    f"workflow_{workflow_id}", {"status": status, "superseded_workflow_ids": superseded_ids})
    return {"status": status, "id": workflow_id, "superseded_workflow_ids": superseded_ids}


@router.post("/{workflow_id}/rerun")
async def rerun_workflow(
    workflow_id: int,
    ticket_id: int = Body(...),
    model: str = Body("qwen/qwen3.6-27b"),
    created_by: str = Body("dashboard"),
):
    workflow = await fetchrow("SELECT * FROM agent_workflows WHERE id = $1", workflow_id)
    ticket = await fetchrow("SELECT * FROM tickets WHERE id = $1", ticket_id)
    if not workflow:
        return {"error": "Workflow not found"}
    if not ticket:
        return {"error": "Ticket not found"}
    if workflow.get("status") not in ("active", "approved", "tested"):
        return {"error": "Workflow must be tested or active before rerun"}
    run_id = await fetchval("""
        INSERT INTO workflow_runs (workflow_id, ticket_id, status, started_at)
        VALUES ($1, $2, 'running', NOW())
        RETURNING id
    """, workflow_id, ticket_id)
    prompt = (
        f"Rerun workflow `{workflow['name']}` version {workflow.get('version') or 1} on ticket {ticket_id}.\n\n"
        f"Workflow blueprint:\n{workflow.get('blueprint') or ''}\n\n"
        "Use the dashboard ticket context first. Create approval gates before risky actions. "
        f"Record workflow run {run_id} completion with POST /api/workflows/runs/{run_id}/complete."
    )
    from services import agent_runner
    result = await agent_runner.spawn_agent(ticket_id, model, prompt, "workflow_rerun")
    await execute(
        "UPDATE workflow_runs SET agent_id = $1, task_id = $2 WHERE id = $3",
        result.get("agent_id"), result.get("task_id"), run_id,
    )
    await log_event("workflow", "info", created_by, "workflow_rerun_started",
                    f"workflow_run_{run_id}", {"workflow_id": workflow_id, "ticket_id": ticket_id, **result})
    return {"status": "started", "run_id": run_id, **result}


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
