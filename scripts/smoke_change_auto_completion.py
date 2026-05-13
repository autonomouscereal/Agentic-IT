#!/usr/bin/env python3
"""Smoke test approved change auto-completion for completed agent tasks.

Run from inside the dashboard API container so it can use the same raw
PostgreSQL connection settings as the service:

    python scripts/smoke_change_auto_completion.py
"""
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def dispatch_to_api_container_if_needed():
    if os.environ.get("DB_HOST") or Path("/app/database.py").exists():
        return
    if not (ROOT / "docker-compose.yml").exists():
        return

    target = "/app/smoke_change_auto_completion.py"
    subprocess.run(
        ["docker", "compose", "cp", str(Path(__file__).resolve()), f"api:{target}"],
        cwd=ROOT,
        check=True,
    )
    completed = subprocess.run(
        ["docker", "compose", "exec", "-T", "api", "python", target],
        cwd=ROOT,
        check=False,
    )
    raise SystemExit(completed.returncode)


dispatch_to_api_container_if_needed()

if Path("/app/database.py").exists():
    sys.path.insert(0, "/app")
else:
    sys.path.insert(0, str(ROOT / "api"))

from database import execute, fetchrow, fetchval
from services import agent_auditor


async def main():
    marker = f"SMOKE-AUTO-COMPLETE-{int(time.time())}"
    ticket_id = await fetchval("""
        INSERT INTO tickets (
            itop_ref, itop_class, title, description, status,
            priority, provider, provider_ref
        )
        VALUES (
            $1, 'Incident', $2, 'Synthetic governance smoke ticket',
            'in_progress', 'P3', 'local', $1
        )
        RETURNING id
    """, marker, "Smoke auto-complete approved change")

    agent_id = await fetchval("""
        INSERT INTO agents (
            ticket_id, model, selected_model, status,
            started_at, finished_at, heartbeat, assigned_by
        )
        VALUES (
            $1, 'qwen/qwen3.6-27b', 'qwen/qwen3.6-27b', 'finished',
            NOW(), NOW(), NOW(), 'smoke-auto-complete'
        )
        RETURNING id
    """, ticket_id)

    checkpoints = [{
        "step": "verified-remediation",
        "status": "done",
        "output": "compile passed; diff reviewed; remediation evidence attached to task output",
        "timestamp": "2026-05-11T00:00:00",
    }]
    task_id = await fetchval("""
        INSERT INTO agent_tasks (
            agent_id, ticket_id, task_type, prompt, status, output,
            checkpoints, progress_pct, work_dir, started_at, completed_at
        )
        VALUES (
            $1, $2, 'ticket_resolution',
            'synthetic approved-change completion test',
            'completed', $3, $4, 100,
            '/app/agent_work/smoke-auto-complete', NOW(), NOW()
        )
        RETURNING id
    """, agent_id, ticket_id,
        "Agent finished approved remediation. Compile passed. Diff showed expected file-only remediation.",
        json.dumps(checkpoints))
    await execute("UPDATE agents SET last_task_id = $1 WHERE id = $2", task_id, agent_id)

    change_id = await fetchval("""
        INSERT INTO change_requests (
            agent_id, ticket_id, action, target, reason, status,
            requested_by, approved_by, approved_at, risk_level,
            approval_policy, requested_at
        )
        VALUES (
            $1, $2, 'Synthetic remediation that requires completion advancement',
            'smoke-control-plane',
            'Verify auditor advances approved changes after completed task',
            'approved', 'smoke', 'smoke', NOW(), 'low', '{}', NOW()
        )
        RETURNING id
    """, agent_id, ticket_id)

    audit = await agent_auditor.audit_once()
    change = await fetchrow(
        "SELECT id, status, result FROM change_requests WHERE id = $1",
        change_id,
    )
    review = await fetchrow("""
        SELECT finding, action_taken
        FROM agent_audit_reviews
        WHERE task_id = $1
        ORDER BY created_at DESC
        LIMIT 1
    """, task_id)

    result = change.get("result") or ""
    passed = change.get("status") == "completed" and "compile passed" in result.lower()
    print(json.dumps({
        "ok": passed,
        "ticket_id": ticket_id,
        "agent_id": agent_id,
        "task_id": task_id,
        "change_id": change_id,
        "audit": audit,
        "change_status": change.get("status"),
        "result_has_evidence": "compile passed" in result.lower(),
        "review": review,
    }, default=str))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
