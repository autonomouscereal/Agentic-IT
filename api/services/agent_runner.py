import os
import json
import asyncio
import signal
import shutil
import subprocess
import time
import urllib.request
from datetime import datetime, timedelta
from database import execute, fetchrow, fetchval, fetchall
from services.event_logger import log_event
from services.agent_harness import get_harness, list_harnesses

AGENT_WORK_BASE = os.getenv("AGENT_WORK_BASE", "/app/agent_work")
MAX_CONCURRENT_AGENTS = int(os.getenv("MAX_CONCURRENT_AGENTS", "3"))
AGENT_TIMEOUT_MINUTES = int(os.getenv("AGENT_TIMEOUT_MINUTES", "0"))
MODEL_CONFIG_PATH = os.getenv("MODEL_CONFIG_PATH", "/app/agent_models.json")
AGENT_PERMISSION_MODE = os.getenv("AGENT_PERMISSION_MODE", "acceptEdits")
AGENT_ALLOWED_TOOLS = os.getenv("AGENT_ALLOWED_TOOLS", "Read,Write,Bash(curl *)").strip()
AGENT_LLM_BASE_URL = os.getenv("AGENT_LLM_BASE_URL", "").strip()
AGENT_LLM_AUTH_TOKEN = os.getenv("AGENT_LLM_AUTH_TOKEN", "").strip()
DASHBOARD_API_BASE = os.getenv("DASHBOARD_API_BASE", "http://localhost:8000").strip()
AGENT_HARNESS = os.getenv("AGENT_HARNESS", "claude-code")

_semaphore = asyncio.Semaphore(MAX_CONCURRENT_AGENTS)
_active_processes = {}
_model_config = None


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


async def _stream_reader(stream, label, output_path, task_id, agent_id, chunks):
    """Stream subprocess output to disk and periodically mirror a tail to DB."""
    last_db_update = 0.0
    with open(output_path, "a", encoding="utf-8", errors="replace") as f:
        while True:
            line = await stream.readline()
            if not line:
                break
            text = line.decode("utf-8", errors="replace")
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


def _loads(value, default):
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value


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
    credentials already available to the harness/container.
    """
    global _model_config
    if _model_config is None:
        try:
            with open(MODEL_CONFIG_PATH, "r") as f:
                _model_config = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            _model_config = {
                "models": ["qwen/qwen3.6-27b"],
                "default": "qwen/qwen3.6-27b",
            }
    return _model_config


def _build_claude_md(ticket, skills, prompt):
    """Build CLAUDE.md for the spawned agent workspace."""
    skills_section = ""
    if skills:
        skills_lines = []
        for s in skills:
            skills_lines.append(f"- **{s['name']}**: {s.get('description', '')}")
        skills_section = "\n".join(skills_lines)
    else:
        skills_section = "- server-manager (SSH client)\n- web-research (SearXNG)\n- MemPalace MCP"

    return f"""# SOC Agent - Ticket Resolution

You are an SOC agent assigned to resolve the following ticket.

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
- Ticket context: `GET /api/tickets/{ticket.get('id', '{ticket_id}')}/context`
- Add ticket notes: `POST /api/tickets/{ticket.get('id', '{ticket_id}')}/notes`
- Request approval: `POST /api/changes/request`
- Poll approval: `GET /api/changes/{{change_id}}/status`
- Persist postmortems: `POST /api/postmortems`
- Persist workflows: `POST /api/workflows`

Treat iTop, ServiceNow, Jira, and local-only tickets as providers behind the dashboard API. Do not call provider-specific APIs unless the ticket context or a skill explicitly requires it.

## Checkpoint Protocol
After each major step, write your progress to `checkpoint.json` in your work directory.
Format: {{"step": "...", "status": "running|done|error", "output": "...", "progress_pct": N, "timestamp": "..."}}
The runner always creates `checkpoint.json` before you start. Read `checkpoint.json` directly before writing it; do not spend a turn searching or globbing for it.

Do not hardcode passwords, API keys, tokens, or plaintext secrets. Use the credential vault or environment variables.
Do not use ORM, Pydantic models, or SQLAlchemy for database work. Use raw PostgreSQL with parameterized queries.
Shared agent memory is enabled through the agent-memory skill and workspace hooks. Before substantial work, search memory for relevant prior context. After meaningful completion, store a concise durable note with outcome, test evidence, changed files, and caveats. Never store secrets; use redacted placeholders or vault references.
Before updating `checkpoint.json`, read it first, then write the updated JSON. Do not use Bash to check or update `checkpoint.json`.

## Instructions
{prompt}
"""


def _build_settings(model, agent_id=None):
    """Build minimal settings.json for agent workspace."""
    env = {
        "PYTHONIOENCODING": "utf-8",
        "DASHBOARD_API_BASE": DASHBOARD_API_BASE,
        "MEMORY_DB_HOST": os.getenv("MEMORY_DB_HOST", "agent-memory-db"),
        "MEMORY_DB_PORT": os.getenv("MEMORY_DB_PORT", "5432"),
        "MEMORY_DB_NAME": os.getenv("MEMORY_DB_NAME", "agent_memory"),
        "MEMORY_DB_USER": os.getenv("MEMORY_DB_USER", "agent_memory"),
        "MEMORY_DB_PASSWORD": os.getenv("MEMORY_DB_PASSWORD", os.getenv("AGENT_MEMORY_DB_PASSWORD", "")),
        "AGENT_MEMORY_AGENT": f"SOC-Dashboard-Agent-{agent_id}" if agent_id else "SOC-Dashboard-Agent",
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


async def _provision_work_dir(agent_id, task_id, model, ticket, skills, prompt):
    """Create isolated work directory with Claude Code config."""
    work_dir = os.path.join(AGENT_WORK_BASE, str(agent_id))
    claude_dir = os.path.join(work_dir, ".claude")
    os.makedirs(claude_dir, exist_ok=True)

    # Write settings
    settings_path = os.path.join(claude_dir, "settings.json")
    with open(settings_path, "w") as f:
        json.dump(_build_settings(model, agent_id), f)

    # Write CLAUDE.md
    claude_md_path = os.path.join(claude_dir, "CLAUDE.md")
    with open(claude_md_path, "w") as f:
        f.write(_build_claude_md(ticket, skills, prompt))

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

    return work_dir


async def _run_agent(work_dir, prompt, task_id):
    """Spawn Claude Code subprocess and wait for completion."""
    harness = get_harness(AGENT_HARNESS)
    env = harness.build_env(
        os.environ.copy(),
        llm_base_url=AGENT_LLM_BASE_URL,
        llm_auth_token=AGENT_LLM_AUTH_TOKEN,
        dashboard_api_base=DASHBOARD_API_BASE,
    )

    settings_path = os.path.join(work_dir, ".claude", "settings.json")
    config = _load_model_config()
    model = config.get("default", "qwen/qwen3.6-27b")
    task = await fetchrow("SELECT agent_id FROM agent_tasks WHERE id = $1", task_id)
    agent_id = task["agent_id"] if task else None
    if task:
        agent = await fetchrow("SELECT selected_model, model FROM agents WHERE id = $1", task["agent_id"])
        if agent:
            model = agent.get("selected_model") or agent.get("model") or model

    cmd = harness.build_command(prompt, settings_path, model, AGENT_PERMISSION_MODE, AGENT_ALLOWED_TOOLS)
    output_path = os.path.join(work_dir, "output.log")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(f"[runner] starting task {task_id} with model {model}\n")

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
                        f"pid_{process.pid}", {"work_dir": work_dir, "model": model})
        await execute(
            "UPDATE agent_tasks SET progress_pct = GREATEST(progress_pct, 5) WHERE id = $1",
            task_id,
        )

        chunks = []
        stdout_task = asyncio.create_task(
            _stream_reader(process.stdout, "stdout", output_path, task_id, agent_id, chunks)
        )
        stderr_task = asyncio.create_task(
            _stream_reader(process.stderr, "stderr", output_path, task_id, agent_id, chunks)
        )
        try:
            if AGENT_TIMEOUT_MINUTES > 0:
                timeout = timedelta(minutes=AGENT_TIMEOUT_MINUTES).total_seconds()
                await asyncio.wait_for(process.wait(), timeout=timeout)
            else:
                await process.wait()
            await asyncio.gather(stdout_task, stderr_task)
            output = "".join(chunks)
            return {
                "exit_code": process.returncode,
                "stdout": output,
                "stderr": "",
            }
        except asyncio.TimeoutError:
            process.kill()
            await process.wait()
            stdout_task.cancel()
            stderr_task.cancel()
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


async def spawn_agent(ticket_id, model, prompt, task_type="ticket_resolution"):
    """Spawn a Claude Code agent to work on a ticket.

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

    # Provision isolated work directory with Claude Code config
    work_dir = await _provision_work_dir(agent_id, task_id, model, ticket, skills, prompt)
    await execute(
        "UPDATE agent_tasks SET work_dir = $1 WHERE id = $2",
        work_dir, task_id,
    )

    await log_event("agent", "info", f"agent_{agent_id}", "spawn_requested",
                    f"ticket_{ticket_id}", {"model": model, "task_id": task_id})
    await _add_agent_note(
        ticket_id,
        agent_id,
        task_id,
        "Agent assigned",
        (
            f"Agent `{agent_id}` was assigned with model `{model}` for `{task_type}`. "
            "The runner provisioned an isolated workspace and queued the task."
        ),
    )

    # Spawn in background with semaphore
    asyncio.create_task(_spawn_with_semaphore(work_dir, prompt, task_id, agent_id))

    return {
        "status": "spawned",
        "agent_id": agent_id,
        "task_id": task_id,
        "ticket_id": ticket_id,
        "model": model,
    }


async def _spawn_with_semaphore(work_dir, prompt, task_id, agent_id):
    """Wait for semaphore slot, then run agent."""
    async with _semaphore:
        task_meta = await fetchrow(
            "SELECT ticket_id, task_type FROM agent_tasks WHERE id = $1",
            task_id,
        )
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
        checkpoint = await _mirror_checkpoint_to_task(task_id, agent_id, work_dir)
        checkpoint_done = bool(checkpoint and checkpoint.get("status") in ("done", "completed"))
        task_meta = await fetchrow(
            "SELECT ticket_id, task_type, started_at FROM agent_tasks WHERE id = $1",
            task_id,
        )

        # Update task and agent status
        if result["exit_code"] == 0 or checkpoint_done:
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
            summary = _parse_stream_result(result["stdout"]) or "Claude Code process completed"
            if checkpoint_done and checkpoint.get("output"):
                summary = checkpoint.get("output")
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
            await log_event("agent", "info", f"agent_{agent_id}", "agent_completed",
                            f"task_{task_id}", {
                                "summary": summary[:500],
                                "checkpoint_done": checkpoint_done,
                                "auto_completed_changes": change_completion.get("completed", []),
                                "auto_complete_skipped": change_completion.get("skipped", []),
                            })
            if task_meta:
                await _add_agent_note(
                    task_meta.get("ticket_id"),
                    agent_id,
                    task_id,
                    "Agent completed",
                    (
                        f"Agent `{agent_id}` finished task `{task_id}`. "
                        f"Summary: {summary[:700] or 'Claude Code process completed.'}"
                    ),
                )
        else:
            raw_error = result.get("stderr") or result.get("stdout") or f"Agent exited with code {result['exit_code']}"
            error = raw_error[:2000]
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


async def stop_agent_task(agent_id):
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
        "error_message = 'stopped via dashboard' WHERE id = $1",
        agent_id,
    )
    await log_event("agent", "info", f"agent_{agent_id}", "agent_stopped",
                    f"task_{task['id']}")

    return {"status": "stopped", "task_id": task["id"]}


async def get_process_snapshot():
    """Return Claude/process diagnostics from inside the runner container."""
    ps_path = shutil.which("ps")
    if not ps_path:
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
            if "claude" in line.lower() or "node" in line.lower() or "bun" in line.lower()
        ]
        return {
            "ps_path": ps_path,
            "exit_code": completed.returncode,
            "header": header,
            "processes": rows,
            "active_processes": list(_active_processes.keys()),
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
    return config.get("models", ["qwen/qwen3.6-27b"])


async def get_runner_health():
    """Return local runner diagnostics without making an LLM request."""
    config = _load_model_config()
    settings_path = os.path.expanduser("~/.claude/settings.json")
    creds_path = os.path.expanduser("~/.claude/.credentials.json")
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
        "settings_path": settings_path,
        "settings_exists": os.path.exists(settings_path),
        "credentials_path": creds_path,
        "credentials_exists": os.path.exists(creds_path),
        "settings_anthropic_base_url": settings_base_url,
        "effective_anthropic_base_url": effective_base_url,
        "model_api": model_api,
        "models": config.get("models", []),
        "default_model": config.get("default"),
        "work_base": AGENT_WORK_BASE,
        "max_concurrent_agents": MAX_CONCURRENT_AGENTS,
        "timeout_minutes": AGENT_TIMEOUT_MINUTES,
        "permission_mode": AGENT_PERMISSION_MODE,
        "allowed_tools": AGENT_ALLOWED_TOOLS,
        "harness": AGENT_HARNESS,
        "available_harnesses": list_harnesses(),
        "ps_path": shutil.which("ps"),
        "dashboard_api_base": DASHBOARD_API_BASE,
    }
