import os
import json
import asyncio
import signal
from datetime import datetime, timedelta, timezone
from database import fetchall, execute, fetchrow, fetchval
from services.event_logger import log_event

TRACK_INTERVAL = int(os.getenv("TRACK_INTERVAL", "10"))
STUCK_TIMEOUT_MINUTES = int(os.getenv("STUCK_TIMEOUT_MINUTES", "60"))
AGENT_WORK_BASE = os.getenv("AGENT_WORK_BASE", "/app/agent_work")

broadcast_fn = None


def set_broadcast(fn):
    global broadcast_fn
    broadcast_fn = fn


async def _read_checkpoint(work_dir):
    """Read checkpoint.json from agent work directory."""
    checkpoint_path = os.path.join(work_dir, "checkpoint.json")
    try:
        with open(checkpoint_path, "r") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


async def _add_checkpoint_note(task, step, status, output, progress):
    """Persist a readable checkpoint note so demos show what agents are doing."""
    if not task.get("ticket_id"):
        return None
    title = f"Agent checkpoint: {step}"
    body = (
        f"{title}\n\n"
        f"Agent `{task['agent_id']}` task `{task['id']}` reported `{status}` "
        f"at {progress or 0}% progress."
    )
    if output:
        body = f"{body}\n\n{str(output)[:900]}"
    note_id = await fetchval("""
        INSERT INTO ticket_notes (ticket_id, source, author, body, visibility)
        VALUES ($1, 'agent-checkpoint', $2, $3, 'internal')
        RETURNING id
    """, task["ticket_id"], f"agent-{task['agent_id']}", body)
    await execute("UPDATE tickets SET updated_at = NOW() WHERE id = $1", task["ticket_id"])
    await log_event("ticket", "info", f"agent_{task['agent_id']}",
                    "agent_checkpoint_note_added", f"ticket_{task['ticket_id']}", {
                        "note_id": note_id,
                        "agent_id": task["agent_id"],
                        "task_id": task["id"],
                        "step": step,
                        "status": status,
                        "progress_pct": progress,
                    })
    return note_id


def _is_agent_process_alive(pid):
    if not pid:
        return False
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    proc_cmdline = f"/proc/{pid}/cmdline"
    try:
        with open(proc_cmdline, "rb") as handle:
            cmdline = handle.read().replace(b"\x00", b" ").decode("utf-8", errors="replace").lower()
    except FileNotFoundError:
        return False
    except OSError:
        return False
    return "claude" in cmdline or "anthropic-ai" in cmdline or "node" in cmdline


def _as_aware_utc(value):
    if not value:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        try:
            dt = datetime.fromisoformat(str(value))
        except ValueError:
            return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _file_mtime(path):
    if not path:
        return None
    try:
        return datetime.fromtimestamp(os.path.getmtime(path), timezone.utc)
    except OSError:
        return None


def _latest_activity(task, checkpoints):
    seen = [
        _as_aware_utc(task.get("started_at")),
        _as_aware_utc(task.get("heartbeat")),
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


async def _mark_orphaned(task, reason):
    await execute(
        "UPDATE agent_tasks SET status = 'failed', error_message = $1, completed_at = NOW() WHERE id = $2",
        reason,
        task["id"],
    )
    await execute(
        "UPDATE agents SET status = 'failed', heartbeat = NOW(), error_message = $1, finished_at = NOW() WHERE id = $2",
        reason,
        task["agent_id"],
    )
    await log_event("agent", "warning", f"agent_{task['agent_id']}",
                    "task_orphaned", f"task_{task['id']}", {
                        "ticket_id": task["ticket_id"],
                        "pid": task.get("pid"),
                        "reason": reason,
                    })
    if broadcast_fn:
        await broadcast_fn({
            "type": "agent_failed",
            "agent_id": task["agent_id"],
            "ticket_id": task["ticket_id"],
            "task_id": task["id"],
            "reason": reason,
        })


async def _sync_task_status(task):
    """Poll checkpoint and update task + agent status."""
    work_dir = task.get("work_dir")
    if not work_dir:
        return

    cp = await _read_checkpoint(work_dir)
    if not cp:
        return

    step = cp.get("step", "unknown")
    status = cp.get("status", "running")
    output = cp.get("output", "")
    progress = cp.get("progress_pct", 0)

    # Build checkpoints array
    existing = task.get("checkpoints") or []
    if isinstance(existing, str):
        try:
            existing = json.loads(existing)
        except json.JSONDecodeError:
            existing = []
    # Only append if this is a new checkpoint (different step or status)
    is_new_checkpoint = not existing or existing[-1].get("step") != step or existing[-1].get("status") != status
    if is_new_checkpoint:
        existing.append({
            "step": step,
            "status": status,
            "output": output[:500] if output else "",
            "timestamp": cp.get("timestamp", datetime.now().isoformat()),
        })
    else:
        existing[-1]["output"] = output[:500] if output else existing[-1].get("output", "")
        existing[-1]["timestamp"] = cp.get("timestamp", datetime.now().isoformat())

    # Map checkpoint status to task status. Local models sometimes use "done"
    # for an intermediate step; only 100% progress is terminal.
    task_status = "running"
    if status in ("done", "completed") and int(progress or 0) >= 100:
        task_status = "completed"
    elif status == "error":
        task_status = "failed"
    elif status in ("done", "completed"):
        await log_event("agent", "warning", f"agent_{task['agent_id']}",
                        "checkpoint_done_ignored_before_100", f"task_{task['id']}", {
                            "ticket_id": task["ticket_id"],
                            "step": step,
                            "status": status,
                            "progress_pct": progress,
                        })

    await execute(
        "UPDATE agent_tasks SET checkpoints = $1, progress_pct = GREATEST(progress_pct, $2), status = $3 WHERE id = $4",
        json.dumps(existing), progress, task_status, task["id"],
    )

    # Sync agent status
    agent_status_map = {
        "running": "working",
        "completed": "finished",
        "failed": "failed",
        "stopped": "stopped",
    }
    agent_status = agent_status_map.get(task_status, "working")
    await execute(
        "UPDATE agents SET status = $1, heartbeat = NOW() WHERE id = $2",
        agent_status, task["agent_id"],
    )
    if is_new_checkpoint and step != "init":
        await _add_checkpoint_note(task, step, status, output, progress)

    # Complete ticket if agent finished
    if task_status == "completed":
        if task.get("pid"):
            try:
                os.kill(task["pid"], signal.SIGTERM)
            except ProcessLookupError:
                pass
            except PermissionError:
                await log_event("agent", "warning", f"agent_{task['agent_id']}",
                                "task_completed_process_stop_denied", f"pid_{task['pid']}")
        await execute(
            "UPDATE agent_tasks SET completed_at = NOW(), progress_pct = 100 WHERE id = $1",
            task["id"],
        )
        await execute(
            "UPDATE agents SET status = 'finished', finished_at = NOW() WHERE id = $1",
            task["agent_id"],
        )
        from services import agent_runner
        provider_close = {"status": "skipped", "reason": "not_ticket_resolution"}
        if task.get("task_type") == "ticket_resolution":
            await execute(
                "UPDATE tickets SET status = 'resolved', updated_at = NOW() WHERE id = $1",
                task["ticket_id"],
            )
            close_fn = getattr(agent_runner, "_close_provider_ticket_if_needed", None)
            if close_fn:
                provider_close = await close_fn(
                    task["ticket_id"],
                    task["agent_id"],
                    task["id"],
                    output or "Resolved by SOC agent via checkpoint tracker.",
                )
        change_completion = await agent_runner.complete_approved_changes_for_task(
            task["agent_id"],
            task["id"],
            reason="checkpoint_task_tracker_success",
            checkpoint=cp,
        )
        await log_event("agent", "info", f"agent_{task['agent_id']}", "task_completed",
                        f"task_{task['id']}", {
                            "ticket_id": task["ticket_id"],
                            "auto_completed_changes": change_completion.get("completed", []),
                            "auto_complete_skipped": change_completion.get("skipped", []),
                            "provider_close": provider_close,
                        })

        if broadcast_fn:
            await broadcast_fn({
                "type": "agent_finished",
                "agent_id": task["agent_id"],
                "ticket_id": task["ticket_id"],
                "task_id": task["id"],
            })

    elif task_status == "failed":
        await execute(
            "UPDATE agent_tasks SET completed_at = NOW() WHERE id = $1",
            task["id"],
        )
        await execute(
            "UPDATE agents SET status = 'failed', finished_at = NOW() WHERE id = $1",
            task["agent_id"],
        )
        await log_event("agent", "error", f"agent_{task['agent_id']}", "task_failed",
                        f"task_{task['id']}")

        if broadcast_fn:
            await broadcast_fn({
                "type": "agent_failed",
                "agent_id": task["agent_id"],
                "ticket_id": task["ticket_id"],
                "task_id": task["id"],
            })

    # Broadcast checkpoint update
    if broadcast_fn:
        await broadcast_fn({
            "type": "checkpoint_update",
            "task_id": task["id"],
            "agent_id": task["agent_id"],
            "step": step,
            "status": status,
            "progress_pct": progress,
            "output": output[:200] if output else "",
        })


async def _detect_stuck_tasks():
    """Find tasks with no evidence of activity for STUCK_TIMEOUT_MINUTES."""
    tasks = await fetchall(
        """
        SELECT t.id, t.agent_id, t.ticket_id, t.checkpoints, t.started_at,
               t.work_dir, t.pid, a.heartbeat,
               (
                 SELECT MAX(n.created_at)
                 FROM ticket_notes n
                 WHERE n.ticket_id = t.ticket_id
                   AND (n.author = ('agent-' || t.agent_id::text)
                        OR n.source LIKE 'agent%')
               ) AS latest_note_at,
               (
                 SELECT MAX(cr.requested_at)
                 FROM change_requests cr
                 WHERE cr.ticket_id = t.ticket_id
                   AND (cr.agent_id = t.agent_id OR cr.agent_id IS NULL)
               ) AS latest_change_at
        FROM agent_tasks t
        JOIN agents a ON a.id = t.agent_id
        WHERE t.status = 'running'
        """
    )
    for task in (tasks or []):
        cps = task.get("checkpoints") or []
        if isinstance(cps, str):
            try:
                cps = json.loads(cps)
            except json.JSONDecodeError:
                cps = []

        last_seen = _latest_activity(task, cps)

        if not last_seen:
            continue

        now = datetime.now(timezone.utc)

        if now - last_seen > timedelta(minutes=STUCK_TIMEOUT_MINUTES):
            await execute(
                "UPDATE agent_tasks SET status = 'failed', "
                "error_message = $1, completed_at = NOW() WHERE id = $2",
                f"Stuck - no checkpoint update for {STUCK_TIMEOUT_MINUTES} min",
                task["id"],
            )
            await execute(
                "UPDATE agents SET status = 'failed', heartbeat = NOW(), "
                "error_message = $1, finished_at = NOW() WHERE id = $2",
                f"Task stuck - no progress for {STUCK_TIMEOUT_MINUTES} min",
                task["agent_id"],
            )
            await log_event("agent", "warning", f"agent_{task['agent_id']}",
                            "task_stuck", f"task_{task['id']}", {
                                "last_activity_at": last_seen.isoformat(),
                                "threshold_minutes": STUCK_TIMEOUT_MINUTES,
                                "progress_sources": [
                                    "checkpoint",
                                    "agent_heartbeat",
                                    "output_log_mtime",
                                    "ticket_note",
                                    "change_request",
                                ],
                            })


async def track_loop():
    """Background task tracking loop - replaces heartbeat monitor."""
    print(f"Task tracker loop started (interval: {TRACK_INTERVAL}s)")
    while True:
        try:
            # Get all running tasks
            tasks = await fetchall(
                "SELECT id, agent_id, ticket_id, task_type, status, work_dir, checkpoints, pid "
            "FROM agent_tasks WHERE status IN ('queued', 'running')"
            )
            for task in (tasks or []):
                if task["status"] == "running":
                    if task.get("pid") and not _is_agent_process_alive(task.get("pid")):
                        await _mark_orphaned(task, "Agent process is no longer running in the API container")
                        continue
                    await _sync_task_status(task)

            # Periodically check for stuck tasks
            await _detect_stuck_tasks()

        except Exception as e:
            print(f"Task tracker error: {e}")

        await asyncio.sleep(TRACK_INTERVAL)
