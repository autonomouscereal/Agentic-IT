#!/usr/bin/env python3
"""Smoke test the approval-gated static site deployment adapter.

Run from the repo root. If run on the host, the script dispatches itself into
the API container so it uses the deployed raw PostgreSQL runtime.
"""
import asyncio
import json
import os
import ssl
import subprocess
import sys
import time
from pathlib import Path
from urllib import request as urllib_request


ROOT = Path(__file__).resolve().parents[1]


def dispatch_to_api_container_if_needed():
    if os.environ.get("DB_HOST") or Path("/app/database.py").exists():
        return
    if not (ROOT / "docker-compose.yml").exists():
        return

    target = "/app/smoke_static_site_deployment.py"
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
from routes.agents import deploy_static_site


async def main():
    marker = f"STATIC-SITE-DEPLOY-SMOKE-{int(time.time())}"
    slug = marker.lower().replace("_", "-")
    public_base_url = os.environ.get("DASHBOARD_PUBLIC_URL", "https://192.168.50.222:25443").rstrip("/")

    ticket_id = await fetchval("""
        INSERT INTO tickets (
            itop_ref, itop_class, title, description, status,
            priority, provider, provider_ref
        )
        VALUES (
            $1, 'UserRequest', $2, 'Synthetic static deployment adapter smoke',
            'in_progress', 'P3', 'local', $1
        )
        RETURNING id
    """, marker, "Static site deployment adapter smoke")

    agent_id = await fetchval("""
        INSERT INTO agents (
            ticket_id, model, selected_model, harness, status,
            started_at, heartbeat, assigned_by
        )
        VALUES (
            $1, 'smoke', 'smoke', 'smoke', 'working',
            NOW(), NOW(), 'smoke-static-site'
        )
        RETURNING id
    """, ticket_id)

    work_dir = Path(f"/app/agent_work/{agent_id}/static-site-smoke")
    site_dir = work_dir / "hello"
    site_dir.mkdir(parents=True, exist_ok=True)
    (site_dir / "index.html").write_text(
        f"<!doctype html><html><body><h1>{marker}</h1></body></html>\n",
        encoding="utf-8",
    )
    (site_dir / "health.json").write_text(
        json.dumps({"ok": True, "marker": marker}),
        encoding="utf-8",
    )

    task_id = await fetchval("""
        INSERT INTO agent_tasks (
            agent_id, ticket_id, task_type, prompt, status,
            progress_pct, work_dir, started_at
        )
        VALUES (
            $1, $2, 'ticket_resolution',
            'synthetic static-site deployment smoke',
            'working', 50, $3, NOW()
        )
        RETURNING id
    """, agent_id, ticket_id, str(work_dir))
    await execute("UPDATE agents SET last_task_id = $1 WHERE id = $2", task_id, agent_id)

    change_id = await fetchval("""
        INSERT INTO change_requests (
            agent_id, ticket_id, action, target, reason, status,
            requested_by, approved_by, approved_at, risk_level,
            approval_policy, requested_at
        )
        VALUES (
            $1, $2, 'Publish static site through dashboard adapter',
            $3, 'Smoke-test the deployment boundary adapter',
            'approved', 'smoke', 'smoke', NOW(), 'low', '{}', NOW()
        )
        RETURNING id
    """, agent_id, ticket_id, f"/published/{slug}/")

    result = await deploy_static_site(
        agent_id,
        {
            "change_id": change_id,
            "source_dir": "hello",
            "slug": slug,
            "public_base_url": public_base_url,
        },
        None,
    )
    if result.get("status") != "deployed":
        print(json.dumps({"ok": False, "error": result}, default=str))
        raise SystemExit(1)

    change = await fetchrow("SELECT status, result FROM change_requests WHERE id = $1", change_id)
    note = await fetchrow("""
        SELECT body FROM ticket_notes
        WHERE ticket_id = $1 AND source = 'deployment-adapter'
        ORDER BY id DESC LIMIT 1
    """, ticket_id)

    public_url = result["deployment"]["public_url"]
    req = urllib_request.Request(
        public_url,
        headers={"X-Dashboard-Service-Token": os.environ.get("DASHBOARD_SERVICE_TOKEN", "")},
    )
    try:
        ssl_context = ssl._create_unverified_context()
        with urllib_request.urlopen(req, timeout=20, context=ssl_context) as response:
            rendered = response.read().decode("utf-8", errors="replace")
    except Exception as exc:
        rendered = f"FETCH_ERROR: {exc}"

    ok = (
        change
        and change.get("status") == "completed"
        and note
        and "not a transient agent-container preview" in (note.get("body") or "")
        and marker in rendered
    )
    if ok:
        await execute("""
            UPDATE agent_tasks
            SET status = 'completed',
                output = $1,
                progress_pct = 100,
                completed_at = NOW()
            WHERE id = $2
        """, f"Published static site smoke verified: {public_url}", task_id)
        await execute("""
            UPDATE agents
            SET status = 'finished',
                finished_at = NOW(),
                heartbeat = NOW()
            WHERE id = $1
        """, agent_id)
        await execute("""
            UPDATE tickets
            SET status = 'resolved',
                updated_at = NOW()
            WHERE id = $1
        """, ticket_id)
    print(json.dumps({
        "ok": bool(ok),
        "ticket_id": ticket_id,
        "agent_id": agent_id,
        "task_id": task_id,
        "change_id": change_id,
        "public_url": public_url,
        "change_status": change.get("status") if change else None,
        "rendered_marker": marker in rendered,
    }, default=str))
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
