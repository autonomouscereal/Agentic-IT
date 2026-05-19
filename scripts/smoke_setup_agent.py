#!/usr/bin/env python3
"""Create a setup ticket and run a short model-backed setup agent proof."""
import json
import os
import sys
import time
import urllib.error
import urllib.request


BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://localhost:25480"
MODEL = sys.argv[2] if len(sys.argv) > 2 else "deepseek/deepseek-v4-flash"
AGENT_WAIT_SECONDS = int(os.environ.get("AGENT_SMOKE_WAIT_SECONDS", "3600"))
IDLE_WAIT_SECONDS = int(os.environ.get("AGENT_SMOKE_IDLE_WAIT_SECONDS", "3600"))
POLL_SECONDS = int(os.environ.get("AGENT_SMOKE_POLL_SECONDS", "15"))
STOP_ON_TIMEOUT = os.environ.get("AGENT_SMOKE_STOP_ON_TIMEOUT", "").lower() in ("1", "true", "yes")
AUTH_USER = os.environ.get("DASHBOARD_SMOKE_USER", "demo_account_1")
AUTH_PROVIDER = os.environ.get("DASHBOARD_SMOKE_PROVIDER", "setup-agent-smoke")
TRUSTED_SECRET = os.environ.get("DASHBOARD_TRUSTED_AUTH_SECRET", "")
SERVICE_TOKEN = os.environ.get("DASHBOARD_SERVICE_TOKEN", "")


def auth_headers():
    if TRUSTED_SECRET:
        return {
            "X-Auth-Request-User": AUTH_USER,
            "X-Auth-Provider": AUTH_PROVIDER,
            "X-Dashboard-Auth-Secret": TRUSTED_SECRET,
        }
    if SERVICE_TOKEN:
        return {
            "X-Dashboard-Service-User": AUTH_PROVIDER,
            "X-Dashboard-Service-Token": SERVICE_TOKEN,
        }
    return {}


def request(method, path, payload=None, timeout=30):
    data = None
    headers = auth_headers()
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed {exc.code}: {body}") from exc


def latest_agent_task(agent_id):
    tasks = request("GET", f"/api/agents/tasks?agent_id={agent_id}")
    rows = tasks.get("tasks") or []
    return rows[0] if rows else {}


def wait_for_idle_agent_lane():
    deadline = time.time() + IDLE_WAIT_SECONDS
    last_count = None
    while time.time() < deadline:
        active = request("GET", "/api/agents/active")
        count = active.get("count", 0)
        if count != last_count:
            print(json.dumps({
                "waiting_for_agent_lane": count,
                "active_agents": [
                    {
                        "id": row.get("id"),
                        "ticket_id": row.get("ticket_id"),
                        "status": row.get("status"),
                        "task_status": row.get("task_status"),
                        "progress_pct_ui_hint": row.get("task_progress_pct"),
                    }
                    for row in active.get("agents", [])
                ],
            }))
            request("POST", "/api/agents/audits/run", {})
            last_count = count
        if count == 0:
            return
        time.sleep(POLL_SECONDS)
    raise SystemExit("Agent lane did not become idle before setup agent smoke spawn")


def main():
    wait_for_idle_agent_lane()
    health = request("GET", "/api/agents/runner-health")
    ai_base_url = health.get("effective_anthropic_base_url") or "http://ai-proxy:4001"
    harness = health.get("harness") or "hermes"

    setup = request("POST", "/api/setup/ticket", {
        "profile": "soc",
        "existing_tools": [
            "ticketing-provider-adapter",
            "siem-provider-adapter",
            "edr-provider-adapter",
            "email-security-provider-adapter",
            "identity-provider-adapter",
        ],
        "deploy_missing": False,
        "ai_base_url": ai_base_url,
        "proxy_mode": "deploy",
        "proxy_url": ai_base_url,
        "harness": harness,
        "provider": "lmstudio" if MODEL.startswith("qwen/") else "nous",
        "model": MODEL,
        "notes": "Smoke test: validate setup-ticket context and provider-agnostic plan without deploying anything.",
        "spawn_agent": False,
        "sync_provider": False,
    })
    ticket_id = setup["ticket"]["id"]

    prompt = f"""Do this exact setup-agent smoke test and do not deploy anything:
1. Read checkpoint.json directly.
2. Run: curl -s http://localhost:8000/api/tickets/{ticket_id}/context
3. Run: curl -s -X POST http://localhost:8000/api/tickets/{ticket_id}/notes -H "Content-Type: application/json" -d '{{"author":"setup-agent-smoke","source":"agent","visibility":"internal","body":"setup agent smoke verified provider-agnostic setup context without deployment"}}'
4. Write checkpoint.json with step setup-agent-smoke, status done, progress_pct 100, output "setup agent smoke complete", and an ISO timestamp.
5. Reply with exactly: setup agent smoke complete
"""
    spawn = request("POST", f"/api/tickets/{ticket_id}/assign-agent", {
        "model": MODEL,
        "prompt": prompt,
    })
    if "agent_id" not in spawn or "task_id" not in spawn:
        agent_id = spawn.get("agent_id")
        task = latest_agent_task(agent_id) if agent_id else {}
        if not agent_id or not task.get("id"):
            raise SystemExit(f"agent spawn failed or was deferred: {spawn}")
        task_id = task["id"]
        print(json.dumps({
            "attached_to_existing_agent": True,
            "ticket_id": ticket_id,
            "agent_id": agent_id,
            "task_id": task_id,
            "spawn_response": spawn,
        }))
    else:
        agent_id = spawn["agent_id"]
        task_id = spawn["task_id"]
    print(json.dumps({"ticket_id": ticket_id, "agent_id": agent_id, "task_id": task_id, "model": MODEL}))

    deadline = time.time() + AGENT_WAIT_SECONDS
    last_status = ""
    while time.time() < deadline:
        tasks = request("GET", f"/api/agents/tasks?agent_id={agent_id}")
        task = (tasks.get("tasks") or [{}])[0]
        status = task.get("status", "")
        if status != last_status:
            print(json.dumps({"task_id": task_id, "status": status, "progress": task.get("progress_pct", 0)}))
            last_status = status
        if status in ("completed", "failed", "stopped"):
            context = request("GET", f"/api/tickets/{ticket_id}/context")
            note_written = any(
                "setup agent smoke verified provider-agnostic setup context" in note.get("body", "")
                for note in context.get("notes", [])
            )
            result = {
                "status": status,
                "ticket_id": ticket_id,
                "note_written": note_written,
                "processes": request("GET", "/api/agents/processes"),
            }
            print(json.dumps(result, indent=2))
            if status != "completed" or not note_written:
                raise SystemExit(2)
            return
        time.sleep(POLL_SECONDS)

    request("POST", "/api/agents/audits/run", {})
    print(json.dumps({
        "wait_window_expired": True,
        "stop_on_timeout": STOP_ON_TIMEOUT,
        "agent_id": agent_id,
        "ticket_id": ticket_id,
        "task_id": task_id,
        "task": request("GET", f"/api/agents/tasks?agent_id={agent_id}"),
    }, indent=2))
    if STOP_ON_TIMEOUT:
        request("POST", f"/api/agents/{agent_id}/stop", {"reason": "setup_agent_smoke_wait_window_expired"})
    raise SystemExit("Setup agent smoke wait window expired")


if __name__ == "__main__":
    main()
