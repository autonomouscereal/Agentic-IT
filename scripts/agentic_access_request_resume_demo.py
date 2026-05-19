#!/usr/bin/env python3
"""Run a real local-model permission-wall -> access approval -> resume proof."""
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dashboard_auth import dashboard_auth_headers


BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://localhost:25480"
MODEL = sys.argv[2] if len(sys.argv) > 2 else "qwen/qwen3.6-27b"
WAIT_SECONDS = int(os.environ.get("ACCESS_AGENT_WAIT_SECONDS", "3600"))
IDLE_WAIT_SECONDS = int(os.environ.get("ACCESS_AGENT_IDLE_WAIT_SECONDS", "3600"))
POLL_SECONDS = int(os.environ.get("ACCESS_AGENT_POLL_SECONDS", "15"))
STOP_ON_TIMEOUT = os.environ.get("ACCESS_AGENT_STOP_ON_TIMEOUT", "").lower() in ("1", "true", "yes")


def request(method, path, payload=None, timeout=45):
    data = None
    headers = dashboard_auth_headers(
        provider="access-request-resume-proof",
        content_type=payload is not None,
    )
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed {exc.code}: {body}") from exc


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
                    }
                    for row in active.get("agents", [])
                ],
            }))
            request("POST", "/api/agents/audits/run", {})
            last_count = count
        if count == 0:
            return
        time.sleep(POLL_SECONDS)
    raise SystemExit("Agent lane did not become idle before access-resume proof")


def latest_task(agent_id):
    tasks = request("GET", f"/api/agents/tasks?agent_id={agent_id}")
    rows = tasks.get("tasks") or []
    return rows[0] if rows else {}


def notes_for(ticket_id):
    context = request("GET", f"/api/tickets/{ticket_id}/context")
    return context, "\n".join(note.get("body", "") for note in context.get("notes", []))


def wait_for_access_gate(ticket_id, agent_id, task_id):
    deadline = time.time() + WAIT_SECONDS
    last = None
    while time.time() < deadline:
        task = latest_task(agent_id)
        access = request("GET", f"/api/tickets/{ticket_id}/access-requests")
        status = task.get("status")
        current = (status, access.get("total", 0))
        if current != last:
            print(json.dumps({
                "phase": "waiting_for_access_gate",
                "task_id": task_id,
                "task_status": status,
                "progress_pct_ui_hint": task.get("progress_pct"),
                "access_request_count": access.get("total", 0),
            }))
            last = current
        if access.get("total", 0) > 0 and status in ("awaiting_access", "pending_approval", "blocked", "failed", "completed"):
            return task, access
        time.sleep(POLL_SECONDS)
    raise SystemExit("Timed out waiting for the first agent to create an access request")


def wait_for_resume_completion(ticket_id, original_agent_id):
    deadline = time.time() + WAIT_SECONDS
    seen = set()
    while time.time() < deadline:
        ticket = request("GET", f"/api/tickets/{ticket_id}")
        current_agent_id = ticket.get("agent_id") or ticket.get("agent_instance_id")
        context, note_text = notes_for(ticket_id)
        access = context.get("access_requests") or []
        granted = any(row.get("status") == "granted" for row in access)
        complete = "ACCESS RESUME COMPLETE" in note_text and granted and ticket.get("status") == "resolved"
        key = (current_agent_id, ticket.get("status"), granted, complete)
        if key not in seen:
            print(json.dumps({
                "phase": "waiting_for_resume_completion",
                "current_agent_id": current_agent_id,
                "original_agent_id": original_agent_id,
                "ticket_status": ticket.get("status"),
                "access_granted": granted,
                "final_note_seen": "ACCESS RESUME COMPLETE" in note_text,
            }))
            seen.add(key)
        if complete:
            return {"ticket": ticket, "context": context, "current_agent_id": current_agent_id}
        time.sleep(POLL_SECONDS)
    if STOP_ON_TIMEOUT:
        ticket = request("GET", f"/api/tickets/{ticket_id}")
        if ticket.get("agent_id"):
            request("POST", f"/api/agents/{ticket['agent_id']}/stop", {
                "reason": "access_resume_demo_wait_window_expired",
            })
    raise SystemExit("Timed out waiting for resumed agent completion")


def main():
    wait_for_idle_agent_lane()
    marker = f"ACCESS_RESUME_{int(time.time())}"
    ticket = request("POST", "/api/tickets", {
        "title": f"Agent permission wall resume proof {marker}",
        "description": (
            "Synthetic real-agent proof. The agent must simulate a 403 permission "
            "wall for GitLab repository access, create an access request, wait for "
            "approval, then resume and finish after the grant."
        ),
        "ticket_class": "UserRequest",
        "status": "new",
        "priority": "P3",
        "provider": "local",
        "sync_provider": False,
        "created_by": "agentic-access-resume-demo",
        "auto_assign": False,
    })
    ticket_id = ticket["id"]

    prompt = f"""Use only the dashboard API at http://localhost:8000. This is a lab-safe permission-wall proof for ticket {ticket_id}.

Do exactly this:
1. Read checkpoint.json directly.
2. GET http://localhost:8000/api/tickets/{ticket_id} and remember agent_instance_id as your real agent_id.
3. GET http://localhost:8000/api/tickets/{ticket_id}/context.
4. If the context does not show an access request with status approved or granted, simulate this precise blocker: GitLab API returned 403 ACCESS_DENIED for project demo/private-infra marker {marker}. POST a ticket note saying "PERMISSION WALL {marker}: GitLab repository read is blocked by missing Developer access." Then POST /api/tickets/{ticket_id}/access-request with JSON fields agent_id, resource "GitLab project demo/private-infra", permission "Developer repository read access", account_ref "agent-{{agent_id}}", assignment_group "DevSecOps", risk_level "medium", sync_provider false, reason "403 ACCESS_DENIED marker {marker}; need least-privilege read access before repository evidence can be reviewed." Then write checkpoint.json with step "waiting-for-access-{marker}", status "waiting_for_access", progress_pct 45, output "waiting for DevSecOps access approval {marker}", and a timestamp. Reply exactly "waiting for access {marker}" and stop.
5. If the context shows the access request is approved or granted, find its change_id. If the change status is approved, POST /api/changes/{{change_id}}/complete with completed_by "agent-{{agent_id}}" and result "Lab-safe repository access grant verified for {marker}; no production permissions changed." Then POST a ticket note with body "ACCESS RESUME COMPLETE {marker}: repository evidence reviewed after approved lab-safe access grant; original task can proceed." Then create status_payload.json with status "resolved", actor "agent-{{agent_id}}", reason "ACCESS RESUME COMPLETE {marker}: approved access grant verified and original task completed.", and close_provider false. POST that file to /api/tickets/{ticket_id}/status. Then write checkpoint.json with step "access-resume-complete-{marker}", status "done", progress_pct 100, output "ACCESS RESUME COMPLETE {marker}", and a timestamp. Reply exactly "ACCESS RESUME COMPLETE {marker}".
"""
    spawn = request("POST", f"/api/tickets/{ticket_id}/assign-agent", {
        "model": MODEL,
        "prompt": prompt,
    })
    agent_id = spawn["agent_id"]
    task_id = spawn["task_id"]
    print(json.dumps({
        "spawned": True,
        "ticket_id": ticket_id,
        "agent_id": agent_id,
        "task_id": task_id,
        "marker": marker,
    }))

    task, access = wait_for_access_gate(ticket_id, agent_id, task_id)
    if task.get("status") == "completed":
        raise SystemExit(f"First agent completed instead of waiting for access: {task}")
    access_rows = access.get("access_requests") or []
    access_row = access_rows[0]
    change_id = access_row.get("change_id")
    if not change_id:
        raise SystemExit(f"Access request missing change_id: {access}")

    approved = request("POST", f"/api/changes/{change_id}/approve", {
        "approved_by": "access-demo-approver",
        "reason": f"Lab approval for least-privilege DevSecOps access marker {marker}.",
    })
    print(json.dumps({"approved": approved, "change_id": change_id}))

    final = wait_for_resume_completion(ticket_id, agent_id)
    context = final["context"]
    access_final = context.get("access_requests") or []
    notes = context.get("notes") or []
    tasks = context.get("tasks") or []
    print(json.dumps({
        "ok": True,
        "marker": marker,
        "ticket_id": ticket_id,
        "original_agent_id": agent_id,
        "resumed_agent_id": final.get("current_agent_id"),
        "access_request_id": access_row.get("id"),
        "access_ticket_id": access_row.get("access_ticket_id"),
        "change_id": change_id,
        "access_statuses": [row.get("status") for row in access_final],
        "note_ids": [note.get("id") for note in notes if marker in note.get("body", "")],
        "task_statuses": [{"id": task.get("id"), "agent_id": task.get("agent_id"), "status": task.get("status")} for task in tasks],
    }, indent=2))


if __name__ == "__main__":
    main()
