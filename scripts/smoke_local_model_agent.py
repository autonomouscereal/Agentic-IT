"""Spawn a short local-model agent and verify dashboard management.

This intentionally uses qwen/qwen3.6-27b by default because it is the fast local
lane in the current lab. It avoids destructive actions and asks the agent to
exercise ticket context, note writing, and checkpoint completion.

Progress percentage is only a UI hint. This smoke determines health from task
status plus active process, stream log, checkpoint, notes, and audit evidence.
"""
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


def tail(text, limit=3000):
    text = text or ""
    if len(text) <= limit:
        return text
    return text[-limit:]


def collect_agent_evidence(agent_id, ticket_id, task_id):
    tasks = request("GET", f"/api/agents/tasks?agent_id={agent_id}")
    task = (tasks.get("tasks") or [{}])[0]
    logs = request("GET", f"/api/agents/tasks/{task_id}/logs?lines=160")
    context = request("GET", f"/api/tickets/{ticket_id}/context")
    audits = request("GET", f"/api/agents/audits?agent_id={agent_id}&limit=20")
    processes = request("GET", "/api/agents/processes")

    active_processes = processes.get("active_processes") or []
    process_rows = processes.get("processes") or []
    pid = task.get("pid")
    pid_seen = any(str(row.get("pid")) == str(pid) for row in process_rows if pid)

    notes = [
        {
            "id": note.get("id"),
            "author": note.get("author"),
            "source": note.get("source"),
            "body": tail(note.get("body"), 500),
            "created_at": note.get("created_at"),
        }
        for note in context.get("notes", [])
    ]

    return {
        "agent_id": agent_id,
        "ticket_id": ticket_id,
        "task_id": task_id,
        "task_status": task.get("status"),
        "progress_pct_ui_hint": task.get("progress_pct"),
        "pid": pid,
        "work_dir": task.get("work_dir"),
        "checkpoint": task.get("checkpoints"),
        "active_process_tracked": task_id in active_processes,
        "pid_seen_in_container": pid_seen,
        "log_path": logs.get("log_path"),
        "log_tail": tail(logs.get("content")),
        "note_count": len(notes),
        "notes": notes[-5:],
        "audit_count": audits.get("total", 0),
        "audits": audits.get("audits", [])[:5],
    }


def main():
    ticket = request("POST", "/api/tickets", {
        "title": f"Local model agent smoke {int(time.time())}",
        "description": "Agent should read context, add a ticket note, and mark checkpoint done.",
        "ticket_class": "UserRequest",
        "status": "new",
        "provider": "local",
        "sync_provider": False,
        "created_by": "local-model-smoke",
    })
    ticket_id = ticket["id"]

    prompt = f"""Do this exact smoke test, and do not do anything else:
1. Read checkpoint.json directly.
2. Use this exact API base URL: http://localhost:8000
3. Run: curl -s http://localhost:8000/api/tickets/{ticket_id}/context
4. Run: curl -s -X POST http://localhost:8000/api/tickets/{ticket_id}/notes -H "Content-Type: application/json" -d '{{"author":"local-model-smoke","source":"agent","visibility":"internal","body":"local model agent smoke note complete"}}'
5. Read checkpoint.json again, then write checkpoint.json with step local-model-agent-smoke, status done, progress_pct 100, output "local model agent smoke complete", and an ISO timestamp.
6. Reply with exactly: local model agent smoke complete
"""
    spawn = request("POST", f"/api/tickets/{ticket_id}/assign-agent", {
        "model": MODEL,
        "prompt": prompt,
    })
    agent_id = spawn["agent_id"]
    task_id = spawn["task_id"]

    print(json.dumps({"spawned": True, "ticket_id": ticket_id, "agent_id": agent_id, "task_id": task_id, "model": MODEL}))

    deadline = time.time() + 720
    last_status = ""
    while time.time() < deadline:
        tasks = request("GET", f"/api/agents/tasks?agent_id={agent_id}")
        task = (tasks.get("tasks") or [{}])[0]
        status = task.get("status", "")
        progress = task.get("progress_pct", 0)
        if status != last_status:
            evidence = collect_agent_evidence(agent_id, ticket_id, task_id)
            print(json.dumps({
                "task_id": task_id,
                "status": status,
                "progress_pct_ui_hint": progress,
                "active_process_tracked": evidence["active_process_tracked"],
                "pid_seen_in_container": evidence["pid_seen_in_container"],
                "note_count": evidence["note_count"],
                "audit_count": evidence["audit_count"],
            }))
            last_status = status
        if status in ("completed", "failed", "stopped"):
            evidence = collect_agent_evidence(agent_id, ticket_id, task_id)
            note_bodies = [n.get("body", "") for n in evidence.get("notes", [])]
            print(json.dumps({
                "final_status": status,
                "progress_pct_ui_hint": progress,
                "note_written": any("local model agent smoke note complete" in body for body in note_bodies),
                "evidence": evidence,
            }, indent=2))
            if status != "completed":
                raise SystemExit(2)
            return
        time.sleep(10)

    request("POST", f"/api/agents/{agent_id}/stop", {"reason": "local_model_smoke_timeout"})
    raise SystemExit("Timed out waiting for local model agent smoke")


if __name__ == "__main__":
    main()
