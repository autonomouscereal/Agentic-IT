#!/usr/bin/env python3
"""Real local-agent proof for non-interrupting ticket note steering.

The proof runs one active ticket agent, adds a dashboard note while it is
running, then adds an iTop public-log note and syncs it back into the dashboard.
The agent must observe both updates through its workspace steering inbox and
still complete the original ticket objective.
"""
import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dashboard_auth import dashboard_auth_headers


def request(base, method, path, payload=None, expect=(200,)):
    data = None
    headers = dashboard_auth_headers(provider="note-steering-proof")
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(base.rstrip("/") + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            status = resp.status
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        status = exc.code
    if status not in expect:
        raise RuntimeError(f"{method} {path} returned HTTP {status}: {body[:1000]}")
    return json.loads(body) if body else {}


def note_bodies(context):
    return "\n".join(row.get("body") or "" for row in context.get("notes") or [])


def latest_task(base, agent_id):
    tasks = request(base, "GET", f"/api/agents/tasks?agent_id={agent_id}")
    rows = tasks.get("tasks") or []
    return rows[0] if rows else {}


def wait_for_note(base, ticket_id, marker, timeout=900):
    start = time.time()
    last = None
    while time.time() - start < timeout:
        context = request(base, "GET", f"/api/tickets/{ticket_id}/context")
        notes = note_bodies(context)
        if marker in notes:
            return context
        ticket = context.get("ticket") or {}
        agent_id = ticket.get("agent_id")
        task = latest_task(base, agent_id) if agent_id else {}
        if task.get("status") in {"failed", "stopped", "terminated"}:
            raise RuntimeError(f"agent ended before note {marker}: {task}")
        last = {
            "ticket_status": ticket.get("status"),
            "task_status": task.get("status"),
            "task_progress": task.get("progress_pct"),
            "note_tail": notes[-500:],
        }
        print(json.dumps({"waiting_for": marker, "last": last}), flush=True)
        time.sleep(8)
    raise TimeoutError(f"note not observed: {marker}; last={last}")


def wait_for_active_process(base, task_id, timeout=300):
    start = time.time()
    while time.time() - start < timeout:
        snapshot = request(base, "GET", "/api/agents/processes")
        if task_id in (snapshot.get("active_processes") or []):
            return snapshot
        time.sleep(3)
    raise TimeoutError(f"task {task_id} did not appear in active_processes")


def wait_for_task_done(base, agent_id, marker, timeout=900):
    start = time.time()
    last = None
    expected_step = f"note-steering-complete-{marker}"
    while time.time() - start < timeout:
        task = latest_task(base, agent_id)
        checkpoints = task.get("checkpoints") or []
        checkpoint_text = json.dumps(checkpoints, default=str)
        status = task.get("status")
        progress = int(task.get("progress_pct") or 0)
        if status == "completed" and progress >= 100 and expected_step in checkpoint_text:
            return task
        if status in {"failed", "stopped", "terminated"}:
            raise RuntimeError(f"agent ended before terminal steering checkpoint: {task}")
        last = {
            "task_status": status,
            "task_progress": task.get("progress_pct"),
            "checkpoint_tail": checkpoint_text[-500:],
        }
        print(json.dumps({"waiting_for_task_done": marker, "last": last}), flush=True)
        time.sleep(10)
    raise TimeoutError(f"agent did not reach terminal steering checkpoint: {marker}; last={last}")


def add_dashboard_note(base, ticket_id, marker):
    return request(base, "POST", f"/api/tickets/{ticket_id}/notes", {
        "body": f"DASHBOARD_STEER {marker}: requester clarified scope. Keep the original objective, but prioritize the Team Y VPN segment and mention the scope change in final evidence.",
        "author": "dashboard-operator",
        "source": "dashboard",
        "visibility": "internal",
    })


def add_itop_public_log(itop_client, ticket_class, provider_ref, marker):
    payload = {
        "public_log": {
            "items": [
                {
                    "message": f"ITOP_STEER {marker}: provider-side update says the requester attached logs and confirmed this is not a global outage."
                }
            ]
        }
    }
    completed = subprocess.run(
        [
            "python3",
            itop_client,
            "update",
            ticket_class,
            str(provider_ref),
            json.dumps(payload),
        ],
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"iTop public_log update failed: {completed.stderr or completed.stdout}")
    parsed = json.loads(completed.stdout)
    if parsed.get("code") != 0:
        raise RuntimeError(f"iTop public_log update rejected: {completed.stdout}")
    return parsed


def build_prompt(ticket_id, marker):
    return f"""
You are proving non-interrupting ticket-note steering for marker {marker}.

Original objective: work ticket {ticket_id} end to end, incorporate live ticket notes from the dashboard and iTop, write clear evidence notes, explicitly update ticket status only when complete, and finish with checkpoint.json at 100%.

Important:
- Do not stop or replace your objective when new notes arrive.
- Read agent_steering_inbox.json before each major step.
- If the inbox does not yet contain the expected marker, keep checking it. Do not mark the ticket complete until both steering updates are observed.
- Use Write to create JSON payload files and Bash curl -d @file for API calls. Do not use inline JSON in Bash.

Steps:
1. Read checkpoint.json and agent_steering_inbox.json.
2. Add a ticket note through POST /api/tickets/{ticket_id}/notes with author agent, source agent, and body exactly: STEERING_READY_DASHBOARD {marker}
3. Re-read agent_steering_inbox.json until it contains DASHBOARD_STEER {marker}.
4. Add a ticket note with author agent, source agent, and body starting exactly: STEERING_OBSERVED_DASHBOARD {marker}
5. Update checkpoint.json with step note-steering-dashboard-{marker}, status running, progress_pct 55, and output saying dashboard steering was incorporated.
6. Add a ticket note through POST /api/tickets/{ticket_id}/notes with author agent, source agent, and body exactly: STEERING_READY_ITOP {marker}
7. Re-read agent_steering_inbox.json until it contains ITOP_STEER {marker}.
8. Add a ticket note with author agent, source agent, and body starting exactly: STEERING_OBSERVED_ITOP {marker}
9. Add a final ticket note with author agent, source agent, and body starting exactly: STEERING_COMPLETE {marker}. Mention that both dashboard and iTop updates were incorporated while preserving the original objective.
10. POST /api/tickets/{ticket_id}/status with status resolved, actor agent, reason STEERING_COMPLETE {marker}, and close_provider false.
11. Write checkpoint.json with step note-steering-complete-{marker}, status done, progress_pct 100, output STEERING_COMPLETE {marker}, and an ISO timestamp.
12. Reply exactly: STEERING_COMPLETE {marker}
""".strip()


def main():
    parser = argparse.ArgumentParser(description="Run real active-agent note steering proof")
    parser.add_argument("base", help="Dashboard API base URL, e.g. http://127.0.0.1:25480")
    parser.add_argument("model", nargs="?", default="qwen/qwen3.6-27b")
    parser.add_argument("--itop-client", default="/home/cereal/SOC_TESTING/itop-deployment/scripts/itop_client.py")
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--marker", default=f"NOTE_STEERING_{int(time.time())}")
    args = parser.parse_args()

    marker = args.marker
    ticket = request(args.base, "POST", "/api/tickets", {
        "title": f"Agent steering proof {marker}",
        "description": "Prove that active agents consume dashboard and provider ticket notes without being stopped or redirected away from the original objective.",
        "ticket_class": "UserRequest",
        "priority": "P3",
        "sync_provider": True,
        "created_by": "agentic-note-steering-demo",
        "auto_assign": False,
    })
    ticket_id = ticket["id"]
    provider_ref = ticket.get("provider_ref") or ticket.get("itop_ref")
    provider_class = ticket.get("provider_class") or ticket.get("itop_class") or "UserRequest"
    print(json.dumps({"ticket_id": ticket_id, "provider_ref": provider_ref, "provider_class": provider_class, "marker": marker}), flush=True)

    spawn = request(args.base, "POST", f"/api/tickets/{ticket_id}/assign-agent", {
        "model": args.model,
        "prompt": build_prompt(ticket_id, marker),
    })
    if spawn.get("error"):
        raise RuntimeError(spawn)
    agent_id = spawn["agent_id"]
    task_id = spawn["task_id"]
    print(json.dumps({"agent_id": agent_id, "task_id": task_id}), flush=True)

    wait_for_active_process(args.base, task_id, timeout=min(300, args.timeout))
    wait_for_note(args.base, ticket_id, f"STEERING_READY_DASHBOARD {marker}", timeout=args.timeout)
    dashboard_note = add_dashboard_note(args.base, ticket_id, marker)
    print(json.dumps({"dashboard_note": dashboard_note}), flush=True)
    wait_for_note(args.base, ticket_id, f"STEERING_OBSERVED_DASHBOARD {marker}", timeout=args.timeout)

    wait_for_note(args.base, ticket_id, f"STEERING_READY_ITOP {marker}", timeout=args.timeout)
    itop_update = add_itop_public_log(args.itop_client, provider_class, provider_ref, marker)
    print(json.dumps({"itop_update_code": itop_update.get("code"), "provider_ref": provider_ref}), flush=True)
    sync = request(args.base, "POST", f"/api/tickets/{ticket_id}/sync")
    print(json.dumps({"sync": sync}), flush=True)
    wait_for_note(args.base, ticket_id, f"STEERING_OBSERVED_ITOP {marker}", timeout=args.timeout)
    wait_for_note(args.base, ticket_id, f"STEERING_COMPLETE {marker}", timeout=args.timeout)
    task = wait_for_task_done(args.base, agent_id, marker, timeout=args.timeout)
    final_context = request(args.base, "GET", f"/api/tickets/{ticket_id}/context")
    steering = request(args.base, "GET", f"/api/agents/{agent_id}/steering")

    result = {
        "status": "passed",
        "marker": marker,
        "ticket_id": ticket_id,
        "provider_ref": provider_ref,
        "agent_id": agent_id,
        "task_id": task_id,
        "task_status": task.get("status"),
        "task_progress": task.get("progress_pct"),
        "steering_events": steering.get("total"),
        "ticket_status": (final_context.get("ticket") or {}).get("status"),
    }
    if task.get("status") != "completed" or int(task.get("progress_pct") or 0) < 100:
        raise RuntimeError({"error": "agent did not complete cleanly", "result": result, "task": task})
    if result["ticket_status"] != "resolved":
        raise RuntimeError({"error": "ticket did not remain locally resolved", "result": result})
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}), file=sys.stderr)
        raise
