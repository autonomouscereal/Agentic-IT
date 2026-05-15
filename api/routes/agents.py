from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, Body
try:
    from fastapi import HTTPException
except ImportError:  # unit-test stubs do not expose HTTPException
    class HTTPException(Exception):
        def __init__(self, status_code=None, detail=None):
            self.status_code = status_code
            self.detail = detail
            super().__init__(detail)
try:
    from fastapi import Request
except ImportError:  # unit-test stubs do not expose Request
    class Request:
        pass
from datetime import datetime
from database import fetchall, fetchrow, execute, fetchval, json_dumps, json_loads
from services.event_logger import log_event
from services.task_prompts import build_ticket_resolution_prompt
try:
    from services import access_control
except ImportError:  # unit-test stubs load this route without service package contents
    class _AccessControlFallback:
        @staticmethod
        def subject_from_request(request):
            return {"identity": {"username": "unit-test"}, "roles": ["platform-admin"], "capabilities": ["*"], "scopes": [], "max_classification": "secret"}

        @staticmethod
        def ticket_access_decision(ticket, subject, required_permission="tickets:read"):
            return {"allow": True, "reason": "unit_test_fallback"}

        @staticmethod
        async def request_agent_vault_lease(*args, **kwargs):
            return {"allow": False, "error": "access_denied", "reason": "unit_test_fallback"}

    access_control = _AccessControlFallback()

router = APIRouter(prefix="/api/agents", tags=["agents"])

_connected_ws = []


@router.get("")
async def list_agents(
    status: str = Query(None, description="Filter by status"),
    ticket_id: int = Query(None, description="Filter by ticket"),
):
    where_clauses = []
    params = []
    param_idx = 1

    if status:
        where_clauses.append(f"a.status = ${param_idx}")
        params.append(status)
        param_idx += 1
    if ticket_id:
        where_clauses.append(f"a.ticket_id = ${param_idx}")
        params.append(ticket_id)
        param_idx += 1

    where_sql = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""

    rows = await fetchall(f"""
        SELECT a.*, t.title AS ticket_title, t.status AS ticket_status,
               t.itop_ref AS ticket_itop_ref,
               task.id AS current_task_id,
               task.status AS task_status,
               task.progress_pct AS task_progress_pct,
               task.task_type AS task_type,
               task.work_dir AS task_work_dir,
               task.error_message AS task_error_message,
               CASE WHEN a.status = 'stalled' THEN 0 ELSE GREATEST(0, EXTRACT(EPOCH FROM (NOW() - COALESCE(a.heartbeat, a.started_at, NOW())))) END AS idle_seconds,
               CASE WHEN a.status = 'stalled' THEN 0 ELSE GREATEST(0, EXTRACT(EPOCH FROM (COALESCE(a.finished_at, NOW()) - COALESCE(a.started_at, NOW())))) END AS running_seconds,
               CASE WHEN a.status = 'stalled' THEN 0 ELSE GREATEST(0, EXTRACT(EPOCH FROM (COALESCE(task.completed_at, NOW()) - COALESCE(task.started_at, task.created_at, NOW())))
                   - COALESCE(gates.gate_wait_seconds, 0)) END AS task_working_seconds,
               COALESCE(gates.gate_wait_seconds, 0) AS gate_wait_seconds
        FROM agents a
        LEFT JOIN tickets t ON a.ticket_id = t.id
        LEFT JOIN LATERAL (
            SELECT id, status, progress_pct, task_type, work_dir, error_message,
                   started_at, completed_at, created_at
            FROM agent_tasks
            WHERE agent_id = a.id
            ORDER BY created_at DESC
            LIMIT 1
        ) task ON true
        LEFT JOIN LATERAL (
            SELECT SUM(
                GREATEST(0, EXTRACT(EPOCH FROM (
                    COALESCE(cr.approved_at, NOW()) - COALESCE(cr.requested_at, NOW())
                )))
            ) AS gate_wait_seconds
            FROM change_requests cr
            WHERE cr.agent_id = a.id
              AND cr.status IN ('pending', 'approved', 'completed', 'rejected')
        ) gates ON true
        {where_sql}
        ORDER BY a.started_at DESC
    """, *params)

    return {"agents": rows, "total": len(rows)}


@router.get("/active")
async def active_agents():
    rows = await fetchall("""
        SELECT a.*, t.title AS ticket_title, t.itop_ref AS ticket_itop_ref,
               task.id AS current_task_id, task.status AS task_status,
               task.progress_pct AS task_progress_pct,
               GREATEST(0, EXTRACT(EPOCH FROM (NOW() - COALESCE(a.heartbeat, a.started_at, NOW())))) AS idle_seconds,
               GREATEST(0, EXTRACT(EPOCH FROM (NOW() - COALESCE(a.started_at, NOW())))) AS running_seconds
        FROM agents a
        LEFT JOIN tickets t ON a.ticket_id = t.id
        LEFT JOIN LATERAL (
            SELECT id, status, progress_pct
            FROM agent_tasks
            WHERE agent_id = a.id
            ORDER BY created_at DESC
            LIMIT 1
        ) task ON true
        WHERE a.status IN ('spawned', 'running', 'working')
        ORDER BY a.started_at DESC
    """)
    return {"agents": rows, "count": len(rows)}


@router.get("/stats")
async def agent_stats():
    total = await fetchval("SELECT COUNT(*) FROM agents") or 0
    active = await fetchval("SELECT COUNT(*) FROM agents WHERE status IN ('spawned', 'running', 'working')") or 0
    finished = await fetchval("SELECT COUNT(*) FROM agents WHERE status IN ('finished', 'resolved')") or 0
    failed = await fetchval("SELECT COUNT(*) FROM agents WHERE status IN ('failed', 'stopped', 'terminated')") or 0

    avg_duration = await fetchval("""
        SELECT EXTRACT(EPOCH FROM AVG(finished_at - started_at))
        FROM agents WHERE finished_at IS NOT NULL
    """)

    return {
        "total": total,
        "active": active,
        "finished": finished,
        "failed": failed,
        "avg_duration_seconds": round(avg_duration, 1) if avg_duration else None,
    }


@router.get("/models")
async def list_models():
    """Return available models for agent selection."""
    from services.agent_runner import get_available_models
    models = await get_available_models()
    return {"models": models}


@router.get("/runner-health")
async def runner_health():
    """Return Claude Code runner diagnostics."""
    from services.agent_runner import get_runner_health
    return await get_runner_health()


@router.get("/processes")
async def runner_processes():
    """Return current runner process diagnostics from inside the API container."""
    from services.agent_runner import get_process_snapshot
    return await get_process_snapshot()


@router.post("/heartbeat/{agent_id}")
async def agent_heartbeat(agent_id: int):
    """Legacy heartbeat endpoint - still accepts heartbeats but doesn't drive monitoring."""
    agent = await fetchrow("SELECT id, status FROM agents WHERE id = $1", agent_id)
    if not agent:
        return {"error": "Agent not found", "valid": False}
    if agent["status"] in ("stopped", "terminated", "failed"):
        return {"error": "Agent is stopped", "valid": False}

    await execute("UPDATE agents SET heartbeat = NOW() WHERE id = $1", agent_id)
    return {"status": "ok", "agent_id": agent_id, "valid": True}


@router.get("/ws")
async def get_ws_info():
    return {"connected": len(_connected_ws), "note": "Use WebSocket at /api/agents/ws"}


@router.post("/spawn")
async def spawn_agent(
    ticket_id: int = Body(...),
    model: str = Body("qwen/qwen3.6-27b"),
    prompt: str = Body(None),
    task_type: str = Body("ticket_resolution"),
    requested_permissions: list = Body(None),
    request: Request = None,
):
    """Spawn a Claude Code agent to work on a ticket."""
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

    # Default prompt if not provided
    if not prompt:
        prompt = f"Investigate and resolve this ticket: {ticket['title']}. Class: {ticket['itop_class']}. Description: {ticket['description'] or 'N/A'}"

    result = await agent_runner.spawn_agent(
        ticket_id,
        model,
        prompt,
        task_type,
        actor_context=access_control.subject_from_request(request),
        requested_permissions=requested_permissions,
    )
    await log_event("agent", "info", "dashboard", "agent_spawned",
                    f"ticket_{ticket_id}", {"model": model, "task_type": task_type})
    return result


@router.post("/create-from-prompt")
async def create_from_prompt(
    prompt: str = Body(...),
    model: str = Body("qwen/qwen3.6-27b"),
    request: Request = None,
):
    """Create a ticket from a prompt and spawn an agent to work it."""
    from services import ticket_service
    ticket = await ticket_service.create_ticket(
        title=prompt[:500],
        description=prompt[:2000],
        ticket_class="UserRequest",
        status="in_progress",
        created_by="dashboard",
    )
    ticket_id = ticket["id"]

    agent_prompt = build_ticket_resolution_prompt(ticket, prompt)

    # Spawn agent
    from services import agent_runner
    result = await agent_runner.spawn_agent(
        ticket_id,
        model,
        agent_prompt,
        "ad_hoc",
        actor_context=access_control.subject_from_request(request),
    )
    await log_event("agent", "info", "dashboard", "create_from_prompt",
                    f"ticket_{ticket_id}", {"prompt_preview": prompt[:200]})
    return result


@router.get("/tasks")
async def list_tasks(
    status: str = Query(None),
    agent_id: int = Query(None),
    ticket_id: int = Query(None),
):
    """List agent tasks with optional filters."""
    where_clauses = []
    params = []
    idx = 1

    if status:
        where_clauses.append(f"status = ${idx}")
        params.append(status)
        idx += 1
    if agent_id:
        where_clauses.append(f"agent_id = ${idx}")
        params.append(agent_id)
        idx += 1
    if ticket_id:
        where_clauses.append(f"ticket_id = ${idx}")
        params.append(ticket_id)
        idx += 1

    wh = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""
    rows = await fetchall(f"SELECT * FROM agent_tasks{wh} ORDER BY created_at DESC", *params)
    return {"tasks": rows, "total": len(rows)}


@router.get("/audits")
async def list_agent_audits(
    agent_id: int = Query(None),
    ticket_id: int = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    where = []
    params = []
    idx = 1
    if agent_id:
        where.append(f"r.agent_id = ${idx}")
        params.append(agent_id)
        idx += 1
    if ticket_id:
        where.append(f"r.ticket_id = ${idx}")
        params.append(ticket_id)
        idx += 1
    wh = " WHERE " + " AND ".join(where) if where else ""
    params.append(limit)
    rows = await fetchall(f"""
        SELECT r.*, t.title AS ticket_title, a.status AS agent_status
        FROM agent_audit_reviews r
        LEFT JOIN tickets t ON t.id = r.ticket_id
        LEFT JOIN agents a ON a.id = r.agent_id
        {wh}
        ORDER BY r.created_at DESC
        LIMIT ${idx}
    """, *params)
    for row in rows:
        if isinstance(row.get("details"), str):
            row["details"] = json_loads(row["details"]) or {}
    return {"audits": rows, "total": len(rows)}


@router.post("/audits/run")
async def run_agent_audit_once():
    from services import agent_auditor
    result = await agent_auditor.audit_once()
    return {"status": "ok", **result}


@router.get("/tasks/{task_id}/logs")
async def get_task_logs(task_id: int, lines: int = Query(200, ge=1, le=2000)):
    """Return output.log tail for a task."""
    task = await fetchrow("SELECT id, work_dir, output FROM agent_tasks WHERE id = $1", task_id)
    if not task:
        return {"error": "Task not found"}

    log_path = None
    content = ""
    if task.get("work_dir"):
        import os
        log_path = os.path.join(task["work_dir"], "output.log")
        try:
            with open(log_path, "r", encoding="utf-8", errors="replace") as f:
                all_lines = f.readlines()
            content = "".join(all_lines[-lines:])
        except FileNotFoundError:
            content = task.get("output") or ""
    else:
        content = task.get("output") or ""

    return {"task_id": task_id, "log_path": log_path, "content": content}


@router.get("/{agent_id}/steering")
async def list_agent_steering(agent_id: int):
    rows = await fetchall("""
        SELECT *
        FROM agent_steering_events
        WHERE agent_id = $1
        ORDER BY created_at DESC, id DESC
        LIMIT 50
    """, agent_id)
    return {"agent_id": agent_id, "events": rows, "total": len(rows)}


@router.post("/{agent_id}/steering/{event_id}/ack")
async def acknowledge_agent_steering(agent_id: int, event_id: int, body: dict = Body(None)):
    from services import agent_steering
    actor = (body or {}).get("actor") or f"agent_{agent_id}"
    return await agent_steering.acknowledge(agent_id, event_id, actor)


@router.get("/{agent_id}/vault")
async def get_agent_vault_manifest(agent_id: int):
    """Return scoped credential lease references for an agent, never secrets."""
    agent = await fetchrow("SELECT id FROM agents WHERE id = $1", agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    rows = await fetchall("""
        SELECT id, agent_id, system, resource_type, resource_id, action,
               credential_ref, lease_status, granted_by, expires_at, created_at
        FROM agent_vault_leases
        WHERE agent_id = $1
        ORDER BY system, resource_type, resource_id, action
    """, agent_id)
    return {
        "agent_id": agent_id,
        "leases": rows,
        "secret_values_returned": False,
        "note": "Each row is a scoped vault reference only. Resolve secrets through the configured credential vault if the lease is active.",
    }


@router.post("/{agent_id}/vault/lease")
async def request_agent_vault_lease(
    agent_id: int,
    system: str = Body(...),
    resource_type: str = Body("resource"),
    resource_id: str = Body("*"),
    action: str = Body("read"),
):
    """Evaluate a per-agent credential lease request for one system/resource/action."""
    agent = await fetchrow("SELECT id FROM agents WHERE id = $1", agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    result = await access_control.request_agent_vault_lease(
        agent_id,
        system,
        resource_type,
        resource_id,
        action,
    )
    if not result.get("allow"):
        raise HTTPException(status_code=403, detail=result)
    return result


@router.get("/{agent_id}")
async def get_agent(agent_id: int):
    agent = await fetchrow("""
        SELECT a.*, t.title AS ticket_title, t.status AS ticket_status,
               t.itop_ref AS ticket_itop_ref, t.description AS ticket_description
        FROM agents a
        LEFT JOIN tickets t ON a.ticket_id = t.id
        WHERE a.id = $1
    """, agent_id)
    if not agent:
        return {"error": "Agent not found"}

    # Get current task info
    task = await fetchrow("""
        SELECT * FROM agent_tasks WHERE agent_id = $1 ORDER BY created_at DESC LIMIT 1
    """, agent_id)
    if task:
        agent["current_task"] = task

    changes = await fetchall("""
        SELECT * FROM change_requests WHERE agent_id = $1 ORDER BY requested_at DESC
    """, agent_id)
    agent["change_requests"] = changes

    audit = await fetchall("""
        SELECT * FROM audit_log WHERE details->>'agent_id' = $1
        ORDER BY created_at DESC LIMIT 50
    """, str(agent_id))
    agent["audit"] = audit

    return agent


@router.get("/{agent_id}/task")
async def get_agent_task(agent_id: int):
    """Get the latest task for an agent."""
    task = await fetchrow("""
        SELECT * FROM agent_tasks WHERE agent_id = $1 ORDER BY created_at DESC LIMIT 1
    """, agent_id)
    if not task:
        return {"error": "No tasks for this agent"}
    return task


@router.get("/{agent_id}/logs")
async def get_agent_logs(agent_id: int, lines: int = Query(200, ge=1, le=2000)):
    """Return latest task logs for an agent."""
    task = await fetchrow(
        "SELECT id FROM agent_tasks WHERE agent_id = $1 ORDER BY created_at DESC LIMIT 1",
        agent_id,
    )
    if not task:
        return {"error": "No tasks for this agent"}
    return await get_task_logs(task["id"], lines)


@router.post("/{agent_id}/stop")
async def stop_agent(agent_id: int, body: dict = Body(None)):
    from services import agent_runner
    reason = "manual_stop"
    if isinstance(body, dict) and body.get("reason"):
        reason = str(body["reason"])
    agent = await fetchrow("SELECT id, ticket_id FROM agents WHERE id = $1", agent_id)

    # Try to stop the running task first
    task_result = await agent_runner.stop_agent_task(agent_id, reason=reason)

    # Also update agent status if no task was found
    if "error" in task_result:
        if agent:
            await execute("""
                UPDATE agents SET status = 'stopped', finished_at = NOW(),
                                 error_message = $1 WHERE id = $2
            """, reason, agent_id)

    ticket_reassignment = None
    if agent and agent.get("ticket_id"):
        current_ticket = await fetchrow("SELECT id, agent_id FROM tickets WHERE id = $1", agent["ticket_id"])
        if current_ticket and current_ticket.get("agent_id") == agent_id:
            replacement = await fetchrow("""
                SELECT id FROM agents
                WHERE ticket_id = $1
                  AND id <> $2
                  AND status IN ('spawned', 'running', 'working')
                ORDER BY started_at DESC NULLS LAST, id DESC
                LIMIT 1
            """, agent["ticket_id"], agent_id)
            replacement_id = replacement["id"] if replacement else None
            await execute("""
                UPDATE tickets
                SET agent_id = $1,
                    status = CASE WHEN $1::integer IS NULL THEN status ELSE 'in_progress' END,
                    updated_at = NOW()
                WHERE id = $2
            """, replacement_id, agent["ticket_id"])
            ticket_reassignment = {
                "ticket_id": agent["ticket_id"],
                "old_agent_id": agent_id,
                "replacement_agent_id": replacement_id,
            }
            await log_event("agent", "info", "dashboard", "ticket_agent_reassigned_after_stop",
                            f"ticket_{agent['ticket_id']}", ticket_reassignment)

    await log_event("agent", "info", "dashboard", "agent_stopped",
                    f"agent_{agent_id}", {"reason": reason, "ticket_reassignment": ticket_reassignment})
    return {"status": "stopped", "agent_id": agent_id}


@router.post("/{agent_id}/wake")
async def wake_agent(agent_id: int):
    """Wake a stalled agent by spawning a replacement for its latest task."""
    agent = await fetchrow("SELECT * FROM agents WHERE id = $1", agent_id)
    if not agent:
        return {"error": "Agent not found"}

    active_task = await fetchrow("""
        SELECT id, status, pid FROM agent_tasks
        WHERE agent_id = $1 AND status IN ('queued', 'running')
        ORDER BY created_at DESC LIMIT 1
    """, agent_id)
    if active_task:
        await execute("UPDATE agents SET heartbeat = NOW() WHERE id = $1", agent_id)
        await log_event("agent", "info", "dashboard", "agent_wake_noop_active",
                        f"agent_{agent_id}", {"task_id": active_task["id"], "status": active_task["status"]})
        return {
            "status": "already_active",
            "agent_id": agent_id,
            "task_id": active_task["id"],
            "message": "Agent already has an active task; heartbeat refreshed.",
        }

    if agent["status"] in ("stopped", "terminated"):
        return {"error": f"Cannot wake agent in status: {agent['status']}. Use restart for a replacement run."}

    latest_task = await fetchrow("""
        SELECT prompt, task_type FROM agent_tasks
        WHERE agent_id = $1
        ORDER BY created_at DESC LIMIT 1
    """, agent_id)
    if not latest_task:
        return {"error": "No previous task prompt found for this agent"}

    from services import agent_runner
    model = agent.get("selected_model") or agent.get("model") or "qwen/qwen3.6-27b"
    result = await agent_runner.spawn_agent(
        agent["ticket_id"],
        model,
        latest_task["prompt"],
        latest_task.get("task_type") or "ticket_resolution",
        actor_context={
            "identity": {"username": f"agent_{agent_id}"},
            "roles": ["agent-operator"],
            "capabilities": ["agents:spawn", "tickets:read", "changes:request"],
            "scopes": [],
            "max_classification": "internal",
        },
    )

    await log_event("agent", "info", "dashboard", "agent_wake_spawned",
                    f"agent_{agent_id}", {"replacement_agent_id": result.get("agent_id"), "model": model})
    return {"status": "replacement_spawned", "source_agent_id": agent_id, **result}


@router.post("/{agent_id}/restart")
async def restart_agent(agent_id: int):
    """Terminate current agent and spawn a new one for the same ticket."""
    agent = await fetchrow("SELECT ticket_id, selected_model, model FROM agents WHERE id = $1", agent_id)
    if not agent:
        return {"error": "Agent not found"}

    model = agent.get("selected_model") or agent.get("model", "qwen/qwen3.6-27b")
    ticket_id = agent["ticket_id"]

    from services import agent_runner
    stop_result = await agent_runner.stop_agent_task(agent_id)

    latest_task = await fetchrow("""
        SELECT prompt, task_type FROM agent_tasks
        WHERE agent_id = $1
        ORDER BY created_at DESC LIMIT 1
    """, agent_id)

    # Terminate old agent if it did not have an active task to stop.
    await execute("""
        UPDATE agents SET status = 'terminated', finished_at = NOW(),
                         error_message = 'restarted via dashboard' WHERE id = $1
    """, agent_id)

    if latest_task and latest_task.get("prompt"):
        prompt = latest_task["prompt"]
        task_type = latest_task.get("task_type") or "ticket_resolution"
    else:
        from services.task_prompts import build_ticket_resolution_prompt
        ticket = await fetchrow("SELECT * FROM tickets WHERE id = $1", ticket_id)
        if not ticket:
            return {"error": "Ticket not found for restart"}
        prompt = build_ticket_resolution_prompt(ticket)
        task_type = "ticket_resolution"

    # Spawn new agent
    result = await agent_runner.spawn_agent(
        ticket_id,
        model,
        prompt,
        task_type,
        actor_context={
            "identity": {"username": f"agent_{agent_id}"},
            "roles": ["agent-operator"],
            "capabilities": ["agents:spawn", "tickets:read", "changes:request"],
            "scopes": [],
            "max_classification": "internal",
        },
    )
    await log_event("agent", "info", "dashboard", "agent_restarted",
                    f"agent_{agent_id}", {"new_task_id": result.get("task_id"), "stop_result": stop_result})
    return result


@router.post("/{agent_id}/update")
async def update_agent_status(
    agent_id: int,
    status: str = Body(...),
    error_message: str = Body(None),
):
    agent = await fetchrow("SELECT id FROM agents WHERE id = $1", agent_id)
    if not agent:
        return {"error": "Agent not found"}

    if error_message:
        await execute("""
            UPDATE agents SET status = $1, heartbeat = NOW(),
                             error_message = $2, updated_at = NOW()
            WHERE id = $3
        """, status, error_message, agent_id)
    else:
        await execute("""
            UPDATE agents SET status = $1, heartbeat = NOW(),
                             updated_at = NOW() WHERE id = $2
        """, status, agent_id)

    await execute("""
        INSERT INTO audit_log (actor, action, target, details)
        VALUES ($1, $2, $3, $4)
    """, "orchestrator", "agent_updated", f"agent_{agent_id}", json_dumps({
        "agent_id": agent_id, "status": status, "error_message": error_message
    }))

    await log_event("agent", "info", "orchestrator", "agent_updated",
                    f"agent_{agent_id}", {"status": status})

    return {"status": "updated", "agent_id": agent_id, "new_status": status}


@router.websocket("/ws")
async def agent_ws(websocket: WebSocket):
    await websocket.accept()
    _connected_ws.append(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text("pong")
    except WebSocketDisconnect:
        _connected_ws.remove(websocket)


async def broadcast_agent_update(message: dict):
    import json
    text = json.dumps(message, default=str)
    disconnected = []
    for ws in _connected_ws:
        try:
            await ws.send_text(text)
        except:
            disconnected.append(ws)
    for ws in disconnected:
        if ws in _connected_ws:
            _connected_ws.remove(ws)
