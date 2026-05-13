"""Auditable agent supervision loop.

This service checks whether agents are making progress, whether they are blocked
on approval, and whether a safe recovery action is available. It records every
finding in PostgreSQL before taking action.
"""
import asyncio
import json
import os
from datetime import datetime, timedelta, timezone

from database import fetchall, fetchrow, fetchval, execute, json_dumps
from services.event_logger import log_event


AUDIT_INTERVAL = int(os.getenv("AGENT_AUDIT_INTERVAL", "60"))
NO_PROGRESS_MINUTES = int(os.getenv("AGENT_AUDIT_NO_PROGRESS_MINUTES", "30"))
MAX_RECOVERY_ATTEMPTS = int(os.getenv("AGENT_AUDIT_MAX_RECOVERY_ATTEMPTS", "2"))
AUTO_RECOVER = os.getenv("AGENT_AUDITOR_AUTO_RECOVER", "false").lower() in ("1", "true", "yes", "on")


def _loads(value, default):
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value


def _parse_time(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _as_aware_utc(value):
    parsed = _parse_time(value)
    if not parsed:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _file_mtime(path):
    if not path:
        return None
    try:
        return datetime.fromtimestamp(os.path.getmtime(path), timezone.utc)
    except OSError:
        return None


def _latest_activity(task):
    checkpoints = _loads(task.get("checkpoints"), [])
    seen = [
        _as_aware_utc(task.get("started_at")),
        _as_aware_utc(task.get("agent_heartbeat")),
        _as_aware_utc(task.get("latest_note_at")),
        _as_aware_utc(task.get("latest_change_at")),
    ]
    if checkpoints and isinstance(checkpoints[-1], dict):
        seen.append(_as_aware_utc(checkpoints[-1].get("timestamp")))
    if task.get("work_dir"):
        seen.append(_file_mtime(os.path.join(task["work_dir"], "output.log")))
        seen.append(_file_mtime(os.path.join(task["work_dir"], "checkpoint.json")))
    valid = [item for item in seen if item]
    return max(valid) if valid else None


async def _has_pending_approval(agent_id, ticket_id):
    count = await fetchval("""
        SELECT COUNT(*) FROM change_requests
        WHERE status = 'pending'
          AND (($1::integer IS NOT NULL AND agent_id = $1)
               OR ($2::integer IS NOT NULL AND ticket_id = $2))
    """, agent_id, ticket_id)
    return bool(count)


async def _recent_duplicate(task_id, finding, minutes=15):
    return await fetchrow("""
        SELECT id FROM agent_audit_reviews
        WHERE task_id = $1 AND finding = $2
          AND created_at > NOW() - ($3::text || ' minutes')::interval
        ORDER BY created_at DESC LIMIT 1
    """, task_id, finding, str(minutes))


async def _recent_ticket_duplicate(ticket_id, finding, minutes=60):
    if not ticket_id:
        return None
    return await fetchrow("""
        SELECT id FROM agent_audit_reviews
        WHERE ticket_id = $1 AND finding = $2
          AND created_at > NOW() - ($3::text || ' minutes')::interval
        ORDER BY created_at DESC LIMIT 1
    """, ticket_id, finding, str(minutes))


async def _ticket_has_other_active_agent(ticket_id, agent_id):
    if not ticket_id:
        return None
    return await fetchrow("""
        SELECT id, status
        FROM agents
        WHERE ticket_id = $1
          AND id <> $2
          AND status IN ('spawned', 'running', 'working')
        ORDER BY started_at DESC
        LIMIT 1
    """, ticket_id, agent_id or 0)


async def _record(agent_id, task_id, ticket_id, severity, finding, recommended_action=None,
                  action_taken=None, approval_blocked=False, details=None):
    review_id = await fetchval("""
        INSERT INTO agent_audit_reviews (
            agent_id, task_id, ticket_id, severity, finding, recommended_action,
            action_taken, approval_blocked, details
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
        RETURNING id
    """, agent_id, task_id, ticket_id, severity, finding, recommended_action,
        action_taken, approval_blocked, json_dumps(details or {}))
    await log_event("agent-auditor", severity, "agent-auditor", finding,
                    f"agent_{agent_id}" if agent_id else None, {
                        "review_id": review_id,
                        "task_id": task_id,
                        "ticket_id": ticket_id,
                        "recommended_action": recommended_action,
                        "action_taken": action_taken,
                        "approval_blocked": approval_blocked,
                    })
    return review_id


async def _spawn_replacement(agent, task, reason):
    if not AUTO_RECOVER:
        return "audit_only"
    other_active = await _ticket_has_other_active_agent(agent.get("ticket_id"), agent.get("id"))
    if other_active:
        return f"blocked_other_active_agent_{other_active['id']}"
    if task.get("task_type") == "postmortem":
        from services.postmortem_synthesizer import synthesize_postmortem
        result = await synthesize_postmortem(
            agent["ticket_id"],
            agent.get("id"),
            task.get("id"),
            "agent-auditor",
            reason,
        )
        return f"postmortem_synthesized_{result.get('postmortem_id')}"
    if task.get("status") != "running":
        return "audit_only_non_running_task"
    attempts = int(agent.get("attempts") or 0)
    if attempts >= MAX_RECOVERY_ATTEMPTS:
        return "max_attempts_reached"
    from services import agent_runner
    result = await agent_runner.spawn_agent(
        agent["ticket_id"],
        agent.get("selected_model") or agent.get("model") or "qwen/qwen3.6-27b",
        task.get("prompt") or f"Continue ticket {agent['ticket_id']} and recover from: {reason}",
        task.get("task_type") or "ticket_resolution",
    )
    await execute("UPDATE agents SET attempts = attempts + 1 WHERE id = $1", agent["id"])
    return f"replacement_agent_{result.get('agent_id')}"


async def _audit_task(row):
    agent = {
        "id": row.get("agent_id"),
        "ticket_id": row.get("ticket_id"),
        "model": row.get("model"),
        "selected_model": row.get("selected_model"),
        "attempts": row.get("attempts"),
    }
    task = {
        "id": row.get("task_id"),
        "ticket_id": row.get("ticket_id"),
        "status": row.get("task_status"),
        "prompt": row.get("prompt"),
        "task_type": row.get("task_type"),
        "checkpoints": row.get("checkpoints"),
        "started_at": row.get("started_at"),
        "agent_heartbeat": row.get("agent_heartbeat"),
        "work_dir": row.get("work_dir"),
        "latest_note_at": row.get("latest_note_at"),
        "latest_change_at": row.get("latest_change_at"),
    }
    if task["status"] == "completed":
        from services import agent_runner
        completion = await agent_runner.complete_approved_changes_for_task(
            agent["id"],
            task["id"],
            reason="agent_auditor_completed_task_sweep",
        )
        if completion.get("completed") and not await _recent_duplicate(task["id"], "approved_change_auto_completed", 60):
            await _record(agent["id"], task["id"], agent["ticket_id"], "info",
                          "approved_change_auto_completed", "none",
                          "auto_completed_changes", False, completion)
        return

    other_active = await _ticket_has_other_active_agent(agent["ticket_id"], agent["id"])
    if other_active:
        if not await _recent_duplicate(task["id"], "ticket_already_has_active_agent", 30):
            await _record(agent["id"], task["id"], agent["ticket_id"], "info",
                          "ticket_already_has_active_agent", "do_not_spawn_duplicate",
                          f"active_agent_{other_active['id']}", False,
                          {"active_agent_id": other_active["id"], "active_agent_status": other_active["status"]})
        return

    approval_blocked = await _has_pending_approval(agent["id"], agent["ticket_id"])
    last_seen = _latest_activity(task)
    age_minutes = None
    if last_seen:
        age_minutes = (datetime.now(timezone.utc) - last_seen).total_seconds() / 60

    if approval_blocked:
        if not await _recent_duplicate(task["id"], "agent_waiting_on_approval", 30):
            await _record(agent["id"], task["id"], agent["ticket_id"], "info",
                          "agent_waiting_on_approval", "no_recovery_while_approval_pending",
                          None, True, {"age_minutes": age_minutes})
        return

    if task["status"] == "running" and age_minutes is not None and age_minutes > NO_PROGRESS_MINUTES:
        if await _recent_duplicate(task["id"], "agent_no_progress", 15):
            return
        action = await _spawn_replacement(agent, task, f"no progress for {age_minutes:.1f} minutes")
        await _record(agent["id"], task["id"], agent["ticket_id"], "warning",
                      "agent_no_progress", "spawn_replacement_agent", action,
                      False, {
                          "age_minutes": age_minutes,
                          "threshold_minutes": NO_PROGRESS_MINUTES,
                          "last_activity_at": last_seen.isoformat() if last_seen else None,
                          "progress_sources": [
                              "checkpoint",
                              "agent_heartbeat",
                              "output_log_mtime",
                              "ticket_note",
                              "change_request",
                          ],
                      })
    elif task["status"] == "failed":
        if await _recent_duplicate(task["id"], "agent_task_failed", 120):
            return
        if await _recent_ticket_duplicate(agent["ticket_id"], "agent_task_failed", 30):
            return
        if task.get("task_type") == "postmortem":
            from services.postmortem_synthesizer import synthesize_postmortem
            result = await synthesize_postmortem(
                agent["ticket_id"],
                agent["id"],
                task["id"],
                "agent-auditor",
                "postmortem task failed",
            )
            action = f"postmortem_synthesized_{result.get('postmortem_id')}"
        else:
            action = await _spawn_replacement(agent, task, "task failed")
        await _record(agent["id"], task["id"], agent["ticket_id"], "warning",
                      "agent_task_failed", "spawn_replacement_agent", action,
                      False, {"attempts": agent.get("attempts") or 0})
    elif task["status"] in ("queued", "running"):
        if not await _recent_duplicate(task["id"], "agent_progress_ok", 60):
            await _record(agent["id"], task["id"], agent["ticket_id"], "info",
                          "agent_progress_ok", None, None, False,
                          {"age_minutes": age_minutes, "task_status": task["status"]})


async def audit_once():
    rows = await fetchall("""
        SELECT a.id AS agent_id, a.ticket_id, a.model, a.selected_model, a.attempts,
               t.id AS task_id, t.status AS task_status, t.prompt, t.task_type,
               t.checkpoints, t.started_at, t.work_dir, a.heartbeat AS agent_heartbeat,
               (
                 SELECT MAX(n.created_at)
                 FROM ticket_notes n
                 WHERE n.ticket_id = a.ticket_id
                   AND (n.author = ('agent-' || a.id::text)
                        OR n.source LIKE 'agent%')
               ) AS latest_note_at,
               (
                 SELECT MAX(cr.requested_at)
                 FROM change_requests cr
                 WHERE cr.ticket_id = a.ticket_id
                   AND (cr.agent_id = a.id OR cr.agent_id IS NULL)
               ) AS latest_change_at
        FROM agents a
        JOIN LATERAL (
            SELECT * FROM agent_tasks
            WHERE agent_id = a.id
            ORDER BY created_at DESC
            LIMIT 1
        ) t ON true
        WHERE a.status IN ('spawned', 'running', 'working')
           OR t.status IN ('queued', 'running')
           OR (t.status = 'failed' AND t.created_at > NOW() - INTERVAL '2 hours')
           OR (
                t.status = 'completed'
                AND EXISTS (
                    SELECT 1 FROM change_requests cr
                    WHERE cr.agent_id = a.id
                      AND cr.status = 'approved'
                      AND (cr.ticket_id = a.ticket_id OR cr.ticket_id IS NULL)
                )
           )
        ORDER BY a.started_at DESC
        LIMIT 100
    """)
    for row in rows:
        await _audit_task(row)
    return {"audited": len(rows)}


async def audit_loop():
    print(f"Agent auditor loop started (interval: {AUDIT_INTERVAL}s, auto_recover={AUTO_RECOVER})")
    while True:
        try:
            await audit_once()
        except Exception as exc:
            print(f"Agent auditor error: {exc}")
        await asyncio.sleep(AUDIT_INTERVAL)
