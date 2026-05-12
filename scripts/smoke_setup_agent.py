#!/usr/bin/env python3
"""Create a setup ticket and run a short model-backed setup agent proof."""
import json
import sys
import time
import urllib.error
import urllib.request


BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://localhost:25480"
MODEL = sys.argv[2] if len(sys.argv) > 2 else "qwen/qwen3.6-27b"


def request(method, path, payload=None, timeout=30):
    data = None
    headers = {}
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


def main():
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
        "ai_base_url": "http://127.0.0.1:4001",
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
    agent_id = spawn["agent_id"]
    task_id = spawn["task_id"]
    print(json.dumps({"ticket_id": ticket_id, "agent_id": agent_id, "task_id": task_id, "model": MODEL}))

    deadline = time.time() + 720
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
        time.sleep(10)

    request("POST", f"/api/agents/{agent_id}/stop", {"reason": "setup_agent_smoke_timeout"})
    raise SystemExit("Timed out waiting for setup agent smoke")


if __name__ == "__main__":
    main()
