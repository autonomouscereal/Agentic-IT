try:
    from fastapi import APIRouter, Query, Body, Request
except ImportError:  # unit-test stubs may not expose Request
    from fastapi import APIRouter, Query, Body
    class Request:
        pass
from datetime import datetime, timedelta
import json
from database import fetchall, fetchrow, execute, fetchval, json_dumps
from services.event_logger import log_event
try:
    from services.lease_inference import infer_lease_request
except ImportError:  # unit-test stubs may load this route without service package contents
    def infer_lease_request(*args, **kwargs):
        return None
try:
    from services import access_control
except ImportError:  # unit-test stubs load this route without service package contents
    class _AccessControlFallback:
        @staticmethod
        async def load_agent_subject(agent_id):
            return {"identity": {"username": f"agent_{agent_id}"}, "roles": ["agent-operator"], "capabilities": ["tickets:read"], "scopes": [], "max_classification": "internal"}

    access_control = _AccessControlFallback()

router = APIRouter(prefix="/api/changes", tags=["changes"])


def _is_auto_approver(actor):
    value = (actor or "").lower()
    explicit_markers = (
        "auto-approver",
        "auto_approver",
        "auto approver",
        "test-auto",
        "test_auto",
        "regression-auto",
        "regression_auto",
        "smoke-auto",
        "smoke_auto",
    )
    return any(marker in value for marker in explicit_markers)


def _completion_result_from_body(body):
    body = body or {}
    for key in ("result", "evidence", "output"):
        value = body.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _completion_actor_from_body(body):
    body = body or {}
    actor = body.get("completed_by") or body.get("actor")
    if actor:
        return str(actor)
    agent_id = body.get("agent_id")
    if agent_id:
        return f"agent_{agent_id}"
    return "dashboard"


def _approval_actor_from_request(request, body, *body_keys, default="dashboard"):
    """Prefer authenticated browser/proxy identity over spoofable UI body fields.

    Service-token automation may still pass a named approver in the body so
    scripted demo gates remain human-readable in audit trails.
    """
    body = body or {}
    try:
        decision = getattr(getattr(request, "state", None), "access_decision", None) or {}
        identity = decision.get("identity") or {}
    except Exception:
        identity = {}
    username = (identity.get("username") or "").strip()
    auth_mode = (identity.get("auth_mode") or "").strip()
    if username and username.lower() not in {"anonymous", "unknown"} and auth_mode != "service-token":
        return username
    for key in body_keys:
        value = body.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    if username:
        return username
    return default


def _loads_json(value, default=None):
    if value is None:
        return default if default is not None else {}
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default if default is not None else {}
    return default if default is not None else {}


def _access_policy(change):
    policy = _loads_json((change or {}).get("approval_policy"), {})
    if not isinstance(policy, dict) or not policy.get("access_request"):
        return None
    return policy


async def _add_gate_note(ticket_id, change_id, title, body, actor="approval-gate", source="approval-gate"):
    if not ticket_id:
        return None
    note_id = await fetchval("""
        INSERT INTO ticket_notes (ticket_id, source, author, body, visibility)
        VALUES ($1, $2, $3, $4, 'internal')
        RETURNING id
    """, ticket_id, source, actor, f"{title}\n\n{body}".strip())
    await execute("UPDATE tickets SET updated_at = NOW() WHERE id = $1", ticket_id)
    await log_event("ticket", "info", actor, "approval_gate_note_added",
                    f"ticket_{ticket_id}", {
                        "note_id": note_id,
                        "change_id": change_id,
                        "title": title,
                    })
    return note_id


async def _record_resume_handoff(change, source_agent, result, approved_by):
    ticket_id = change.get("ticket_id")
    source_agent_id = change.get("agent_id")
    replacement_agent_id = result.get("agent_id")
    replacement_task_id = result.get("task_id")
    if not ticket_id or not source_agent_id or not replacement_agent_id:
        return {"status": "skipped", "reason": "missing handoff identifiers"}

    previous_reason = ""
    if source_agent:
        previous_reason = (source_agent.get("error_message") or "").strip()
    title = f"Agent handoff after approval: {source_agent_id} -> {replacement_agent_id}"
    body = "\n".join([
        f"Source agent `{source_agent_id}` had stopped at an approval/access gate and is now historical evidence for that wait state.",
        f"Continuation agent `{replacement_agent_id}` / task `{replacement_task_id}` was spawned after change `{change.get('id')}` was approved by `{approved_by}`.",
        "The original ticket objective continues under the continuation agent; the source agent should not be expected to keep running indefinitely.",
        f"Prior wait reason: {previous_reason or 'not recorded'}.",
    ])
    note_id = await _add_gate_note(
        ticket_id,
        change.get("id"),
        title,
        body,
        approved_by,
        "agent-lifecycle",
    )
    handoff_message = (
        f"{previous_reason}; " if previous_reason else ""
    ) + (
        f"Handed off to continuation agent {replacement_agent_id} / task "
        f"{replacement_task_id} after change {change.get('id')} approval."
    )
    await execute("""
        UPDATE agents
        SET status = 'finished',
            error_message = $1,
            heartbeat = NOW(),
            finished_at = COALESCE(finished_at, NOW())
        WHERE id = $2
          AND status IN ('awaiting_access', 'pending_approval', 'blocked', 'awaiting_user_response')
    """, handoff_message[:1000], source_agent_id)
    source_task_id = source_agent.get("last_task_id") if source_agent else None
    if source_task_id:
        await execute("""
            UPDATE agent_tasks
            SET status = 'completed',
                output = $1,
                error_message = NULL,
                completed_at = COALESCE(completed_at, NOW()),
                progress_pct = 100
            WHERE id = $2
              AND status IN ('awaiting_access', 'pending_approval', 'blocked', 'awaiting_user_response')
        """, handoff_message[:5000], source_task_id)
    await log_event("agent", "info", approved_by, "agent_handoff_after_approval",
                    f"agent_{source_agent_id}", {
                        "change_id": change.get("id"),
                        "ticket_id": ticket_id,
                        "source_agent_id": source_agent_id,
                        "source_task_id": source_task_id,
                        "replacement_agent_id": replacement_agent_id,
                        "replacement_task_id": replacement_task_id,
                        "note_id": note_id,
                    })
    return {
        "status": "recorded",
        "note_id": note_id,
        "source_agent_id": source_agent_id,
        "replacement_agent_id": replacement_agent_id,
        "replacement_task_id": replacement_task_id,
    }


async def _sync_access_request_status(change, status, actor, evidence=None):
    policy = _access_policy(change)
    if not policy:
        return {"status": "not_access_request"}
    change_id = change.get("id")
    if status == "approved":
        access_request = await fetchrow("""
            UPDATE access_requests
            SET status = 'approved',
                approval_actor = $1,
                updated_at = NOW()
            WHERE change_id = $2
            RETURNING *
        """, actor, change_id)
    elif status == "completed":
        access_request = await fetchrow("""
            UPDATE access_requests
            SET status = 'granted',
                grant_evidence = $1,
                updated_at = NOW()
            WHERE change_id = $2
            RETURNING *
        """, evidence or "", change_id)
    elif status == "rejected":
        access_request = await fetchrow("""
            UPDATE access_requests
            SET status = 'rejected',
                approval_actor = $1,
                grant_evidence = $2,
                updated_at = NOW()
            WHERE change_id = $3
            RETURNING *
        """, actor, evidence or "", change_id)
    else:
        return {"status": "ignored", "requested_status": status}

    if not access_request:
        return {"status": "missing_access_request", "change_id": change_id}

    title = {
        "approved": "Access gate approved",
        "completed": "Access granted",
        "rejected": "Access gate rejected",
    }.get(status, "Access request updated")
    body = "\n".join([
        f"Access request `{access_request['id']}` moved to `{access_request['status']}`.",
        f"Resource: `{access_request['resource']}`.",
        f"Permission: `{access_request['permission']}`.",
        f"Actor: `{actor}`.",
        f"Evidence: {evidence or 'Approval status update recorded.'}",
    ])
    await _add_gate_note(access_request.get("parent_ticket_id"), change_id, title, body, actor, "access-request")
    if access_request.get("access_ticket_id"):
        await _add_gate_note(access_request.get("access_ticket_id"), change_id, title, body, actor, "access-request")
        provider_close = {"status": "skipped", "reason": "not_terminal_or_local"}
        if status in ("completed", "rejected"):
            await execute("""
                UPDATE tickets
                SET status = $1, updated_at = NOW()
                WHERE id = $2
            """, "resolved" if status == "completed" else "closed", access_request.get("access_ticket_id"))
            if status == "completed":
                access_ticket = await fetchrow(
                    """
                    SELECT id, provider, provider_ref, provider_class, itop_ref, itop_class
                    FROM tickets
                    WHERE id = $1
                    """,
                    access_request.get("access_ticket_id"),
                )
                provider_name = (access_ticket or {}).get("provider") or "local"
                provider_ref = (access_ticket or {}).get("provider_ref") or (access_ticket or {}).get("itop_ref")
                if provider_name != "local" and provider_ref:
                    try:
                        from services import provider_registry
                        provider_close = await provider_registry.close_ticket(
                            provider_name,
                            access_request.get("access_ticket_id"),
                            evidence or f"Access request {access_request['id']} completed by {actor}.",
                        )
                    except Exception as exc:
                        provider_close = {"error": str(exc), "provider": provider_name}
                    if provider_close.get("error"):
                        await log_event(
                            "sync",
                            "warning",
                            actor,
                            "access_request_provider_close_failed",
                            f"ticket_{access_request.get('access_ticket_id')}",
                            {
                                "provider": provider_name,
                                "provider_ref": provider_ref,
                                "error": provider_close.get("error"),
                            },
                        )
                    else:
                        await log_event(
                            "sync",
                            "info",
                            actor,
                            "access_request_provider_close_complete",
                            f"ticket_{access_request.get('access_ticket_id')}",
                            {
                                "provider": provider_name,
                                "provider_ref": provider_ref,
                                "result": provider_close,
                            },
                        )
    await log_event("access", "info", actor, f"access_request_{status}",
                    f"access_request_{access_request['id']}", {
                        "change_id": change_id,
                        "parent_ticket_id": access_request.get("parent_ticket_id"),
                        "access_ticket_id": access_request.get("access_ticket_id"),
                        "status": access_request.get("status"),
                    })
    granted_leases = []
    if status == "completed":
        lease_request = policy.get("lease_request")
        inferred_on_completion = False
        if not lease_request:
            lease_request = infer_lease_request(
                access_request.get("resource"),
                access_request.get("permission"),
                access_request.get("account_ref"),
            )
            inferred_on_completion = bool(lease_request)
            if inferred_on_completion:
                await log_event(
                    "access",
                    "warning",
                    actor,
                    "access_request_lease_inferred_on_completion",
                    f"access_request_{access_request['id']}",
                    {
                        "change_id": change_id,
                        "resource": access_request.get("resource"),
                        "permission": access_request.get("permission"),
                        "lease_request": lease_request,
                        "reason": "approval_policy_missing_lease_request",
                    },
                )
        if lease_request:
            candidate_agent_ids = []
            if access_request.get("agent_id"):
                candidate_agent_ids.append(access_request.get("agent_id"))
            if actor and str(actor).startswith("agent_"):
                try:
                    candidate_agent_ids.append(int(str(actor).split("_", 1)[1]))
                except (TypeError, ValueError):
                    pass
            for candidate in dict.fromkeys(candidate_agent_ids):
                granted = await access_control.grant_agent_vault_lease(
                    candidate,
                    lease_request,
                    granted_by=actor,
                    evidence=evidence,
                )
                granted_leases.append(granted)
        elif not lease_request:
            await log_event(
                "access",
                "error",
                actor,
                "access_request_lease_not_granted",
                f"access_request_{access_request['id']}",
                {
                    "change_id": change_id,
                    "resource": access_request.get("resource"),
                    "permission": access_request.get("permission"),
                    "reason": "no_explicit_or_inferred_lease_request",
                },
            )
    return {
        "status": access_request.get("status"),
        "access_request_id": access_request.get("id"),
        "granted_leases": granted_leases,
        "provider_close": provider_close if access_request.get("access_ticket_id") else {"status": "skipped", "reason": "no_access_ticket"},
    }


async def _resume_agent_after_approval(change, approved_by):
    """Spawn a continuation agent when an approval gate opens.

    This keeps approval-driven recovery inside the control plane instead of
    requiring a fragile model-side heartbeat loop. If the original agent still
    has an active task, do nothing and let it observe the approval itself.
    """
    agent_id = change.get("agent_id")
    ticket_id = change.get("ticket_id")
    if not agent_id or not ticket_id:
        return {"status": "not_applicable", "reason": "change has no agent_id"}

    active_task = await fetchrow("""
        SELECT id, status, work_dir FROM agent_tasks
        WHERE agent_id = $1 AND status IN ('queued', 'running')
        ORDER BY created_at DESC LIMIT 1
    """, agent_id)
    if active_task:
        steering = {"status": "not_attempted"}
        try:
            from services import agent_steering
            steering = await agent_steering.record_ticket_note(
                ticket_id,
                None,
                (
                    f"Approval gate `{change.get('id')}` for `{change.get('action')}` on `{change.get('target')}` "
                    f"was approved by `{approved_by}` while agent `{agent_id}` task `{active_task['id']}` was already running. "
                    "Re-read the current change/access status before writing any wait checkpoint. If the gate is approved or completed, continue the original ticket objective instead of waiting."
                ),
                author=approved_by,
                source="dashboard",
            )
        except Exception as exc:
            steering = {"status": "failed", "error": str(exc)}
        await log_event("agent", "info", approved_by, "approval_update_delivered_to_active_agent",
                        f"agent_{agent_id}", {
                            "change_id": change.get("id"),
                            "ticket_id": ticket_id,
                            "task_id": active_task["id"],
                            "steering": steering,
                        })
        return {"status": "already_active", "task_id": active_task["id"], "steering": steering}

    active_ticket_agent = await fetchrow("""
        SELECT a.id, a.status, a.last_task_id
        FROM agents a
        LEFT JOIN agent_tasks at ON at.id = a.last_task_id
        WHERE a.ticket_id = $1
          AND (
              a.status IN ('spawned', 'running', 'working')
              OR at.status IN ('queued', 'running')
          )
        ORDER BY a.started_at DESC NULLS LAST, a.id DESC
        LIMIT 1
    """, ticket_id)
    if active_ticket_agent:
        source_agent = await fetchrow(
            "SELECT error_message, last_task_id FROM agents WHERE id = $1",
            agent_id,
        )
        handoff = await _record_resume_handoff(
            change,
            source_agent,
            {
                "agent_id": active_ticket_agent["id"],
                "task_id": active_ticket_agent.get("last_task_id"),
            },
            approved_by,
        )
        await log_event("agent", "info", approved_by, "approval_resume_skipped_active_ticket_agent",
                        f"ticket_{ticket_id}", {
                            "change_id": change["id"],
                            "source_agent_id": agent_id,
                            "active_agent_id": active_ticket_agent["id"],
                            "active_task_id": active_ticket_agent.get("last_task_id"),
                            "handoff": handoff,
                        })
        return {
            "status": "already_active_ticket",
            "agent_id": active_ticket_agent["id"],
            "task_id": active_ticket_agent.get("last_task_id"),
            "handoff": handoff,
        }

    agent = await fetchrow("SELECT model, selected_model, error_message, last_task_id FROM agents WHERE id = $1", agent_id)
    latest_task = await fetchrow("""
        SELECT prompt, task_type FROM agent_tasks
        WHERE agent_id = $1
        ORDER BY created_at DESC LIMIT 1
    """, agent_id)
    if not agent or not latest_task:
        return {"status": "not_resumed", "reason": "missing source agent/task"}

    continuation = "\n\nApproval update:\n"
    continuation += f"- Change request {change['id']} was approved by {approved_by}.\n"
    continuation += "- Continue from the approval gate, perform only the approved safe/test action, document the result as a ticket note, mark the change complete with compile/test/diff or operational evidence, and update checkpoint.json to done.\n"

    from services import agent_runner
    result = await agent_runner.spawn_agent(
        ticket_id,
        agent.get("selected_model") or agent.get("model") or "deepseek/deepseek-v4-flash",
        (latest_task.get("prompt") or "") + continuation,
        latest_task.get("task_type") or "ticket_resolution",
        actor_context=await access_control.load_agent_subject(agent_id),
    )
    await log_event("agent", "info", approved_by, "agent_resumed_after_approval",
                    f"agent_{agent_id}", {
                        "change_id": change["id"],
                        "ticket_id": ticket_id,
                        "agent_id": agent_id,
                        "replacement_agent_id": result.get("agent_id"),
                        "replacement_task_id": result.get("task_id"),
                    })
    handoff = await _record_resume_handoff(change, agent, result, approved_by)
    return {"status": "resumed", "handoff": handoff, **result}

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
        where_clauses.append(f"cr.status = ${param_idx}")
        params.append(status)
        param_idx += 1
    if agent_id:
        where_clauses.append(f"cr.agent_id = ${param_idx}")
        params.append(agent_id)
        param_idx += 1
    if ticket_id:
        where_clauses.append(f"cr.ticket_id = ${param_idx}")
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
                    f"change_{change_id}", {
                        "ticket_id": ticket_id,
                        "agent_id": agent_id,
                        "risk_level": risk_level,
                        "approval_gate": True,
                        "gate_status": "pending",
                    })
    await _add_gate_note(
        ticket_id,
        change_id,
        f"Approval gate opened: change {change_id}",
        (
            f"A change approval gate was created before `{action}` on `{target}`.\n"
            f"Risk level: `{risk_level}`.\n"
            f"Requested by: `{actor}`.\n"
            f"Reason: {reason or 'No reason provided.'}\n\n"
            "The agent must wait here until this gate is approved or rejected."
        ),
        actor,
    )

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
async def approve_change(change_id: int, body: dict = Body({}), request: Request = None):
    approved_by = _approval_actor_from_request(
        request,
        body,
        "approved_by",
        "actor",
        default="dashboard",
    )
    approval_reason = (body or {}).get("reason") or (body or {}).get("approval_reason") or ""
    change = await fetchrow("SELECT * FROM change_requests WHERE id = $1", change_id)
    if not change:
        return {"error": "Change request not found"}
    if change["status"] == "approved":
        resume = await _resume_agent_after_approval({**change, "id": change_id}, approved_by)
        return {
            "status": "approved",
            "change_id": change_id,
            "already_approved": True,
            "resume": resume,
        }
    if change["status"] != "pending":
        return {"error": f"Change request is {change['status']}, not pending"}

    await execute("""
        UPDATE change_requests SET status = 'approved', approved_by = $1,
                                  approved_at = NOW() WHERE id = $2
    """, approved_by, change_id)

    auto_approved = _is_auto_approver(approved_by)
    approval_mode = "demo_auto_approval" if auto_approved else "manual_approval"
    await execute("""
        INSERT INTO audit_log (actor, action, target, details)
        VALUES ($1, $2, $3, $4)
    """, approved_by, "change_approved", f"change_{change_id}", json_dumps({
        "change_id": change_id,
        "approved_by": approved_by,
        "approval_actor": approved_by,
        "action": change["action"],
        "target": change["target"],
        "agent_id": change["agent_id"],
        "ticket_id": change["ticket_id"],
        "risk_level": change["risk_level"],
        "approval_gate": True,
        "approval_mode": approval_mode,
        "auto_approved": auto_approved,
        "approval_reason": approval_reason,
    }))
    await log_event("change", "info", approved_by, "change_approved",
                    f"change_{change_id}", {
                        "ticket_id": change["ticket_id"],
                        "agent_id": change["agent_id"],
                        "change_id": change_id,
                        "action": change["action"],
                        "target": change["target"],
                        "risk_level": change["risk_level"],
                        "approved_by": approved_by,
                        "approval_actor": approved_by,
                        "approval_gate": True,
                        "approval_mode": approval_mode,
                        "auto_approved": auto_approved,
                    })
    note_title = (
        f"Approval gate AUTO-APPROVED: change {change_id}"
        if auto_approved else
        f"Approval gate approved: change {change_id}"
    )
    note_body = (
        f"Gate `{change_id}` for `{change['action']}` on `{change['target']}` was approved by `{approved_by}`.\n"
        f"Approval mode: `{approval_mode}`.\n"
        f"Risk level: `{change['risk_level']}`.\n"
        f"Agent: `{change['agent_id'] or 'none'}`.\n"
    )
    if auto_approved:
        note_body += "\nThis environment is currently configured for demo/lab auto-approval so the approval chain is visible without waiting for a human click. In production this same gate would wait for an authorized approver."
    if approval_reason:
        note_body += f"\nApproval reason: {approval_reason}"
    await _add_gate_note(change["ticket_id"], change_id, note_title, note_body, approved_by, "approval-gate")
    await _sync_access_request_status({**change, "id": change_id}, "approved", approved_by, approval_reason)

    resume = await _resume_agent_after_approval({**change, "id": change_id}, approved_by)
    return {"status": "approved", "change_id": change_id, "resume": resume}

@router.post("/{change_id}/reject")
async def reject_change(
    change_id: int,
    body: dict = Body({}),
    request: Request = None,
):
    rejected_by = _approval_actor_from_request(
        request,
        body,
        "rejected_by",
        "actor",
        default="dashboard",
    )
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
        "change_id": change_id,
        "rejected_by": rejected_by,
        "approval_actor": rejected_by,
        "reason": reason,
        "action": change["action"],
        "target": change["target"],
        "agent_id": change["agent_id"],
        "ticket_id": change["ticket_id"],
        "risk_level": change["risk_level"],
        "approval_gate": True,
    }))
    await log_event("change", "warning", rejected_by, "change_rejected",
                    f"change_{change_id}", {
                        "ticket_id": change["ticket_id"],
                        "agent_id": change["agent_id"],
                        "change_id": change_id,
                        "action": change["action"],
                        "target": change["target"],
                        "rejected_by": rejected_by,
                        "approval_actor": rejected_by,
                        "approval_gate": True,
                        "gate_status": "rejected",
                    })
    await _add_gate_note(
        change["ticket_id"],
        change_id,
        f"Approval gate rejected: change {change_id}",
        f"Gate `{change_id}` for `{change['action']}` on `{change['target']}` was rejected by `{rejected_by}`.\nReason: {reason}",
        rejected_by,
        "approval-gate",
    )
    await _sync_access_request_status({**change, "id": change_id}, "rejected", rejected_by, reason)

    return {"status": "rejected", "change_id": change_id}

@router.post("/{change_id}/complete")
async def complete_change(change_id: int, body: dict = Body({})):
    result = _completion_result_from_body(body)
    actor = _completion_actor_from_body(body)
    change = await fetchrow("SELECT * FROM change_requests WHERE id = $1", change_id)
    if not change:
        return {"error": "Change request not found"}
    if not result:
        return {"error": "Change completion requires non-empty result, evidence, or output"}

    await execute("""
        UPDATE change_requests SET status = 'completed', result = $1 WHERE id = $2
    """, result, change_id)
    await execute("""
        INSERT INTO audit_log (actor, action, target, details)
        VALUES ($1, $2, $3, $4)
    """, actor, "change_completed", f"change_{change_id}", json_dumps({
        "change_id": change_id,
        "agent_id": change["agent_id"],
        "ticket_id": change["ticket_id"],
        "result": result[:1000] if result else "",
    }))
    await log_event("change", "info", actor, "change_completed",
                    f"change_{change_id}", {
                        "ticket_id": change["ticket_id"],
                        "agent_id": change["agent_id"],
                        "approval_gate": True,
                        "gate_status": "completed",
                        "result": result[:500] if result else "",
                    })
    await _add_gate_note(
        change["ticket_id"],
        change_id,
        f"Approval gate completed: change {change_id}",
        (
            f"Gate `{change_id}` for `{change['action']}` on `{change['target']}` moved to completed by `{actor}`.\n"
            f"Evidence/result: {result[:1200] if result else 'No result provided.'}"
        ),
        actor,
        "approval-gate",
    )
    access_sync = await _sync_access_request_status({**change, "id": change_id}, "completed", actor, result)

    return {"status": "completed", "change_id": change_id, "access_sync": access_sync}
