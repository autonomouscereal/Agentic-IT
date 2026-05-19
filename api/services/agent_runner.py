import os
import json
import asyncio
import signal
import shutil
import subprocess
import time
import urllib.request
import itertools
from datetime import datetime, timedelta
from database import execute, fetchrow, fetchval, fetchall
from services.event_logger import log_event
from services.agent_harness import get_harness, list_harnesses


def _env_int(name, default):
    permission_context_result = {"status": "not_recorded", "denied_permissions": []}
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _env_bool(name, default=True):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() not in ("0", "false", "no", "off")


AGENT_WORK_BASE = os.getenv("AGENT_WORK_BASE", "/app/agent_work")
MAX_CONCURRENT_AGENTS = int(os.getenv("MAX_CONCURRENT_AGENTS", "3"))
AGENT_TIMEOUT_MINUTES = int(os.getenv("AGENT_TIMEOUT_MINUTES", "0"))
MODEL_CONFIG_PATH = os.getenv("MODEL_CONFIG_PATH", "/app/agent_models.json")
AGENT_PERMISSION_MODE = os.getenv("AGENT_PERMISSION_MODE", "acceptEdits")
AGENT_ALLOWED_TOOLS = os.getenv(
    "AGENT_ALLOWED_TOOLS",
    "Read,Write,Bash(curl *),Bash(node *),Bash(npx *),Bash(playwright *)",
).strip()
AGENT_LLM_BASE_URL = os.getenv("AGENT_LLM_BASE_URL", "").strip()
AGENT_LLM_AUTH_TOKEN = os.getenv("AGENT_LLM_AUTH_TOKEN", "").strip()
DASHBOARD_API_BASE = os.getenv("DASHBOARD_API_BASE", "http://localhost:8000").strip()
AGENT_DASHBOARD_SESSION_FILE = "dashboard_auth.json"
AGENT_HARNESS = os.getenv("AGENT_HARNESS", "claude-code")
AGENT_CURL_GUARD_ENABLED = _env_bool("AGENT_CURL_GUARD_ENABLED", True)
AGENT_CURL_MAX_OUTPUT_BYTES = _env_int("AGENT_CURL_MAX_OUTPUT_BYTES", 250000)
AGENT_CURL_BLOCKED_PATHS = os.getenv(
    "AGENT_CURL_BLOCKED_PATHS",
    "/openapi.json,/api/tools,/api/tools/status,/api/tools/check-all,/docs,/redoc",
).strip()
AGENT_CURL_ALLOWED_HOSTS = os.getenv(
    "AGENT_CURL_ALLOWED_HOSTS",
    (
        "localhost,127.0.0.1,::1,host.docker.internal,ai-proxy,"
        "192.168.50.222,api.openai.com,api.anthropic.com,"
        "inference-api.nousresearch.com,virustotal.com,*.virustotal.com,"
        "urlscan.io,*.urlscan.io,hybrid-analysis.com,*.hybrid-analysis.com"
    ),
).strip()
AGENT_NO_OUTPUT_STALL_SECONDS = _env_int(
    "AGENT_NO_OUTPUT_STALL_SECONDS",
    _env_int("AGENT_NO_OUTPUT_TIMEOUT_SECONDS", 3600),
)
AGENT_TRANSIENT_MODEL_RETRY_MAX = _env_int("AGENT_TRANSIENT_MODEL_RETRY_MAX", 3)
AGENT_TRANSIENT_MODEL_RETRY_DELAY_SECONDS = _env_int("AGENT_TRANSIENT_MODEL_RETRY_DELAY_SECONDS", 30)

_semaphore = asyncio.Semaphore(MAX_CONCURRENT_AGENTS)
_agent_queue = asyncio.PriorityQueue()
_queue_counter = itertools.count()
_queue_workers = set()
_active_processes = {}
_model_config = None


def _is_transient_model_capacity_error(text):
    """Return true for upstream/provider failures that should be retried."""
    if not text:
        return False
    lowered = str(text).lower()
    patterns = (
        "http 429",
        "http 500",
        "http 502",
        "http 503",
        "http 504",
        "status 429",
        "status 500",
        "status 502",
        "status 503",
        "status 504",
        "temporarily unavailable",
        "upstream capacity",
        "capacity limits",
        "rate limit",
        "rate-limit",
        "overloaded",
        "provider overloaded",
        "model is temporarily unavailable",
    )
    return any(pattern in lowered for pattern in patterns)


async def _requeue_transient_model_retry(priority_rank, work_dir, prompt, task_id, agent_id, delay_seconds):
    """Put the same task back on the runner queue after a provider backoff."""
    if delay_seconds > 0:
        await asyncio.sleep(delay_seconds)
    task_meta = await fetchrow("""
        SELECT at.status AS task_status, a.status AS agent_status
        FROM agent_tasks at
        JOIN agents a ON a.id = at.agent_id
        WHERE at.id = $1 AND at.agent_id = $2
    """, task_id, agent_id)
    if not task_meta:
        return
    if task_meta.get("task_status") != "queued" or task_meta.get("agent_status") in ("stopped", "terminated", "failed", "finished"):
        return
    sequence = next(_queue_counter)
    await _agent_queue.put((priority_rank, sequence, work_dir, prompt, task_id, agent_id))
    await log_event("agent", "info", f"agent_{agent_id}", "agent_transient_model_retry_enqueued",
                    f"task_{task_id}", {
                        "priority_rank": priority_rank,
                        "sequence": sequence,
                        "delay_seconds": delay_seconds,
                    })


async def _schedule_transient_model_retry(agent_id, task_id, task_meta, work_dir, prompt, result, error):
    """Schedule a retry/resume for provider-capacity errors."""
    if AGENT_TRANSIENT_MODEL_RETRY_MAX <= 0 or not _is_transient_model_capacity_error(error):
        return None
    attempts = await fetchval(
        "UPDATE agents SET attempts = COALESCE(attempts, 0) + 1, "
        "status = 'running', heartbeat = NOW(), error_message = $1 WHERE id = $2 "
        "RETURNING attempts",
        f"Transient model/provider capacity error; retry scheduled for task {task_id}"[:500],
        agent_id,
    )
    attempts = int(attempts or 0)
    if attempts > AGENT_TRANSIENT_MODEL_RETRY_MAX:
        await log_event("agent", "error", f"agent_{agent_id}", "agent_transient_model_retry_exhausted",
                        f"task_{task_id}", {
                            "attempts": attempts,
                            "retry_max": AGENT_TRANSIENT_MODEL_RETRY_MAX,
                            "error": error[:500],
                        })
        return None

    ticket_id = (task_meta or {}).get("ticket_id")
    priority = None
    if ticket_id:
        ticket = await fetchrow("SELECT priority FROM tickets WHERE id = $1", ticket_id)
        priority = ticket.get("priority") if ticket else None
    priority_rank = _ticket_priority_rank(priority, (task_meta or {}).get("task_type"))
    delay_seconds = max(0, AGENT_TRANSIENT_MODEL_RETRY_DELAY_SECONDS)
    await execute(
        "UPDATE agent_tasks SET status = 'queued', output = $1, error_message = $2, "
        "pid = NULL, completed_at = NULL WHERE id = $3",
        _tail_text(result.get("stdout", "")),
        (
            f"Transient model/provider capacity error; retry {attempts}/"
            f"{AGENT_TRANSIENT_MODEL_RETRY_MAX} scheduled after {delay_seconds}s. "
            f"{error[:1200]}"
        ),
        task_id,
    )
    if ticket_id:
        await _add_agent_note(
            ticket_id,
            agent_id,
            task_id,
            "Agent provider retry scheduled",
            (
                f"Agent `{agent_id}` hit a transient model/provider capacity error on task `{task_id}`. "
                f"The runner preserved workspace progress and queued retry `{attempts}` of "
                f"`{AGENT_TRANSIENT_MODEL_RETRY_MAX}` after `{delay_seconds}` seconds."
            ),
            "agent-control-plane",
        )
    await log_event("agent", "warning", f"agent_{agent_id}", "agent_transient_model_retry_scheduled",
                    f"task_{task_id}", {
                        "attempts": attempts,
                        "retry_max": AGENT_TRANSIENT_MODEL_RETRY_MAX,
                        "delay_seconds": delay_seconds,
                        "priority_rank": priority_rank,
                        "error": error[:500],
                    })
    asyncio.create_task(
        _requeue_transient_model_retry(priority_rank, work_dir, prompt, task_id, agent_id, delay_seconds)
    )
    return {"status": "scheduled", "attempts": attempts, "delay_seconds": delay_seconds}


async def _record_model_turn_event(action, task_id, agent_id, details=None):
    """Record model turn timing in both operator-facing logs."""
    payload = {
        "task_id": task_id,
        "agent_id": agent_id,
        **(details or {}),
    }
    try:
        await log_event(
            "agent",
            "info",
            f"agent_{agent_id}" if agent_id else "agent-runner",
            action,
            f"task_{task_id}",
            payload,
        )
        await execute(
            "INSERT INTO audit_log (actor, action, target, details) VALUES ($1, $2, $3, $4)",
            f"agent_{agent_id}" if agent_id else "agent-runner",
            action,
            f"task_{task_id}",
            json.dumps(payload, default=str),
        )
    except Exception:
        pass


def _tail_text(text, limit=12000):
    if not text:
        return ""
    return text[-limit:]


def _parse_stream_result(output):
    """Extract the final Claude Code stream-json result, when present."""
    if not output:
        return ""
    result = ""
    for line in output.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "result":
            result = event.get("result") or ""
    return result


async def _stream_reader(stream, label, output_path, task_id, agent_id, chunks, activity=None):
    """Stream subprocess output to disk and periodically mirror a tail to DB."""
    last_db_update = 0.0
    with open(output_path, "a", encoding="utf-8", errors="replace") as f:
        while True:
            line = await stream.readline()
            if not line:
                break
            if activity is not None:
                activity["last_output_at"] = time.monotonic()
            text = line.decode("utf-8", errors="replace")
            if activity is not None and label == "stdout":
                try:
                    event = json.loads(text)
                except json.JSONDecodeError:
                    event = {}
                if event.get("type") == "assistant":
                    turn_index = activity.get("model_turn_index") or 1
                    started_at = activity.get("model_turn_started_at")
                    duration = None
                    if activity.get("model_turn_started_monotonic"):
                        duration = round(time.monotonic() - activity["model_turn_started_monotonic"], 3)
                    content = ((event.get("message") or {}).get("content") or [])
                    has_tool_use = any(
                        isinstance(item, dict) and item.get("type") == "tool_use"
                        for item in content
                    )
                    await _record_model_turn_event(
                        "agent_model_turn_finished",
                        task_id,
                        agent_id,
                        {
                            "turn_index": turn_index,
                            "turn_started_at": started_at,
                            "duration_seconds": duration,
                            "stop_reason": (event.get("message") or {}).get("stop_reason"),
                            "has_tool_use": has_tool_use,
                            "session_id": event.get("session_id"),
                            "uuid": event.get("uuid"),
                        },
                    )
                    activity["model_turn_open"] = False
                    if (event.get("message") or {}).get("stop_reason") == "tool_use" and not has_tool_use:
                        activity["malformed_tool_use_at"] = time.monotonic()
                    elif has_tool_use or event.get("type") == "user":
                        activity.pop("malformed_tool_use_at", None)
                elif event.get("type") == "user":
                    activity.pop("malformed_tool_use_at", None)
                    activity["model_turn_index"] = int(activity.get("model_turn_index") or 1) + 1
                    activity["model_turn_started_at"] = datetime.now().isoformat()
                    activity["model_turn_started_monotonic"] = time.monotonic()
                    activity["model_turn_open"] = True
                    await _record_model_turn_event(
                        "agent_model_turn_started",
                        task_id,
                        agent_id,
                        {
                            "turn_index": activity["model_turn_index"],
                            "trigger": "tool_result_or_user_event",
                            "session_id": event.get("session_id"),
                            "uuid": event.get("uuid"),
                        },
                    )
            rendered = text if label == "stdout" else f"[stderr] {text}"
            f.write(rendered)
            f.flush()
            chunks.append(rendered)

            progress = 5
            if label == "stdout":
                progress = _progress_from_stream_event(text)

            now = time.monotonic()
            if now - last_db_update >= 2.0:
                last_db_update = now
                tail = _tail_text("".join(chunks))
                await execute(
                    "UPDATE agent_tasks SET output = $1, progress_pct = GREATEST(progress_pct, $2) WHERE id = $3",
                    tail, progress, task_id,
                )
                await execute(
                    "UPDATE agents SET heartbeat = NOW() WHERE id = $1",
                    agent_id,
                )


def _progress_from_stream_event(line):
    """Map Claude Code stream-json events to coarse dashboard progress."""
    try:
        event = json.loads(line)
    except json.JSONDecodeError:
        return 10

    event_type = event.get("type")
    subtype = event.get("subtype")
    if event_type == "system" and subtype == "init":
        return 10
    if event_type == "assistant":
        return 40
    if event_type == "user":
        return 45
    if event_type == "result":
        return 95
    return 15


async def _terminate_after_no_output(process, stall_seconds, activity, state):
    if stall_seconds <= 0:
        return
    while process.returncode is None:
        await asyncio.sleep(min(30, max(1, stall_seconds / 10)))
        if process.returncode is not None:
            return
        malformed_at = activity.get("malformed_tool_use_at")
        if malformed_at and time.monotonic() - malformed_at >= min(stall_seconds, 90):
            idle_seconds = time.monotonic() - malformed_at
            state["stalled"] = True
            state["reason"] = (
                f"Agent emitted stop_reason=tool_use without an executable tool payload "
                f"and made no tool progress for {int(idle_seconds)} seconds; "
                "runner stopped the process to prevent a silent model/harness hang."
            )
            try:
                process.terminate()
                for _ in range(5):
                    await asyncio.sleep(1)
                    if process.returncode is not None:
                        return
                if process.returncode is None:
                    process.kill()
            except ProcessLookupError:
                return
            return
        idle_seconds = time.monotonic() - activity.get("last_output_at", time.monotonic())
        if idle_seconds < stall_seconds:
            continue
        state["stalled"] = True
        state["reason"] = (
            f"Agent produced no output for {int(idle_seconds)} seconds; "
            "runner marked it stalled and stopped the process to prevent a silent harness/model hang."
        )
        try:
            process.terminate()
            for _ in range(5):
                await asyncio.sleep(1)
                if process.returncode is not None:
                    return
            if process.returncode is None:
                process.kill()
        except ProcessLookupError:
            return
        return


async def _terminate_after_blocking_checkpoint(process, work_dir, activity, state, poll_seconds=5, grace_seconds=5):
    while process.returncode is None:
        await asyncio.sleep(poll_seconds)
        if process.returncode is not None:
            return
        checkpoint = _read_checkpoint_sync(work_dir)
        if not _checkpoint_blocks_completion(checkpoint):
            continue
        state["checkpoint"] = checkpoint
        state["reason"] = (
            "Agent wrote a durable wait checkpoint; runner stopped the owned "
            "harness process so approval/resume handling can continue."
        )
        activity["last_output_at"] = time.monotonic()
        try:
            process.terminate()
            for _ in range(max(1, int(grace_seconds))):
                await asyncio.sleep(1)
                if process.returncode is not None:
                    return
            if process.returncode is None:
                process.kill()
        except ProcessLookupError:
            return
        return


def _write_checkpoint(work_dir, task_id, step, status, output, progress_pct):
    checkpoint_path = os.path.join(work_dir, "checkpoint.json")
    with open(checkpoint_path, "w", encoding="utf-8") as f:
        json.dump({
            "task_id": task_id,
            "step": step,
            "status": status,
            "output": output,
            "progress_pct": progress_pct,
            "timestamp": datetime.now().isoformat(),
        }, f)


def _read_checkpoint_sync(work_dir):
    checkpoint_path = os.path.join(work_dir, "checkpoint.json")
    try:
        with open(checkpoint_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None


def _append_checkpoint(existing, checkpoint):
    if not checkpoint:
        return existing
    checkpoints = existing or []
    if isinstance(checkpoints, str):
        try:
            checkpoints = json.loads(checkpoints)
        except json.JSONDecodeError:
            checkpoints = []
    item = {
        "step": checkpoint.get("step", "unknown"),
        "status": checkpoint.get("status", "running"),
        "output": (checkpoint.get("output") or "")[:500],
        "timestamp": checkpoint.get("timestamp", datetime.now().isoformat()),
    }
    if not checkpoints or checkpoints[-1].get("step") != item["step"] or checkpoints[-1].get("status") != item["status"]:
        checkpoints.append(item)
    else:
        checkpoints[-1].update(item)
    return checkpoints


def _checkpoint_blocks_completion(checkpoint):
    """Return True when an agent intentionally stopped at a durable wait gate."""
    if not checkpoint:
        return False
    status = str(checkpoint.get("status") or "").strip().lower()
    step = str(checkpoint.get("step") or "").strip().lower()
    try:
        progress = int(checkpoint.get("progress_pct") or 0)
    except (TypeError, ValueError):
        progress = 0
    if progress >= 100 or status in ("done", "completed"):
        return False
    waiting_markers = (
        "waiting_for_",
        "pending_approval",
        "pending_access",
        "blocked",
        "access_denied",
        "needs_access",
    )
    return status.startswith(waiting_markers) or step.startswith(waiting_markers)


def _blocked_task_status(checkpoint):
    status = str((checkpoint or {}).get("status") or "").strip().lower()
    if "access" in status:
        return "awaiting_access"
    if "approval" in status:
        return "pending_approval"
    if "user" in status:
        return "awaiting_user_response"
    return "blocked"


async def _gate_state_for_wait(agent_id, ticket_id):
    if not agent_id or not ticket_id:
        return {"pending": [], "approved": [], "completed": [], "rejected": []}
    rows = await fetchall("""
        SELECT id, status, action, target, approved_at, requested_at
        FROM change_requests
        WHERE ticket_id = $1
          AND (agent_id = $2 OR agent_id IS NULL)
          AND status IN ('pending', 'approved', 'completed', 'rejected')
        ORDER BY requested_at DESC
        LIMIT 20
    """, ticket_id, agent_id)
    state = {"pending": [], "approved": [], "completed": [], "rejected": []}
    for row in rows or []:
        status = str(row.get("status") or "").lower()
        if status in state:
            state[status].append(row)
    return state


def _wait_checkpoint_obsolete(checkpoint, gate_state):
    if not _checkpoint_blocks_completion(checkpoint):
        return False
    if gate_state.get("pending"):
        return False
    return bool(gate_state.get("approved") or gate_state.get("completed"))


async def _spawn_obsolete_wait_continuation(agent_id, task_id, task_meta, checkpoint, gate_state, prompt):
    ticket_id = (task_meta or {}).get("ticket_id")
    if not ticket_id:
        return {"status": "skipped", "reason": "missing_ticket_id"}
    active_ticket_agent = await fetchrow("""
        SELECT a.id, a.last_task_id
        FROM agents a
        LEFT JOIN agent_tasks at ON at.id = a.last_task_id
        WHERE a.ticket_id = $1
          AND a.id <> $2
          AND (
              a.status IN ('spawned', 'running', 'working')
              OR at.status IN ('queued', 'running')
          )
        ORDER BY a.started_at DESC NULLS LAST, a.id DESC
        LIMIT 1
    """, ticket_id, agent_id)
    if active_ticket_agent:
        return {
            "status": "already_active_ticket",
            "agent_id": active_ticket_agent["id"],
            "task_id": active_ticket_agent.get("last_task_id"),
        }

    agent = await fetchrow("SELECT model, selected_model FROM agents WHERE id = $1", agent_id)
    approved_ids = [row["id"] for row in gate_state.get("approved", [])]
    completed_ids = [row["id"] for row in gate_state.get("completed", [])]
    continuation = "\n\nApproval/wait-state correction:\n"
    continuation += (
        f"- Source agent {agent_id} wrote wait checkpoint `{(checkpoint or {}).get('step', 'unknown')}` "
        "after the relevant gate had already been approved or completed.\n"
    )
    continuation += f"- Approved change IDs: {approved_ids or 'none'}; completed change IDs: {completed_ids or 'none'}.\n"
    continuation += (
        "- Re-read the ticket, change request statuses, access request status, and approval notes now. "
        "Do not request the same access again unless a fresh permission wall is proven. "
        "Continue the original ticket objective and write an audit note explaining the stale wait recovery.\n"
    )
    try:
        from services import access_control
        actor_context = await access_control.load_agent_subject(agent_id)
    except Exception:
        actor_context = {
            "identity": {"username": f"agent_{agent_id}"},
            "roles": ["agent-operator"],
            "capabilities": ["agents:spawn", "tickets:read", "changes:request"],
            "scopes": [],
            "max_classification": "internal",
        }
    result = await spawn_agent(
        ticket_id,
        (agent or {}).get("selected_model") or (agent or {}).get("model") or "deepseek/deepseek-v4-flash",
        (prompt or "") + continuation,
        (task_meta or {}).get("task_type") or "ticket_resolution",
        actor_context=actor_context,
    )
    await _add_agent_note(
        ticket_id,
        agent_id,
        task_id,
        "Stale wait checkpoint recovered",
        (
            f"Agent `{agent_id}` wrote wait checkpoint `{(checkpoint or {}).get('step', 'unknown')}` "
            "after the approval/access gate was already open or completed. "
            f"Continuation agent `{result.get('agent_id')}` / task `{result.get('task_id')}` was queued to continue from current state."
        ),
        "agent-control-plane",
    )
    await log_event("agent", "warning", f"agent_{agent_id}", "agent_wait_checkpoint_obsolete",
                    f"task_{task_id}", {
                        "ticket_id": ticket_id,
                        "checkpoint": checkpoint,
                        "approved_change_ids": approved_ids,
                        "completed_change_ids": completed_ids,
                        "replacement_agent_id": result.get("agent_id"),
                        "replacement_task_id": result.get("task_id"),
                    })
    return {"status": "continuation_spawned", **result}


def _loads(value, default):
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value


def _split_guard_paths(value):
    if isinstance(value, (list, tuple, set)):
        raw_items = value
    else:
        raw_items = str(value or "").split(",")
    return [str(item).strip() for item in raw_items if str(item).strip()]


def _ticket_priority_rank(priority, task_type="ticket_resolution"):
    """Return lower-is-more-urgent queue rank for agent scheduling."""
    normalized = str(priority or "").strip().upper()
    rank_map = {
        "P1": 0,
        "CRITICAL": 0,
        "EMERGENCY": 0,
        "1": 0,
        "P2": 1,
        "HIGH": 1,
        "2": 1,
        "P3": 2,
        "MEDIUM": 2,
        "NORMAL": 2,
        "3": 2,
        "P4": 3,
        "LOW": 3,
        "4": 3,
    }
    rank = rank_map.get(normalized, 2)
    if task_type in ("postmortem", "workflow_build", "workflow_rerun"):
        rank += 2
    return rank


def _ensure_queue_workers():
    """Start bounded priority queue workers for this event loop."""
    desired = max(1, int(MAX_CONCURRENT_AGENTS or 1))
    live = {task for task in _queue_workers if not task.done()}
    _queue_workers.clear()
    _queue_workers.update(live)
    while len(_queue_workers) < desired:
        task = asyncio.create_task(_agent_queue_worker())
        _queue_workers.add(task)


async def _agent_queue_worker():
    """Run queued agent tasks in priority order."""
    while True:
        priority_rank, sequence, work_dir, prompt, task_id, agent_id = await _agent_queue.get()
        try:
            await log_event("agent", "info", f"agent_{agent_id}", "agent_queue_dequeued",
                            f"task_{task_id}", {
                                "priority_rank": priority_rank,
                                "sequence": sequence,
                                "queued_depth": _agent_queue.qsize(),
                            })
            await _spawn_with_semaphore(work_dir, prompt, task_id, agent_id)
        finally:
            _agent_queue.task_done()


def _curl_guard_script(real_curl, blocked_paths=None, max_output_bytes=None, allowed_hosts=None):
    paths = blocked_paths if blocked_paths is not None else _split_guard_paths(AGENT_CURL_BLOCKED_PATHS)
    limit = int(max_output_bytes if max_output_bytes is not None else AGENT_CURL_MAX_OUTPUT_BYTES)
    hosts = _split_guard_paths(allowed_hosts if allowed_hosts is not None else AGENT_CURL_ALLOWED_HOSTS)
    return f"""#!/usr/bin/env python3
import os
import subprocess
import sys
import json
from urllib.parse import urlparse

REAL_CURL = {json.dumps(real_curl)}
BLOCKED_PATHS = {json.dumps(paths)}
ALLOWED_HOSTS = {json.dumps(hosts)}
MAX_OUTPUT_BYTES = {limit}
DASHBOARD_API_BASE = os.getenv("DASHBOARD_API_BASE", "http://localhost:8000").rstrip("/")
DASHBOARD_AGENT_SESSION_COOKIE = os.getenv("DASHBOARD_AGENT_SESSION_COOKIE", "")

args = sys.argv[1:]
for blocked in BLOCKED_PATHS:
    if blocked and any(blocked in arg for arg in args):
        sys.stderr.write("[curl-guard] blocked broad dashboard endpoint: " + blocked + "\\n")
        sys.stderr.write("[curl-guard] use a bounded ticket/evidence endpoint instead.\\n")
        sys.exit(64)

def is_dashboard_url(value):
    if not isinstance(value, str) or not value.startswith(("http://", "https://")):
        return False
    if DASHBOARD_API_BASE and value.startswith(DASHBOARD_API_BASE):
        return True
    parsed = urlparse(value)
    return parsed.hostname in ("localhost", "127.0.0.1") and str(parsed.port or "") == "8000"

def host_allowed(hostname):
    if not hostname:
        return True
    host = str(hostname).lower().strip("[]")
    for pattern in ALLOWED_HOSTS:
        pattern = str(pattern).lower().strip()
        if not pattern:
            continue
        if pattern.startswith("*.") and host.endswith(pattern[1:]):
            return True
        if host == pattern:
            return True
    return False

for value in args:
    if not isinstance(value, str) or not value.startswith(("http://", "https://")):
        continue
    if is_dashboard_url(value):
        continue
    parsed = urlparse(value)
    if not host_allowed(parsed.hostname):
        sys.stderr.write("[curl-guard] blocked direct retrieval of untrusted external URL: " + value + "\\n")
        sys.stderr.write("[curl-guard] use passive reputation, mail/proxy/SIEM evidence, VirusTotal/urlscan-style adapters, or an approved isolated detonation service instead.\\n")
        sys.exit(65)

def has_auth_header(values):
    lowered = [str(item).lower() for item in values]
    joined = "\\n".join(lowered)
    return (
        "dashboard_session=" in joined
        or "x-dashboard-service-token" in joined
        or "x-dashboard-auth-secret" in joined
        or "cookie:" in joined
    )

def load_workspace_cookie():
    if DASHBOARD_AGENT_SESSION_COOKIE:
        return DASHBOARD_AGENT_SESSION_COOKIE
    current = os.getcwd()
    for _ in range(8):
        candidate = os.path.join(current, "dashboard_auth.json")
        try:
            with open(candidate, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            cookie = payload.get("cookie")
            if cookie:
                return cookie
        except (OSError, ValueError, TypeError):
            pass
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    return ""

session_cookie = load_workspace_cookie()
if session_cookie and any(is_dashboard_url(arg) for arg in args) and not has_auth_header(args):
    args = ["-H", "Cookie: dashboard_session=" + session_cookie] + args

try:
    proc = subprocess.Popen([REAL_CURL] + args, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    stdout, stderr = proc.communicate()
except OSError as exc:
    sys.stderr.write("[curl-guard] failed to execute real curl: " + str(exc) + "\\n")
    sys.exit(127)

def emit(stream, data, label):
    if MAX_OUTPUT_BYTES > 0 and len(data) > MAX_OUTPUT_BYTES:
        stream.write(data[:MAX_OUTPUT_BYTES])
        sys.stderr.buffer.write(
            ("\\n[curl-guard] " + label + " truncated from " + str(len(data)) +
             " bytes to " + str(MAX_OUTPUT_BYTES) + " bytes. Use a bounded API query.\\n").encode("utf-8")
        )
        return
    stream.write(data)

emit(sys.stdout.buffer, stdout, "stdout")
emit(sys.stderr.buffer, stderr, "stderr")
sys.exit(proc.returncode)
"""


def _resolve_real_curl():
    for candidate in ("/usr/bin/curl", "/bin/curl"):
        if os.path.exists(candidate):
            return candidate
    return shutil.which("curl") or "/usr/bin/curl"


def _write_global_curl_guard(real_curl=None, blocked_paths=None, max_output_bytes=None, allowed_hosts=None):
    """Install a container-level curl guard for harnesses that reset PATH.

    The guard remains inert unless the current working directory belongs to an
    agent workspace containing dashboard_auth.json and the URL targets the
    dashboard API.
    """
    if not AGENT_CURL_GUARD_ENABLED:
        return None
    guard_path = "/usr/local/bin/curl"
    try:
        with open(guard_path, "w", encoding="utf-8") as f:
            f.write(_curl_guard_script(real_curl or _resolve_real_curl(), blocked_paths, max_output_bytes, allowed_hosts))
        os.chmod(guard_path, 0o755)
        return guard_path
    except OSError:
        return None


def _write_curl_guard(work_dir, real_curl=None, blocked_paths=None, max_output_bytes=None, allowed_hosts=None):
    """Install a per-agent curl wrapper that blocks broad context pulls."""
    if not AGENT_CURL_GUARD_ENABLED:
        return None
    resolved_curl = real_curl or _resolve_real_curl()
    bin_dir = os.path.join(work_dir, "bin")
    os.makedirs(bin_dir, exist_ok=True)
    guard_path = os.path.join(bin_dir, "curl")
    with open(guard_path, "w", encoding="utf-8") as f:
        f.write(_curl_guard_script(resolved_curl, blocked_paths, max_output_bytes, allowed_hosts))
    os.chmod(guard_path, 0o755)
    return guard_path


def _chown_agent_tree(path, uid=None, gid=None):
    """Make a provisioned workspace writable by the least-privilege harness user."""
    if uid is None or gid is None:
        return
    try:
        os.chown(path, uid, gid)
        for root, dirs, files in os.walk(path):
            for name in dirs:
                os.chown(os.path.join(root, name), uid, gid)
            for name in files:
                os.chown(os.path.join(root, name), uid, gid)
    except (AttributeError, OSError):
        return


def _ensure_harness_workspace_ownership(work_dir):
    if AGENT_HARNESS != "hermes":
        return
    run_uid = _env_int("HERMES_RUN_AS_UID", 1000)
    run_gid = _env_int("HERMES_RUN_AS_GID", run_uid)
    if run_uid <= 0:
        return
    _chown_agent_tree(work_dir, run_uid, run_gid)


def _apply_agent_path_guards(env, work_dir):
    guard_bin = os.path.join(work_dir, "bin")
    if os.path.exists(os.path.join(guard_bin, "curl")):
        env["PATH"] = guard_bin + os.pathsep + env.get("PATH", "")
        env["AGENT_CURL_GUARD_ENABLED"] = "1"
        env["AGENT_CURL_MAX_OUTPUT_BYTES"] = str(AGENT_CURL_MAX_OUTPUT_BYTES)
        env["AGENT_CURL_BLOCKED_PATHS"] = AGENT_CURL_BLOCKED_PATHS
        env["AGENT_NO_OUTPUT_STALL_SECONDS"] = str(AGENT_NO_OUTPUT_STALL_SECONDS)
        auth_path = os.path.join(work_dir, AGENT_DASHBOARD_SESSION_FILE)
        try:
            with open(auth_path, "r", encoding="utf-8") as f:
                auth_payload = json.load(f)
            if auth_payload.get("cookie"):
                env["DASHBOARD_AGENT_SESSION_COOKIE"] = auth_payload["cookie"]
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass
    return env


async def _add_agent_note(ticket_id, agent_id, task_id, title, body, source="agent-control-plane"):
    """Write a human-readable agent progress note to the canonical ticket."""
    if not ticket_id:
        return None
    text = f"{title}\n\n{body}".strip()
    note_id = await fetchval("""
        INSERT INTO ticket_notes (ticket_id, source, author, body, visibility)
        VALUES ($1, $2, $3, $4, 'internal')
        RETURNING id
    """, ticket_id, source, f"agent-{agent_id}" if agent_id else source, text)
    await execute("UPDATE tickets SET updated_at = NOW() WHERE id = $1", ticket_id)
    await log_event("ticket", "info", f"agent_{agent_id}" if agent_id else source,
                    "agent_progress_note_added", f"ticket_{ticket_id}", {
                        "note_id": note_id,
                        "agent_id": agent_id,
                        "task_id": task_id,
                        "title": title,
                    })
    return note_id


async def _close_provider_ticket_if_needed(ticket_id, agent_id, task_id, notes):
    """Best-effort provider close for explicit agent/operator close actions."""
    if not ticket_id:
        return {"status": "skipped", "reason": "missing_ticket_id"}
    ticket = await fetchrow(
        "SELECT provider, provider_ref, status FROM tickets WHERE id = $1",
        ticket_id,
    )
    if not ticket:
        return {"status": "skipped", "reason": "ticket_not_found"}
    provider = (ticket.get("provider") or "local").strip().lower()
    if provider != "itop" or not ticket.get("provider_ref"):
        return {"status": "skipped", "reason": f"provider_{provider or 'local'}"}
    try:
        from services.itop_sync import iTopProvider
        result = await iTopProvider().close_ticket(ticket_id, notes or "Resolved by SOC agent.")
        if result.get("error") and "Invalid stimulus" in str(result.get("error")):
            await asyncio.sleep(2)
            result = await iTopProvider().close_ticket(ticket_id, notes or "Resolved by SOC agent.")
    except Exception as exc:
        result = {"error": str(exc)}

    if result.get("error"):
        await log_event("sync", "warning", f"agent_{agent_id}", "provider_close_failed",
                        f"ticket_{ticket_id}", {"task_id": task_id, "error": result.get("error")})
        await _add_agent_note(
            ticket_id,
            agent_id,
            task_id,
            "Provider close failed",
            f"The explicit ticket close was recorded locally, but provider close failed: {result.get('error')}",
            source="agent-control-plane",
        )
    else:
        await log_event("sync", "info", f"agent_{agent_id}", "provider_close_complete",
                        f"ticket_{ticket_id}", {"task_id": task_id, "provider": provider, "result": result})
    return result


def _auto_complete_allowed(change):
    policy = _loads(change.get("approval_policy"), {})
    if not isinstance(policy, dict):
        return True
    if policy.get("auto_complete") is False:
        return False
    if policy.get("manual_completion_required") is True:
        return False
    return True


def _format_change_completion_result(change, task, checkpoint):
    checkpoints = _loads(task.get("checkpoints"), [])
    latest_checkpoint = checkpoint
    if not latest_checkpoint and checkpoints and isinstance(checkpoints[-1], dict):
        latest_checkpoint = checkpoints[-1]

    output = _parse_stream_result(task.get("output") or "")
    evidence = [
        "Control plane auto-completed this approved agent-linked change after verified agent task completion.",
        f"Change: {change.get('id')} - {change.get('action') or 'unspecified action'}",
        f"Target: {change.get('target') or 'unspecified target'}",
        f"Agent: {task.get('agent_id')}; task: {task.get('id')}; ticket: {task.get('ticket_id')}",
        f"Task status: {task.get('status')}; completed_at: {task.get('completed_at') or 'recorded by supervisor'}",
    ]
    if task.get("work_dir"):
        evidence.append(f"Work directory: {task.get('work_dir')}")
    if latest_checkpoint:
        evidence.append(
            "Final checkpoint: "
            f"{latest_checkpoint.get('step', 'unknown')} / {latest_checkpoint.get('status', 'unknown')} - "
            f"{(latest_checkpoint.get('output') or '')[:900]}"
        )
    if output:
        evidence.append(f"Task final response: {_tail_text(output, 700)}")
    return "\n".join(evidence)


async def _recent_manual_completion_skip(change_id, task_id, window_seconds=3600):
    return bool(await fetchval("""
        SELECT 1
        FROM event_log
        WHERE action = 'change_auto_complete_skipped'
          AND target = $1
          AND details->>'task_id' = $2
          AND created_at > NOW() - ($3::text || ' seconds')::interval
        LIMIT 1
    """, f"change_{change_id}", str(task_id), str(int(window_seconds))))


async def complete_approved_changes_for_task(agent_id, task_id, reason="agent_task_completed", checkpoint=None):
    """Advance approved agent-linked changes when a task has finished cleanly.

    Agents are still instructed to call the change completion API themselves.
    This supervisor path is the deterministic fallback for cases where the
    approved remediation finished but the final state transition was omitted.
    """
    task = await fetchrow("""
        SELECT id, agent_id, ticket_id, status, work_dir, output, checkpoints,
               completed_at, task_type
        FROM agent_tasks
        WHERE id = $1 AND agent_id = $2
    """, task_id, agent_id)
    if not task or task.get("status") != "completed":
        return {"completed": [], "skipped": [], "reason": "task_not_completed"}

    changes = await fetchall("""
        SELECT *
        FROM change_requests
        WHERE agent_id = $1
          AND status = 'approved'
          AND ($2::integer IS NULL OR ticket_id = $2 OR ticket_id IS NULL)
        ORDER BY approved_at NULLS LAST, requested_at
    """, agent_id, task.get("ticket_id"))

    completed = []
    skipped = []
    for change in changes or []:
        if not _auto_complete_allowed(change):
            skipped.append({"change_id": change["id"], "reason": "manual_completion_required"})
            if not await _recent_manual_completion_skip(change["id"], task_id):
                await log_event("change", "info", "agent-supervisor", "change_auto_complete_skipped",
                                f"change_{change['id']}", {
                                    "agent_id": agent_id,
                                    "task_id": task_id,
                                    "ticket_id": task.get("ticket_id"),
                                    "reason": "manual_completion_required",
                                })
            continue

        result = _format_change_completion_result(change, task, checkpoint)
        await execute("""
            UPDATE change_requests
            SET status = 'completed', result = $1
            WHERE id = $2 AND status = 'approved'
        """, result, change["id"])
        await execute("""
            INSERT INTO audit_log (actor, action, target, details)
            VALUES ($1, $2, $3, $4)
        """, "agent-supervisor", "change_auto_completed", f"change_{change['id']}", json.dumps({
            "change_id": change["id"],
            "agent_id": agent_id,
            "task_id": task_id,
            "ticket_id": task.get("ticket_id"),
            "reason": reason,
        }))
        await log_event("change", "info", "agent-supervisor", "change_auto_completed",
                        f"change_{change['id']}", {
                            "agent_id": agent_id,
                            "task_id": task_id,
                            "ticket_id": task.get("ticket_id"),
                            "reason": reason,
                        })
        await _add_agent_note(
            task.get("ticket_id"),
            agent_id,
            task_id,
            f"Change {change['id']} completed",
            (
                f"The approved change `{change.get('action') or 'unspecified action'}` "
                f"on `{change.get('target') or 'unspecified target'}` was moved to completed "
                f"after the agent task finished and the control plane verified completion evidence."
            ),
            "agent-supervisor",
        )
        completed.append(change["id"])

    return {"completed": completed, "skipped": skipped}


async def _detect_completed_ticket_resolution(task_id, agent_id):
    task = await fetchrow("""
        SELECT id, agent_id, ticket_id, task_type, started_at, created_at
        FROM agent_tasks
        WHERE id = $1 AND agent_id = $2
    """, task_id, agent_id)
    if not task or task.get("task_type") != "ticket_resolution" or not task.get("ticket_id"):
        return None

    ticket_id = task["ticket_id"]
    started_at = task.get("started_at") or task.get("created_at")
    evidence = await fetchrow("""
        SELECT
            (SELECT status FROM tickets WHERE id = $1) AS ticket_status,
            (SELECT COUNT(*)
             FROM change_requests
             WHERE ticket_id = $1 AND status = 'completed') AS completed_changes,
            (SELECT COUNT(*)
             FROM change_requests
             WHERE ticket_id = $1
               AND status NOT IN ('completed', 'rejected', 'cancelled')) AS open_changes,
            (SELECT COUNT(*)
             FROM ticket_notes
             WHERE ticket_id = $1
               AND created_at >= COALESCE($2, created_at)
               AND (
                   source IN ('soc-agent', 'dashboard', 'agent-control-plane', 'agent')
                   OR source LIKE 'agent%'
                   OR author = ('agent-' || $4::text)
               )
               AND (
                   body ILIKE '%Resolution%'
                   OR body ILIKE '%Residual Risk%'
                   OR body ILIKE '%complete%'
               )) AS final_notes,
            (SELECT COUNT(*)
             FROM postmortems
             WHERE ticket_id = $1
               AND (task_id = $3 OR created_at >= COALESCE($2, created_at))) AS postmortems
            ,
            (SELECT COUNT(*)
             FROM postmortems
             WHERE ticket_id = $1
               AND status = 'promoted'
               AND (task_id = $3 OR created_at >= COALESCE($2, created_at))) AS promoted_postmortems
    """, ticket_id, started_at, task_id, str(agent_id))
    if not evidence:
        return None

    ticket_status = str(evidence.get("ticket_status") or "").strip().lower()
    completed_changes = int(evidence.get("completed_changes") or 0)
    open_changes = int(evidence.get("open_changes") or 0)
    final_notes = int(evidence.get("final_notes") or 0)
    postmortems = int(evidence.get("postmortems") or 0)
    promoted_postmortems = int(evidence.get("promoted_postmortems") or 0)
    if final_notes > 0 and open_changes == 0 and (completed_changes > 0 or postmortems > 0):
        return {
            "ticket_id": ticket_id,
            "ticket_status": ticket_status,
            "completed_changes": completed_changes,
            "open_changes": open_changes,
            "final_notes": final_notes,
            "postmortems": postmortems,
            "promoted_postmortems": promoted_postmortems,
        }
    return None


def _can_autoresolve_from_terminal_evidence(evidence):
    """Allow a narrow final status recovery after the agent did all gated work.

    This does not turn generic task completion into ticket closure. It only
    applies when the dashboard already has no open gates, final agent evidence,
    completed approval work, and a promoted postmortem/workflow asset. That is
    the exact failure mode where a local model completed the workflow learning
    step but hung before the explicit final `/status resolved` call.
    """
    if not evidence:
        return False
    ticket_status = str(evidence.get("ticket_status") or "").strip().lower()
    if ticket_status in ("closed", "resolved", "closed/resolved", "implemented"):
        return True
    return (
        ticket_status in ("new", "assigned", "in_progress", "awaiting_user_response", "pending_approval", "awaiting_access", "blocked")
        and int(evidence.get("open_changes") or 0) == 0
        and int(evidence.get("completed_changes") or 0) > 0
        and int(evidence.get("final_notes") or 0) > 0
        and int(evidence.get("promoted_postmortems") or 0) > 0
    )


TERMINAL_TICKET_STATUSES = {"closed", "resolved", "closed/resolved", "implemented"}
WAIT_TICKET_STATUSES = {"awaiting_user_response", "pending_approval", "awaiting_access", "blocked"}


def _done_checkpoint_ready_for_close(checkpoint):
    if not checkpoint:
        return False
    status = str(checkpoint.get("status") or "").strip().lower()
    if status not in ("done", "completed"):
        return False
    try:
        progress = int(checkpoint.get("progress_pct") or 0)
    except (TypeError, ValueError):
        progress = 0
    return progress >= 100


def _prompt_requires_agent_closure(prompt):
    text = str(prompt or "").lower()
    if not text:
        return False
    markers = (
        "resolve the ticket",
        "close the ticket",
        "resolved/closed",
        "/status",
        "agent-initiated closure",
        "close_provider",
    )
    return any(marker in text for marker in markers)


async def recover_done_checkpoint_ticket_status(agent_id, task_id, checkpoint, reason="done_checkpoint_recovery"):
    """Close a ticket from a successful done checkpoint when closure was required.

    This is intentionally narrower than generic task completion. It only runs
    after the runner has persisted task success and an agent completion note, and
    it still requires explicit prompt closure intent, no open gates, and final
    agent evidence before touching ticket/provider state.
    """
    if not _done_checkpoint_ready_for_close(checkpoint):
        return {"status": "skipped", "reason": "checkpoint_not_terminal"}

    task = await fetchrow("""
        SELECT t.id, t.agent_id, t.ticket_id, t.task_type, t.prompt,
               t.started_at, t.created_at, tk.status AS ticket_status,
               tk.provider, tk.provider_ref
        FROM agent_tasks t
        JOIN tickets tk ON tk.id = t.ticket_id
        WHERE t.id = $1 AND t.agent_id = $2
    """, task_id, agent_id)
    if not task:
        return {"status": "skipped", "reason": "missing_task"}
    if task.get("task_type") != "ticket_resolution":
        return {"status": "skipped", "reason": "not_ticket_resolution"}
    ticket_id = task.get("ticket_id")
    ticket_status = str(task.get("ticket_status") or "").strip().lower()
    if ticket_status in TERMINAL_TICKET_STATUSES:
        return {"status": "skipped", "reason": "ticket_already_terminal", "ticket_status": ticket_status}
    if ticket_status in WAIT_TICKET_STATUSES:
        return {"status": "skipped", "reason": f"ticket_waiting_{ticket_status}", "ticket_status": ticket_status}
    if not _prompt_requires_agent_closure(task.get("prompt")):
        return {"status": "skipped", "reason": "closure_not_required_by_prompt"}

    started_at = task.get("started_at") or task.get("created_at")
    evidence = await fetchrow("""
        SELECT
            (SELECT COUNT(*)
             FROM change_requests
             WHERE ticket_id = $1
               AND status NOT IN ('completed', 'rejected', 'cancelled')) AS open_changes,
            (SELECT COUNT(*)
             FROM access_requests
             WHERE parent_ticket_id = $1
               AND status NOT IN ('granted', 'rejected', 'cancelled')) AS open_access_requests,
            (SELECT COUNT(*)
             FROM ticket_notes
             WHERE ticket_id = $1
               AND created_at >= COALESCE($2, created_at)
               AND (
                   source IN ('soc-agent', 'agent-control-plane', 'agent-supervisor', 'agent')
                   OR source LIKE 'agent%'
                   OR author = ('agent-' || $3::text)
               )
               AND (
                   body ILIKE '%Resolution%'
                   OR body ILIKE '%Residual Risk%'
                   OR body ILIKE '%complete%'
                   OR body ILIKE '%resolved%'
                   OR body ILIKE '%done%'
               )) AS final_notes
    """, ticket_id, started_at, str(agent_id))
    if not evidence:
        return {"status": "skipped", "reason": "missing_evidence"}
    open_changes = int(evidence.get("open_changes") or 0)
    open_access_requests = int(evidence.get("open_access_requests") or 0)
    final_notes = int(evidence.get("final_notes") or 0)
    if open_changes or open_access_requests:
        return {
            "status": "skipped",
            "reason": "open_gates",
            "open_changes": open_changes,
            "open_access_requests": open_access_requests,
        }
    if final_notes <= 0:
        return {"status": "skipped", "reason": "missing_final_agent_note"}

    summary = (
        f"Agent `{agent_id}` wrote a terminal `done` checkpoint at 100% and final evidence, "
        "and the ticket prompt required closure. The supervisor resolved the ticket because "
        "the agent exited before making the explicit status call."
    )
    await execute(
        "UPDATE tickets SET status = 'resolved', updated_at = NOW() WHERE id = $1",
        ticket_id,
    )
    await _add_agent_note(
        ticket_id,
        agent_id,
        task_id,
        "Ticket resolved by done checkpoint recovery",
        summary,
        "agent-supervisor",
    )
    provider_result = await _close_provider_ticket_if_needed(
        ticket_id,
        agent_id,
        task_id,
        summary,
    )
    await log_event("ticket", "warning", f"agent_{agent_id}",
                    "ticket_status_recovered_from_done_checkpoint",
                    f"ticket_{ticket_id}", {
                        "task_id": task_id,
                        "previous_status": ticket_status,
                        "new_status": "resolved",
                        "reason": reason,
                        "provider": task.get("provider"),
                        "provider_result": provider_result,
                        "evidence": {
                            "open_changes": open_changes,
                            "open_access_requests": open_access_requests,
                            "final_notes": final_notes,
                        },
                    })
    return {
        "status": "recovered",
        "ticket_id": ticket_id,
        "previous_status": ticket_status,
        "new_status": "resolved",
        "provider_result": provider_result,
        "evidence": {
            "open_changes": open_changes,
            "open_access_requests": open_access_requests,
            "final_notes": final_notes,
        },
    }


async def recover_completed_ticket_resolution(agent_id, task_id, reason="terminal_evidence_recovered"):
    """Finalize a running ticket task when dashboard evidence proves completion.

    This is deliberately narrow: only ticket-resolution tasks with a final agent
    note, no open gates, and completed change/postmortem evidence qualify. It
    lets the auditor free the local-model lane if the harness keeps running
    after the ticket is already closed.
    """
    task = await fetchrow("""
        SELECT id, agent_id, ticket_id, task_type, status, pid, output
        FROM agent_tasks
        WHERE id = $1 AND agent_id = $2
    """, task_id, agent_id)
    if not task:
        return {"status": "skipped", "reason": "missing_task"}
    if task.get("task_type") != "ticket_resolution":
        return {"status": "skipped", "reason": "not_ticket_resolution"}
    if task.get("status") not in ("queued", "running"):
        return {"status": "skipped", "reason": f"task_status_{task.get('status')}"}

    evidence = await _detect_completed_ticket_resolution(task_id, agent_id)
    if not evidence:
        return {"status": "skipped", "reason": "insufficient_terminal_evidence"}
    if evidence.get("ticket_status") not in ("closed", "resolved"):
        if not _can_autoresolve_from_terminal_evidence(evidence):
            return {
                "status": "skipped",
                "reason": "ticket_not_closed",
                "evidence": evidence,
            }
        await execute(
            "UPDATE tickets SET status = 'resolved', updated_at = NOW() WHERE id = $1",
            evidence["ticket_id"],
        )
        await _add_agent_note(
            evidence["ticket_id"],
            agent_id,
            task_id,
            "Ticket resolved by terminal evidence recovery",
            (
                f"Agent `{agent_id}` completed all approval gates, wrote final completion evidence, "
                "and promoted the postmortem/workflow assets, but the harness did not reach the "
                "explicit final ticket status call. The supervisor marked the ticket resolved from "
                "that persisted evidence without exposing secrets or expanding permissions."
            ),
            "agent-supervisor",
        )
        await log_event("ticket", "warning", f"agent_{agent_id}",
                        "ticket_status_recovered_from_terminal_evidence",
                        f"ticket_{evidence['ticket_id']}", {
                            "task_id": task_id,
                            "previous_status": evidence.get("ticket_status"),
                            "new_status": "resolved",
                            "reason": reason,
                            "evidence": evidence,
                        })
        evidence["ticket_status"] = "resolved"
        evidence["auto_resolved"] = True

    summary = (
        "Recovered terminal completion from dashboard evidence: "
        f"ticket status `{evidence['ticket_status']}`, "
        f"{evidence['completed_changes']} completed change gates, "
        f"{evidence['final_notes']} final notes, and "
        f"{evidence['postmortems']} postmortems."
    )
    await execute(
        "UPDATE agent_tasks SET status = 'completed', output = $1, error_message = NULL, "
        "completed_at = NOW(), progress_pct = 100 WHERE id = $2",
        summary,
        task_id,
    )
    await execute(
        "UPDATE agents SET status = 'finished', heartbeat = NOW(), error_message = NULL, finished_at = NOW() WHERE id = $1",
        agent_id,
    )
    await log_event("agent", "warning", f"agent_{agent_id}", "agent_terminal_completion_recovered",
                    f"task_{task_id}", {
                        "reason": reason,
                        "evidence": evidence,
                    })
    await _add_agent_note(
        evidence["ticket_id"],
        agent_id,
        task_id,
        "Agent completed with terminal evidence recovery",
        (
            f"Agent `{agent_id}` had already completed ticket work but left the task running. "
            f"The supervisor finalized task `{task_id}` from persisted evidence. {summary}"
        ),
        "agent-control-plane",
    )

    pid = task.get("pid")
    if pid:
        if task_id in _active_processes:
            proc = _active_processes[task_id]
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                proc.kill()
        else:
            try:
                os.kill(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                pass
    _active_processes.pop(task_id, None)
    return {"status": "recovered", "task_id": task_id, "agent_id": agent_id, "evidence": evidence}


async def _mirror_checkpoint_to_task(task_id, agent_id, work_dir):
    checkpoint = _read_checkpoint_sync(work_dir)
    if not checkpoint:
        return None
    task = await fetchrow("SELECT checkpoints FROM agent_tasks WHERE id = $1", task_id)
    checkpoints = _append_checkpoint(task.get("checkpoints") if task else [], checkpoint)
    await execute(
        "UPDATE agent_tasks SET checkpoints = $1, progress_pct = GREATEST(progress_pct, $2) WHERE id = $3",
        json.dumps(checkpoints),
        int(checkpoint.get("progress_pct") or 0),
        task_id,
    )
    await execute("UPDATE agents SET heartbeat = NOW() WHERE id = $1", agent_id)
    return checkpoint


def _load_model_config():
    """Load model config from JSON file.

    Secrets and auth tokens are never stored here. Claude Code should use the
    credentials already available to the selected harness/container.
    """
    global _model_config
    if _model_config is None:
        try:
            with open(MODEL_CONFIG_PATH, "r") as f:
                _model_config = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            _model_config = {
                "models": ["deepseek/deepseek-v4-flash"],
                "default": "deepseek/deepseek-v4-flash",
            }
    return _model_config


def _build_agent_context_md(ticket, skills, prompt):
    """Build workspace instructions for the spawned agent."""
    skills_section = ""
    if skills:
        skills_lines = []
        for s in skills:
            skills_lines.append(f"- **{s['name']}**: {s.get('description', '')}")
        skills_section = "\n".join(skills_lines)
    else:
        skills_section = "- server-manager (SSH client)\n- web-research (SearXNG)\n- MemPalace MCP"

    return f"""# Agentic Operations Agent - Ticket Resolution

You are an Agentic Operations worker assigned to resolve the following ticket.

## Ticket Context
- Title: {ticket.get('title', 'N/A')}
- Description: {ticket.get('description', 'N/A')}
- Class: {ticket.get('itop_class', 'N/A')}
- Priority: {ticket.get('priority', 'N/A')}
- Status: {ticket.get('status', 'N/A')}
- iTop Ref: {ticket.get('itop_ref', 'N/A')}

## Available Skills
{skills_section}

## Dashboard API
Use the canonical dashboard API for ticket context, notes, approvals, postmortems, and workflows:
- Base URL inside this runner: `{DASHBOARD_API_BASE}`
- Authentication is attached automatically by the per-agent curl guard as a
  signed, scoped session cookie. Do not print, copy, store, or manually add
  dashboard auth material; use `curl` normally against the dashboard API.
- Preferred bounded evidence: `GET /api/postmortems/evidence/{ticket.get('id', '{ticket_id}')}?task_log_lines=0&max_notes=8&max_articles=1&max_audit=6`
  - This includes relevant active/tested/approved reusable workflows and knowledge articles; follow matching active/approved workflows first and note any deviation.
- Ticket detail: `GET /api/tickets/{ticket.get('id', '{ticket_id}')}`
- Broader ticket context only when needed: `GET /api/tickets/{ticket.get('id', '{ticket_id}')}/context`
- Add ticket notes: `POST /api/tickets/{ticket.get('id', '{ticket_id}')}/notes`
- Request approval: `POST /api/changes/request`
  - Required JSON: `{{"agent_id": <agent_instance_id>, "ticket_id": {ticket.get('id', '{ticket_id}')}, "action": "short verb phrase", "target": "system/account/domain", "reason": "why approval is required", "risk_level": "low|medium|high", "approval_policy": {{"auto_complete": false}}}}`
  - Do not use `title` or `description` fields for change requests.
- The shell guard blocks inline JSON with quoted braces. For POST payloads,
  use the Write tool to create a JSON file, then run a simple Bash curl command
  with `-d @payload.json`. Do not create JSON payloads with Bash heredocs or
  inline `-d '{{...}}'`.
- Poll approval: `GET /api/changes/{{change_id}}/status`
- Complete approved lab/demo containment when no concrete provider adapter is available: `POST /api/changes/{{change_id}}/complete` with JSON `{{"actor": "agent-<agent_instance_id>", "result": "lab-safe evidence and production adapter note"}}`, then add a ticket note.
- Persist postmortems: `POST /api/postmortems`
- Persist workflows: `POST /api/workflows`

## Suspicious URL Safety
Never directly browse, curl, wget, open, screenshot, or otherwise retrieve a
suspicious/phishing/malware URL from this runner, the dashboard host, a user
workstation, or any production network. Treat URLs from phishing reports,
untrusted ticket text, attachments, SIEM/EDR alerts, and user reports as hostile
until proven otherwise. Use passive/sandboxed evidence paths instead: ticket and
email headers, mail-gateway logs, proxy/DNS/firewall logs, Wazuh/SIEM evidence,
known-safe internal allowlists, URL/domain parsing, configured VirusTotal or
urlscan-style adapters, or an approved isolated detonation service. If no safe
adapter exists, record that limitation and request approval/access for a safe
analysis path. Approval to block/quarantine/contain a URL is not approval to
fetch it.

## Browser / Playwright Validation
The runner image includes Node.js and Playwright Chromium for dashboard or
internal-tool UI validation. Use it only for trusted internal dashboard,
ticketing, setup, CI/CD, provider-console, or generated local app checks. A
simple pattern is to write a small `.js` file in the work directory and run it
with `node` or `npx playwright test`; `NODE_PATH` is configured so
`require("playwright")` works from small agent-written scripts.

Do not use Playwright to open suspicious/phishing/malware URLs from tickets,
emails, SIEM, EDR, or user text. Those URLs must stay on the passive,
reputation-adapter, or approved isolated-detonation path above.

## Live Ticket Note Steering
Operators and ticketing providers can add notes while you are already running.
Those updates are delivered without stopping or replacing your task:
- Read `agent_steering_inbox.json` or `AGENT_STEERING.md` in this work
  directory before each major action/checkpoint and after writing any
  "waiting/ready" note.
- Treat steering updates as extra context. Keep the original ticket objective
  unless the update creates a concrete approval, access, safety, or requester
  wait gate.
- When you use a steering update, add a ticket note explaining what changed and
  continue the full goal set. Do not drop prior requirements just because a new
  note arrived.

## Per-Agent Credential Vault
This agent has its own credential lease manifest at `agent_vault.json` in the
work directory. The manifest contains scoped vault references only, never secret
values. Before using any external system credential, request the exact lease
from the dashboard with `POST /api/agents/<agent_id>/vault/lease` using
`system`, `resource_type`, `resource_id`, and `action`. If that endpoint returns
`403 access_denied`, do not reuse broader credentials or bypass the wall. Add a
ticket note explaining the blocked system/resource/action, create
`POST /api/tickets/{ticket.get('id', '{ticket_id}')}/access-request`, write a
`waiting_for_access` checkpoint below 100%, and stop until the gate is approved.

Treat iTop, ServiceNow, Jira, and local-only tickets as providers behind the dashboard API. Do not call provider-specific APIs unless the ticket context or a skill explicitly requires it.
Do not fetch broad schema, docs, or tool inventory endpoints such as `/openapi.json`, `/api/tools`, `/api/tools/status`, `/docs`, or `/redoc`. The runner blocks those calls because they have caused local models to stall on oversized context. Use the bounded ticket/evidence endpoints above.
Do not read saved harness `tool-results` files from current or prior agent workdirs to recover context. Those files can be oversized and stale; re-query the canonical dashboard API with narrower filters instead.
When posting a postmortem, use the exact body fields `ticket_id`, `agent_id`, `task_id`, `status`, `summary`, `went_well`, `improvements`, `workflow_proposal`, `skill_proposals`, `test_cases`, `guardrails`, `documentation`, and `created_by`. Text fields must be strings. `skill_proposals`, `test_cases`, and `guardrails` must be JSON arrays, not strings. Put timeline, root cause, residual risk, and evidence details into the text fields instead of inventing extra top-level fields.

## Checkpoint Protocol
After each major step, write your progress to `checkpoint.json` in your work directory.
Format: {{"step": "...", "status": "running|done|error", "output": "...", "progress_pct": N, "timestamp": "..."}}
Use status `running` for intermediate checkpoints. Only use status `done` with `progress_pct: 100` after approved changes are completed, final notes are written, and the ticket is ready to close.
The runner always creates `checkpoint.json` before you start. Read `checkpoint.json` directly before writing it; do not spend a turn searching or globbing for it.

Do not hardcode passwords, API keys, tokens, or plaintext secrets. Use the credential vault or environment variables.
Do not use ORM, Pydantic models, or SQLAlchemy for database work. Use raw PostgreSQL with parameterized queries.
Shared agent memory is enabled through the agent-memory skill and workspace hooks. Before substantial work, search memory for relevant prior context. After meaningful completion, store a concise durable note with outcome, test evidence, changed files, and caveats. Never store secrets; use redacted placeholders or vault references.
Before updating `checkpoint.json`, read it first, then write the updated JSON. Do not use Bash to check or update `checkpoint.json`.

## Instructions
{prompt}
"""


def _build_claude_md(ticket, skills, prompt):
    """Backward-compatible wrapper for older tests and callers."""
    return _build_agent_context_md(ticket, skills, prompt)


def _build_settings(model, agent_id=None, ticket=None):
    """Build minimal settings.json for agent workspace."""
    ticket_id = (ticket or {}).get("id")
    ticket_class = (ticket or {}).get("itop_class") or (ticket or {}).get("provider_class") or "ticket"
    memory_space = f"soc-dashboard/{str(ticket_class).lower()}/ticket-{ticket_id}" if ticket_id else "soc-dashboard"
    env = {
        "PYTHONIOENCODING": "utf-8",
        "DASHBOARD_API_BASE": DASHBOARD_API_BASE,
        "MEMORY_DB_HOST": os.getenv("MEMORY_DB_HOST", "agent-memory-db"),
        "MEMORY_DB_PORT": os.getenv("MEMORY_DB_PORT", "5432"),
        "MEMORY_DB_NAME": os.getenv("MEMORY_DB_NAME", "agent_memory"),
        "MEMORY_DB_USER": os.getenv("MEMORY_DB_USER", "agent_memory"),
        "MEMORY_DB_PASSWORD": os.getenv("MEMORY_DB_PASSWORD", os.getenv("AGENT_MEMORY_DB_PASSWORD", "")),
        "AGENT_MEMORY_AGENT": f"SOC-Dashboard-Agent-{agent_id}" if agent_id else "SOC-Dashboard-Agent",
        "AGENT_MEMORY_SPACE": memory_space,
    }
    if AGENT_LLM_BASE_URL:
        env["ANTHROPIC_BASE_URL"] = AGENT_LLM_BASE_URL
    if AGENT_LLM_AUTH_TOKEN:
        env["ANTHROPIC_AUTH_TOKEN"] = AGENT_LLM_AUTH_TOKEN

    hook_base = "/root/.claude/skills/agent-memory/scripts/agent_memory_hook.py"
    hook_agent = f"SOC-Dashboard-Agent-{agent_id}" if agent_id else "SOC-Dashboard-Agent"

    return {
        "env": {
            **env,
        },
        "model": model,
        "hooks": {
            "UserPromptSubmit": [
                {
                    "matcher": ".*",
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"python {hook_base} --event UserPromptSubmit --agent {hook_agent} --source soc_dashboard_agent_hook || true",
                            "statusMessage": "Filing prompt into shared agent memory...",
                        }
                    ],
                }
            ],
            "PostToolUse": [
                {
                    "matcher": ".*",
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"python {hook_base} --event PostToolUse --agent {hook_agent} --source soc_dashboard_agent_hook || true",
                            "statusMessage": "Filing tool call into shared agent memory...",
                        }
                    ],
                }
            ],
            "Stop": [
                {
                    "matcher": ".*",
                    "hooks": [
                        {
                            "type": "command",
                            "command": f"python {hook_base} --event Stop --agent {hook_agent} --source soc_dashboard_agent_hook || true",
                            "statusMessage": "Finalizing shared agent memory...",
                        }
                    ],
                }
            ],
        },
    }


def _agent_session_subject(actor_context, ticket_id, allowed_permissions=None):
    actor_context = actor_context or {}
    identity = dict(actor_context.get("identity") or {})
    if not identity.get("username"):
        identity = {
            "username": os.getenv("AGENT_DASHBOARD_SERVICE_USER", "agent-runner-service"),
            "provider": "agent-runner",
            "authenticated": True,
            "auth_mode": "agent-session",
        }
    else:
        identity.setdefault("provider", "agent-runner")
        identity["authenticated"] = True
        identity.setdefault("auth_mode", "agent-session")

    scopes = list(actor_context.get("scopes") or [])
    if ticket_id:
        ticket_scope = {"scope_type": "ticket", "scope_value": str(ticket_id), "permissions": []}
        if ticket_scope not in scopes:
            scopes.append(ticket_scope)

    if allowed_permissions is None:
        allowed_permissions = actor_context.get("capabilities") or []

    return {
        "identity": identity,
        "roles": actor_context.get("roles") or ["agent-operator"],
        "capabilities": allowed_permissions or [],
        "scopes": scopes,
        "max_classification": actor_context.get("max_classification") or "internal",
    }


async def _write_agent_dashboard_session(work_dir, agent_id, subject):
    if not subject:
        return None
    try:
        from services import access_control
        cookie = access_control.create_session_cookie(subject.get("identity"), subject)
    except Exception as exc:
        await log_event("access", "warning", f"agent_{agent_id}", "agent_dashboard_session_failed",
                        f"agent_{agent_id}", {"error": str(exc)})
        return None
    if not cookie:
        return None
    auth_path = os.path.join(work_dir, AGENT_DASHBOARD_SESSION_FILE)
    with open(auth_path, "w", encoding="utf-8") as f:
        json.dump({
            "cookie_name": "dashboard_session",
            "cookie": cookie,
            "username": subject.get("identity", {}).get("username"),
            "provider": subject.get("identity", {}).get("provider"),
            "capabilities": subject.get("capabilities") or [],
            "scopes": subject.get("scopes") or [],
            "secret_values_returned": False,
        }, f, indent=2)
    os.chmod(auth_path, 0o600)
    await log_event("access", "info", f"agent_{agent_id}", "agent_dashboard_session_provisioned",
                    f"agent_{agent_id}", {
                        "username": subject.get("identity", {}).get("username"),
                        "capabilities": subject.get("capabilities") or [],
                        "secret_values_returned": False,
                    })
    return auth_path


async def _provision_work_dir(agent_id, task_id, model, ticket, skills, prompt, vault_manifest=None, dashboard_subject=None):
    """Create isolated work directory with harness config."""
    work_dir = os.path.join(AGENT_WORK_BASE, str(agent_id))
    claude_dir = os.path.join(work_dir, ".claude")
    os.makedirs(claude_dir, exist_ok=True)

    # Write settings
    settings_path = os.path.join(claude_dir, "settings.json")
    with open(settings_path, "w") as f:
        json.dump(_build_settings(model, agent_id, ticket), f)

    # Write context files for both currently supported harnesses. Claude Code
    # reads CLAUDE.md, while Hermes loads AGENTS.md project context.
    claude_md_path = os.path.join(claude_dir, "CLAUDE.md")
    agent_context = _build_agent_context_md(ticket, skills, prompt)
    with open(claude_md_path, "w") as f:
        f.write(agent_context)
    agents_md_path = os.path.join(work_dir, "AGENTS.md")
    with open(agents_md_path, "w", encoding="utf-8") as f:
        f.write(agent_context)

    vault_manifest_path = os.path.join(work_dir, "agent_vault.json")
    with open(vault_manifest_path, "w", encoding="utf-8") as f:
        json.dump(vault_manifest or {"agent_id": agent_id, "leases": []}, f, indent=2, default=str)

    await _write_agent_dashboard_session(work_dir, agent_id, dashboard_subject)

    global_guard_path = _write_global_curl_guard()
    guard_path = _write_curl_guard(work_dir)
    if guard_path:
        await log_event("agent", "info", f"agent_{agent_id}", "agent_curl_guard_provisioned",
                        f"task_{task_id}", {
                            "work_dir": work_dir,
                            "guard_path": guard_path,
                            "global_guard_path": global_guard_path,
                            "blocked_paths": _split_guard_paths(AGENT_CURL_BLOCKED_PATHS),
                            "max_output_bytes": AGENT_CURL_MAX_OUTPUT_BYTES,
                        })

    # Initial checkpoint
    checkpoint_path = os.path.join(work_dir, "checkpoint.json")
    with open(checkpoint_path, "w") as f:
        json.dump({
            "task_id": task_id,
            "step": "init",
            "status": "queued",
            "output": "Agent workspace provisioned",
            "progress_pct": 0,
            "timestamp": datetime.now().isoformat(),
        }, f)

    try:
        from services import agent_steering
        await agent_steering.initialize_agent_inbox(agent_id, task_id, ticket.get("id"), work_dir)
    except Exception as exc:
        await log_event("agent", "warning", f"agent_{agent_id}", "agent_steering_inbox_init_failed",
                        f"task_{task_id}", {"error": str(exc), "work_dir": work_dir})

    _ensure_harness_workspace_ownership(work_dir)

    return work_dir


async def _run_agent(work_dir, prompt, task_id):
    """Spawn selected agent harness subprocess and wait for completion."""
    harness = get_harness(AGENT_HARNESS)
    env = harness.build_env(
        os.environ.copy(),
        llm_base_url=AGENT_LLM_BASE_URL,
        llm_auth_token=AGENT_LLM_AUTH_TOKEN,
        dashboard_api_base=DASHBOARD_API_BASE,
    )
    env = _apply_agent_path_guards(env, work_dir)

    settings_path = os.path.join(work_dir, ".claude", "settings.json")
    config = _load_model_config()
    model = config.get("default", "deepseek/deepseek-v4-flash")
    task = await fetchrow("SELECT agent_id FROM agent_tasks WHERE id = $1", task_id)
    agent_id = task["agent_id"] if task else None
    if task:
        agent = await fetchrow("SELECT selected_model, model FROM agents WHERE id = $1", task["agent_id"])
        if agent:
            model = agent.get("selected_model") or agent.get("model") or model

    cmd = harness.build_command(prompt, settings_path, model, AGENT_PERMISSION_MODE, AGENT_ALLOWED_TOOLS)
    output_path = os.path.join(work_dir, "output.log")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"[runner] starting task {task_id} with harness {harness.name} and model {model}\n")

    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            cwd=work_dir,
        )
        _active_processes[task_id] = process

        # Update task with PID
        await execute(
            "UPDATE agent_tasks SET pid = $1, status = 'running', started_at = NOW(), work_dir = $2 WHERE id = $3",
            process.pid, work_dir, task_id,
        )
        await log_event("agent", "info", f"task_{task_id}", "agent_spawned",
                        f"pid_{process.pid}", {
                            "work_dir": work_dir,
                            "model": model,
                            "harness": harness.name,
                        })
        await _record_model_turn_event(
            "agent_model_turn_started",
            task_id,
            agent_id,
            {
                "turn_index": 1,
                "trigger": "process_started",
                "pid": process.pid,
                "model": model,
            },
        )
        await execute(
            "UPDATE agent_tasks SET progress_pct = GREATEST(progress_pct, 5) WHERE id = $1",
            task_id,
        )

        chunks = []
        activity = {
            "last_output_at": time.monotonic(),
            "model_turn_index": 1,
            "model_turn_started_at": datetime.now().isoformat(),
            "model_turn_started_monotonic": time.monotonic(),
            "model_turn_open": True,
        }
        idle_state = {"stalled": False, "reason": None}
        checkpoint_state = {"checkpoint": None, "reason": None}
        idle_task = asyncio.create_task(
            _terminate_after_no_output(process, AGENT_NO_OUTPUT_STALL_SECONDS, activity, idle_state)
        )
        checkpoint_task = asyncio.create_task(
            _terminate_after_blocking_checkpoint(process, work_dir, activity, checkpoint_state)
        )
        stdout_task = asyncio.create_task(
            _stream_reader(process.stdout, "stdout", output_path, task_id, agent_id, chunks, activity)
        )
        stderr_task = asyncio.create_task(
            _stream_reader(process.stderr, "stderr", output_path, task_id, agent_id, chunks, activity)
        )
        try:
            if AGENT_TIMEOUT_MINUTES > 0:
                timeout = timedelta(minutes=AGENT_TIMEOUT_MINUTES).total_seconds()
                await asyncio.wait_for(process.wait(), timeout=timeout)
            else:
                await process.wait()
            idle_task.cancel()
            checkpoint_task.cancel()
            await asyncio.gather(idle_task, checkpoint_task, return_exceptions=True)
            await asyncio.gather(stdout_task, stderr_task)
            output = "".join(chunks)
            return {
                "exit_code": process.returncode,
                "stdout": output,
                "stderr": checkpoint_state["reason"] or idle_state["reason"] or "",
                "no_output_stalled": idle_state["stalled"],
                "blocking_checkpoint": checkpoint_state["checkpoint"],
            }
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            idle_task.cancel()
            checkpoint_task.cancel()
            stdout_task.cancel()
            stderr_task.cancel()
            await asyncio.gather(idle_task, checkpoint_task, stdout_task, stderr_task, return_exceptions=True)
            return {
                "exit_code": -1,
                "stdout": _tail_text("".join(chunks)),
                "stderr": f"Agent timed out after {AGENT_TIMEOUT_MINUTES} minutes",
                "timed_out": True,
            }

    except Exception as e:
        return {
            "exit_code": -1,
            "stdout": "",
            "stderr": str(e),
        }


async def spawn_agent(ticket_id, model, prompt, task_type="ticket_resolution", actor_context=None, requested_permissions=None):
    """Spawn the selected agent harness to work on a ticket.

    Returns task_id on success.
    """
    # Get ticket context
    ticket = await fetchrow(
        "SELECT id, title, description, itop_class, priority, status, itop_ref FROM tickets WHERE id = $1",
        ticket_id,
    )
    if not ticket:
        return {"error": "Ticket not found"}

    # Get assigned skills for this agent
    skills = []
    row = await fetchall(
        "SELECT name, description FROM agent_skills WHERE enabled = true AND assigned_to_all = true"
    )
    skills.extend(row or [])

    # Create agent record first (agent_tasks has FK to agents)
    agent_id = await fetchval(
        "INSERT INTO agents (ticket_id, model, selected_model, status, started_at, heartbeat, assigned_by) "
        "VALUES ($1, $2, $3, 'spawned', NOW(), NOW(), 'dashboard') "
        "RETURNING id",
        ticket_id, model, model,
    )

    # Create task record with real agent_id
    task_id = await fetchval(
        "INSERT INTO agent_tasks (agent_id, ticket_id, task_type, prompt, status) "
        "VALUES ($1, $2, $3, $4, 'queued') RETURNING id",
        agent_id, ticket_id, task_type, prompt,
    )
    permission_context_result = {"status": "not_recorded", "allowed_permissions": [], "denied_permissions": []}
    try:
        from services import access_control
        permission_context_result = await access_control.record_agent_permission_context(
            agent_id,
            ticket_id,
            actor_context,
            requested_permissions,
        )
    except Exception as exc:
        await log_event(
            "access",
            "warning",
            f"agent_{agent_id}",
            "agent_permission_snapshot_failed",
            f"ticket_{ticket_id}",
            {"error": str(exc), "task_type": task_type},
        )

    vault_manifest = {"agent_id": agent_id, "ticket_id": ticket_id, "leases": []}
    try:
        from services import access_control
        vault_manifest = await access_control.create_agent_vault_manifest(
            agent_id,
            ticket_id,
            actor_context,
        )
        if permission_context_result.get("denied_permissions"):
            vault_manifest["denied_requested_permissions"] = permission_context_result.get("denied_permissions")
    except Exception as exc:
        await log_event(
            "access",
            "warning",
            f"agent_{agent_id}",
            "agent_vault_manifest_failed",
            f"ticket_{ticket_id}",
            {"error": str(exc), "task_type": task_type},
        )

    # Link agent to task and ticket to agent
    await execute(
        "UPDATE agents SET last_task_id = $1 WHERE id = $2",
        task_id, agent_id,
    )
    if task_type == "postmortem":
        await execute(
            "UPDATE tickets SET updated_at = NOW() WHERE id = $1",
            ticket_id,
        )
    else:
        await execute(
            "UPDATE tickets SET agent_id = $1, status = 'in_progress', updated_at = NOW() WHERE id = $2",
            agent_id, ticket_id,
        )

    # Provision isolated work directory with selected harness config
    dashboard_subject = _agent_session_subject(
        actor_context,
        ticket_id,
        permission_context_result.get("allowed_permissions") if permission_context_result else None,
    )
    work_dir = await _provision_work_dir(
        agent_id,
        task_id,
        model,
        ticket,
        skills,
        prompt,
        vault_manifest,
        dashboard_subject,
    )
    await execute(
        "UPDATE agent_tasks SET work_dir = $1 WHERE id = $2",
        work_dir, task_id,
    )

    priority_rank = _ticket_priority_rank(ticket.get("priority"), task_type)
    await log_event("agent", "info", f"agent_{agent_id}", "spawn_requested",
                    f"ticket_{ticket_id}", {
                        "model": model,
                        "task_id": task_id,
                        "priority": ticket.get("priority"),
                        "priority_rank": priority_rank,
                    })
    await _add_agent_note(
        ticket_id,
        agent_id,
        task_id,
        "Agent assigned",
        (
            f"Agent `{agent_id}` was assigned with model `{model}` for `{task_type}`. "
            f"The runner provisioned an isolated workspace and queued the task with priority rank `{priority_rank}`."
        ),
    )

    _ensure_queue_workers()
    sequence = next(_queue_counter)
    await _agent_queue.put((priority_rank, sequence, work_dir, prompt, task_id, agent_id))
    await log_event("agent", "info", f"agent_{agent_id}", "agent_queue_enqueued",
                    f"task_{task_id}", {
                        "priority": ticket.get("priority"),
                        "priority_rank": priority_rank,
                        "sequence": sequence,
                        "queued_depth": _agent_queue.qsize(),
                    })

    return {
        "status": "spawned",
        "agent_id": agent_id,
        "task_id": task_id,
        "ticket_id": ticket_id,
        "model": model,
        "priority_rank": priority_rank,
    }


async def _spawn_with_semaphore(work_dir, prompt, task_id, agent_id):
    """Wait for semaphore slot, then run agent."""
    async with _semaphore:
        task_meta = await fetchrow("""
            SELECT at.ticket_id, at.task_type, at.status AS task_status,
                   a.status AS agent_status
            FROM agent_tasks at
            JOIN agents a ON a.id = at.agent_id
            WHERE at.id = $1 AND at.agent_id = $2
        """, task_id, agent_id)
        if not task_meta:
            await log_event("agent", "warning", f"agent_{agent_id}",
                            "agent_spawn_skipped_missing_task", f"task_{task_id}",
                            {"work_dir": work_dir})
            return

        if task_meta.get("task_status") not in ("queued", "running") or task_meta.get("agent_status") in ("stopped", "terminated", "failed"):
            await log_event("agent", "info", f"agent_{agent_id}",
                            "agent_spawn_skipped_not_runnable", f"task_{task_id}", {
                                "task_status": task_meta.get("task_status"),
                                "agent_status": task_meta.get("agent_status"),
                            })
            return

        await log_event("agent", "info", f"agent_{agent_id}", "agent_running",
                        f"task_{task_id}", {"work_dir": work_dir})
        if task_meta:
            await _add_agent_note(
                task_meta.get("ticket_id"),
                agent_id,
                task_id,
                "Agent started",
                (
                    f"Agent `{agent_id}` started `{task_meta.get('task_type') or 'ticket_resolution'}` "
                    f"in workspace `{work_dir}`. Progress checkpoints and approval gates will be recorded here."
                ),
            )

        result = await _run_agent(work_dir, prompt, task_id)
        terminal_meta = await fetchrow("""
            SELECT at.status AS task_status, a.status AS agent_status, at.ticket_id
            FROM agent_tasks at
            JOIN agents a ON a.id = at.agent_id
            WHERE at.id = $1 AND at.agent_id = $2
        """, task_id, agent_id)
        if terminal_meta and (
            terminal_meta.get("task_status") in ("stopped", "terminated")
            or terminal_meta.get("agent_status") in ("stopped", "terminated")
        ):
            await log_event("agent", "info", f"agent_{agent_id}",
                            "agent_exit_after_operator_stop", f"task_{task_id}", {
                                "exit_code": result.get("exit_code"),
                                "task_status": terminal_meta.get("task_status"),
                                "agent_status": terminal_meta.get("agent_status"),
                            })
            if terminal_meta.get("ticket_id"):
                await _add_agent_note(
                    terminal_meta.get("ticket_id"),
                    agent_id,
                    task_id,
                    "Agent stopped",
                    (
                        f"Agent `{agent_id}` exited after an operator stop. "
                        f"The runner preserved `{terminal_meta.get('agent_status')}` / "
                        f"`{terminal_meta.get('task_status')}` instead of marking the intentional stop as a failure."
                    ),
                    "agent-control-plane",
                )
            _active_processes.pop(task_id, None)
            return
        checkpoint = await _mirror_checkpoint_to_task(task_id, agent_id, work_dir)
        checkpoint_done = bool(checkpoint and checkpoint.get("status") in ("done", "completed"))
        checkpoint_blocked = _checkpoint_blocks_completion(checkpoint)
        task_meta = await fetchrow(
            "SELECT ticket_id, task_type, started_at FROM agent_tasks WHERE id = $1",
            task_id,
        )

        # Update task and agent status
        if checkpoint_blocked:
            blocked_status = _blocked_task_status(checkpoint)
            blocked_summary = (checkpoint or {}).get("output") or "Agent stopped at a durable wait gate."
            gate_state = await _gate_state_for_wait(
                agent_id,
                (task_meta or {}).get("ticket_id"),
            )
            if _wait_checkpoint_obsolete(checkpoint, gate_state):
                continuation = await _spawn_obsolete_wait_continuation(
                    agent_id,
                    task_id,
                    task_meta,
                    checkpoint,
                    gate_state,
                    prompt,
                )
                await execute(
                    "UPDATE agent_tasks SET status = 'completed', output = $1, completed_at = NOW(), "
                    "progress_pct = 100 WHERE id = $2",
                    _tail_text(result.get("stdout", "")) or blocked_summary,
                    task_id,
                )
                await execute(
                    "UPDATE agents SET status = 'finished', heartbeat = NOW(), error_message = $1, finished_at = NOW() WHERE id = $2",
                    (
                        "Wait checkpoint was stale because the approval/access gate was already approved or completed. "
                        f"Continuation: {continuation.get('status')}"
                    )[:500],
                    agent_id,
                )
                _active_processes.pop(task_id, None)
                return
            await execute(
                "UPDATE agent_tasks SET status = $1, output = $2, completed_at = NOW(), "
                "progress_pct = GREATEST(progress_pct, $3) WHERE id = $4",
                blocked_status,
                _tail_text(result.get("stdout", "")) or blocked_summary,
                int((checkpoint or {}).get("progress_pct") or 50),
                task_id,
            )
            await execute(
                "UPDATE agents SET status = $1, heartbeat = NOW(), error_message = $2, finished_at = NOW() WHERE id = $3",
                blocked_status,
                blocked_summary[:500],
                agent_id,
            )
            if task_meta and task_meta.get("ticket_id"):
                ticket_status = "pending_approval" if blocked_status == "pending_approval" else blocked_status
                await execute(
                    "UPDATE tickets SET status = $1, updated_at = NOW() WHERE id = $2",
                    ticket_status,
                    task_meta.get("ticket_id"),
                )
                await _add_agent_note(
                    task_meta.get("ticket_id"),
                    agent_id,
                    task_id,
                    "Agent waiting",
                    (
                        f"Agent `{agent_id}` stopped at `{blocked_status}` instead of resolving the ticket. "
                        f"Checkpoint: `{(checkpoint or {}).get('step', 'unknown')}`. "
                        f"Reason: {blocked_summary[:900]}"
                    ),
                    "agent-control-plane",
                )
            await log_event("agent", "info", f"agent_{agent_id}", "agent_waiting_at_gate",
                            f"task_{task_id}", {
                                "ticket_id": (task_meta or {}).get("ticket_id"),
                                "blocked_status": blocked_status,
                                "checkpoint": checkpoint,
                            })
        elif result["exit_code"] == 0 or checkpoint_done:
            if task_meta and task_meta.get("task_type") == "postmortem":
                postmortem_count = await fetchval("""
                    SELECT COUNT(*) FROM postmortems
                    WHERE ticket_id = $1
                      AND (task_id = $2 OR created_at >= $3)
                """, task_meta["ticket_id"], task_id, task_meta["started_at"])
                if not postmortem_count:
                    error = "Postmortem task exited without creating a postmortem artifact"
                    synthesis = None
                    try:
                        from services.postmortem_synthesizer import synthesize_postmortem
                        synthesis = await synthesize_postmortem(
                            task_meta["ticket_id"],
                            agent_id,
                            task_id,
                            "agent-runner",
                            error,
                        )
                    except Exception as exc:
                        synthesis = {"status": "failed", "error": str(exc)}
                    await execute(
                        "UPDATE agent_tasks SET status = 'failed', output = $1, error_message = $2, "
                        "completed_at = NOW() WHERE id = $3",
                        _tail_text(result.get("stdout", "")), error, task_id,
                    )
                    await execute(
                        "UPDATE agents SET status = 'failed', heartbeat = NOW(), error_message = $1, finished_at = NOW() WHERE id = $2",
                        error, agent_id,
                    )
                    await log_event("agent", "error", f"agent_{agent_id}",
                                    "postmortem_artifact_missing", f"task_{task_id}",
                                    {"synthesis": synthesis})
                    await _add_agent_note(
                        task_meta["ticket_id"],
                        agent_id,
                        task_id,
                        "Postmortem fallback used",
                        (
                            "The postmortem agent exited without creating a postmortem artifact. "
                            f"The supervisor synthesis result was `{(synthesis or {}).get('status', 'unknown')}`."
                        ),
                    )
                    _active_processes.pop(task_id, None)
                    return
            summary = _parse_stream_result(result["stdout"]) or f"{harness.name} process completed"
            if checkpoint_done and checkpoint.get("output"):
                summary = checkpoint.get("output")
            if not checkpoint_done:
                _write_checkpoint(
                    work_dir,
                    task_id,
                    "agent_runner_success",
                    "done",
                    summary[:1000],
                    100,
                )
                checkpoint = _read_checkpoint_sync(work_dir) or checkpoint
            await execute(
                "UPDATE agent_tasks SET status = 'completed', output = $1, "
                "completed_at = NOW(), progress_pct = 100 WHERE id = $2",
                result["stdout"][:5000], task_id,
            )
            await execute(
                "UPDATE agents SET status = 'finished', heartbeat = NOW(), finished_at = NOW() WHERE id = $1",
                agent_id,
            )
            change_completion = await complete_approved_changes_for_task(
                agent_id,
                task_id,
                reason="agent_runner_success",
                checkpoint=checkpoint,
            )
            status_recovery = {"status": "skipped", "reason": "not_attempted"}
            if task_meta:
                await _add_agent_note(
                    task_meta.get("ticket_id"),
                    agent_id,
                    task_id,
                    "Agent completed",
                    (
                        f"Agent `{agent_id}` finished task `{task_id}`. "
                        f"Summary: {summary[:700] or f'{harness.name} process completed.'}"
                    ),
                )
                status_recovery = await recover_done_checkpoint_ticket_status(
                    agent_id,
                    task_id,
                    checkpoint,
                    reason="agent_runner_success",
                )
            await log_event("agent", "info", f"agent_{agent_id}", "agent_completed",
                            f"task_{task_id}", {
                                "summary": summary[:500],
                                "checkpoint_done": checkpoint_done,
                                "auto_completed_changes": change_completion.get("completed", []),
                                "auto_complete_skipped": change_completion.get("skipped", []),
                                "ticket_status_recovery": status_recovery,
                            })
        else:
            recovered_completion = await _detect_completed_ticket_resolution(task_id, agent_id)
            if recovered_completion:
                summary = (
                    "Recovered completion: ticket has final resolution evidence, "
                    f"{recovered_completion['completed_changes']} completed change gates, "
                    f"{recovered_completion['final_notes']} final notes, and "
                    f"{recovered_completion['postmortems']} postmortems."
                )
                if not checkpoint_done:
                    _write_checkpoint(
                        work_dir,
                        task_id,
                        "agent_runner_recovered_completion",
                        "done",
                        summary[:1000],
                        100,
                    )
                await execute(
                    "UPDATE agent_tasks SET status = 'completed', output = $1, error_message = NULL, "
                    "completed_at = NOW(), progress_pct = 100 WHERE id = $2",
                    _tail_text(result.get("stdout", "")), task_id,
                )
                await execute(
                    "UPDATE agents SET status = 'finished', heartbeat = NOW(), error_message = NULL, finished_at = NOW() WHERE id = $1",
                    agent_id,
                )
                await log_event("agent", "warning", f"agent_{agent_id}", "agent_completion_recovered",
                                f"task_{task_id}", {
                                    "summary": summary,
                                    "checkpoint_done": checkpoint_done,
                                    "exit_code": result.get("exit_code"),
                                    "evidence": recovered_completion,
                                })
                await _add_agent_note(
                    recovered_completion["ticket_id"],
                    agent_id,
                    task_id,
                    "Agent completed with recovered finalization",
                    (
                        f"Agent `{agent_id}` finished the ticket work but did not persist a final done checkpoint. "
                        f"The supervisor recovered completion from dashboard evidence: {summary}"
                    ),
                )
                _active_processes.pop(task_id, None)
                return
            raw_error = result.get("stderr") or result.get("stdout") or f"Agent exited with code {result['exit_code']}"
            error = raw_error[:2000]
            transient_retry = await _schedule_transient_model_retry(
                agent_id,
                task_id,
                task_meta,
                work_dir,
                prompt,
                result,
                error,
            )
            if transient_retry:
                _active_processes.pop(task_id, None)
                return
            await execute(
                "UPDATE agent_tasks SET status = 'failed', output = $1, error_message = $2, "
                "completed_at = NOW() WHERE id = $3",
                _tail_text(result.get("stdout", "")), error, task_id,
            )
            await execute(
                "UPDATE agents SET status = 'failed', heartbeat = NOW(), error_message = $1, finished_at = NOW() WHERE id = $2",
                error[:500], agent_id,
            )
            await log_event("agent", "error", f"agent_{agent_id}", "agent_failed",
                            f"task_{task_id}", {"error": error[:500]})
            if task_meta:
                await _add_agent_note(
                    task_meta.get("ticket_id"),
                    agent_id,
                    task_id,
                    "Agent failed",
                    f"Agent `{agent_id}` failed task `{task_id}`. Error: {error[:900]}",
                )

        # Clean up
        _active_processes.pop(task_id, None)


async def stop_agent_task(agent_id, reason="stopped via dashboard"):
    """Stop a running agent task."""
    task = await fetchrow(
        "SELECT id, pid FROM agent_tasks WHERE agent_id = $1 AND status IN ('queued', 'running')",
        agent_id,
    )
    if not task:
        return {"error": "No active task for this agent"}

    if task["pid"]:
        if task["id"] in _active_processes:
            proc = _active_processes[task["id"]]
            proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=5)
            except asyncio.TimeoutError:
                proc.kill()
        else:
            try:
                os.kill(task["pid"], signal.SIGTERM)
            except ProcessLookupError:
                pass
            except PermissionError:
                return {"error": f"Permission denied stopping pid {task['pid']}"}

    await execute(
        "UPDATE agent_tasks SET status = 'stopped', completed_at = NOW() WHERE id = $1",
        task["id"],
    )
    await execute(
        "UPDATE agents SET status = 'stopped', finished_at = NOW(), "
        "error_message = $1 WHERE id = $2",
        reason,
        agent_id,
    )
    await log_event("agent", "info", f"agent_{agent_id}", "agent_stopped",
                    f"task_{task['id']}", {"reason": reason})

    return {"status": "stopped", "task_id": task["id"]}


async def get_process_snapshot():
    """Return agent harness process diagnostics from inside the runner container."""
    ps_path = shutil.which("ps")
    if not ps_path:
        for task_id, proc in list(_active_processes.items()):
            if getattr(proc, "returncode", None) is not None:
                _active_processes.pop(task_id, None)
        return {
            "ps_path": None,
            "error": "ps not installed in runner container",
            "active_processes": list(_active_processes.keys()),
        }

    try:
        completed = subprocess.run(
            [ps_path, "-eo", "pid,ppid,stat,etime,comm,args"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        lines = completed.stdout.splitlines()
        header = lines[0] if lines else ""
        rows = [
            line for line in lines[1:]
            if (
                "claude" in line.lower()
                or "hermes" in line.lower()
                or "node" in line.lower()
                or "bun" in line.lower()
            )
        ]
        observed_pids = set()
        for row in rows:
            parts = row.split(None, 1)
            if not parts:
                continue
            try:
                observed_pids.add(int(parts[0]))
            except ValueError:
                continue
        active_task_ids = set()
        for task_id, proc in list(_active_processes.items()):
            if getattr(proc, "returncode", None) is not None:
                _active_processes.pop(task_id, None)
                continue
            active_task_ids.add(task_id)
        try:
            pid_tasks = await fetchall(
                """
                SELECT id, pid
                FROM agent_tasks
                WHERE status IN ('queued', 'running')
                  AND pid IS NOT NULL
                """
            )
            for task in pid_tasks:
                if task.get("pid") in observed_pids:
                    active_task_ids.add(task["id"])
        except Exception:
            pass
        return {
            "ps_path": ps_path,
            "exit_code": completed.returncode,
            "header": header,
            "processes": rows,
            "active_processes": sorted(active_task_ids),
        }
    except Exception as exc:
        return {
            "ps_path": ps_path,
            "error": f"{type(exc).__name__}: {exc}",
            "active_processes": list(_active_processes.keys()),
        }


async def get_available_models():
    """Return list of available models from config file."""
    config = _load_model_config()
    return config.get("models", ["deepseek/deepseek-v4-flash"])


async def get_runner_health():
    """Return local runner diagnostics without making an LLM request."""
    config = _load_model_config()
    settings_path = os.path.expanduser("~/.claude/settings.json")
    creds_path = os.path.expanduser("~/.claude/.credentials.json")
    hermes_home = os.getenv("HERMES_HOME", os.path.expanduser("~/.hermes"))
    hermes_config_path = os.path.join(hermes_home, "config.yaml")
    hermes_auth_path = os.path.join(hermes_home, "shared", "nous_auth.json")
    settings = {}
    if os.path.exists(settings_path):
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                settings = json.load(f)
        except json.JSONDecodeError:
            settings = {"error": "settings.json is not valid JSON"}

    settings_base_url = (settings.get("env") or {}).get("ANTHROPIC_BASE_URL")
    effective_base_url = AGENT_LLM_BASE_URL or settings_base_url
    model_api = {"status": "unknown", "error": "AGENT_LLM_BASE_URL/ANTHROPIC_BASE_URL is not configured"}
    if effective_base_url:
        try:
            with urllib.request.urlopen(f"{effective_base_url.rstrip('/')}/v1/models", timeout=3) as response:
                body = response.read(1000).decode("utf-8", errors="replace")
                model_api = {
                    "status": "ok",
                    "http_status": response.status,
                    "sample": body,
                }
        except Exception as exc:
            model_api = {
                "status": "error",
                "error": f"{type(exc).__name__}: {exc}",
            }

    return {
        "claude_path": shutil.which("claude"),
        "hermes_path": shutil.which("hermes") or os.getenv("HERMES_BIN"),
        "settings_path": settings_path,
        "settings_exists": os.path.exists(settings_path),
        "credentials_path": creds_path,
        "credentials_exists": os.path.exists(creds_path),
        "hermes_home": hermes_home,
        "hermes_config_exists": os.path.exists(hermes_config_path),
        "hermes_nous_auth_exists": os.path.exists(hermes_auth_path),
        "settings_anthropic_base_url": settings_base_url,
        "effective_anthropic_base_url": effective_base_url,
        "model_api": model_api,
        "models": config.get("models", []),
        "default_model": config.get("default"),
        "work_base": AGENT_WORK_BASE,
        "max_concurrent_agents": MAX_CONCURRENT_AGENTS,
        "timeout_minutes": AGENT_TIMEOUT_MINUTES,
        "no_output_stall_seconds": AGENT_NO_OUTPUT_STALL_SECONDS,
        "permission_mode": AGENT_PERMISSION_MODE,
        "allowed_tools": AGENT_ALLOWED_TOOLS,
        "harness": AGENT_HARNESS,
        "available_harnesses": list_harnesses(),
        "ps_path": shutil.which("ps"),
        "dashboard_api_base": DASHBOARD_API_BASE,
    }
