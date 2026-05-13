#!/usr/bin/env python3
"""Real iTop-backed local-agent close proof.

Creates a dashboard ticket through the iTop provider, runs a bounded local
agent that writes evidence notes and a terminal checkpoint, then proves the
dashboard ticket and the iTop object both resolve. This is intentionally not a
local-only smoke.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request


def request(base, method, path, payload=None, timeout=60):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed {exc.code}: {body}") from exc


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def read_itop_object(itop_client, ticket_class, provider_ref):
    result = subprocess.run(
        [
            sys.executable,
            itop_client,
            "get",
            ticket_class,
            str(provider_ref),
            "--fields",
            "id,ref,title,status,solution,resolution_code,last_update",
        ],
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"iTop read failed: {result.stderr or result.stdout}")
    return json.loads(result.stdout)


def latest_task(base, agent_id):
    tasks = request(base, "GET", f"/api/agents/tasks?agent_id={agent_id}")
    rows = tasks.get("tasks") or []
    return rows[0] if rows else {}


def wait_for_idle_agent_lane(base, wait_seconds, poll_seconds):
    deadline = time.time() + wait_seconds
    last_count = None
    while time.time() < deadline:
        active = request(base, "GET", "/api/agents/active")
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
            request(base, "POST", "/api/agents/audits/run", {})
            last_count = count
        if count == 0:
            return
        time.sleep(poll_seconds)
    raise SystemExit("Agent lane did not become idle before iTop close proof spawn")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("base", nargs="?", default="http://localhost:25480")
    parser.add_argument("--model", default="qwen/qwen3.6-27b")
    parser.add_argument("--timeout-seconds", type=int, default=int(os.environ.get("AGENT_SMOKE_WAIT_SECONDS", "3600")))
    parser.add_argument("--idle-wait-seconds", type=int, default=int(os.environ.get("AGENT_SMOKE_IDLE_WAIT_SECONDS", "3600")))
    parser.add_argument("--poll-seconds", type=int, default=int(os.environ.get("AGENT_SMOKE_POLL_SECONDS", "15")))
    parser.add_argument("--stop-on-timeout", action="store_true", default=os.environ.get("AGENT_SMOKE_STOP_ON_TIMEOUT", "").lower() in ("1", "true", "yes"))
    parser.add_argument("--marker", default=f"CODEX_ITOP_CLOSE_PROOF_{int(time.time())}")
    parser.add_argument("--ticket-id", type=int, default=None)
    parser.add_argument(
        "--itop-client",
        default="/home/cereal/SOC_TESTING/itop-deployment/scripts/itop_client.py",
    )
    args = parser.parse_args()
    base = args.base.rstrip("/")

    wait_for_idle_agent_lane(base, args.idle_wait_seconds, args.poll_seconds)

    if args.ticket_id:
        ticket = request(base, "GET", f"/api/tickets/{args.ticket_id}")
    else:
        ticket = request(base, "POST", "/api/tickets", {
            "title": f"{args.marker}: controlled iTop agent completion proof",
            "description": (
                f"Real iTop-backed close proof for {args.marker}. The agent must write "
                "evidence notes, finish with a 100% checkpoint, and the control plane "
                "must resolve the matching iTop object."
            ),
            "ticket_class": "Incident",
            "priority": "P3",
            "provider": "itop",
            "sync_provider": True,
            "auto_assign": False,
            "created_by": "itop-agent-close-e2e",
        })
    ticket_id = ticket["id"]
    require(ticket.get("provider") == "itop", f"ticket did not select itop: {ticket}")
    require(ticket.get("provider_sync_status") == "synced", f"ticket did not sync to iTop: {ticket}")
    provider_ref = ticket.get("provider_ref") or ticket.get("itop_ref")
    provider_class = ticket.get("provider_class") or ticket.get("itop_class")
    require(str(provider_ref).isdigit(), f"missing numeric iTop ref: {ticket}")

    prompt = f"""Do this exact iTop close proof, and do not do anything else:
1. Read checkpoint.json directly.
2. Use this exact API base URL: http://localhost:8000
3. Run: curl -s http://localhost:8000/api/tickets/{ticket_id}/context
4. Post note one with: curl -s -X POST http://localhost:8000/api/tickets/{ticket_id}/notes -H "Content-Type: application/json" -d '{{"author":"agent-itop-close-proof","source":"agent","visibility":"internal","body":"{args.marker} evidence note 1: iTop-backed ticket context read and retained."}}'
5. Post note two with: curl -s -X POST http://localhost:8000/api/tickets/{ticket_id}/notes -H "Content-Type: application/json" -d '{{"author":"agent-itop-close-proof","source":"agent","visibility":"internal","body":"{args.marker} evidence note 2: ready for provider close verification."}}'
6. Create a file named status_payload.json containing exactly this JSON: {{"status":"resolved","actor":"agent-itop-close-proof","reason":"{args.marker} provider close proof complete after retained evidence notes.","close_provider":true}}
7. Run: curl -s -X POST http://localhost:8000/api/tickets/{ticket_id}/status -H "Content-Type: application/json" -d @status_payload.json
8. Read checkpoint.json again, then write checkpoint.json with step complete, status done, progress_pct 100, output "{args.marker} provider close proof complete", and an ISO timestamp.
9. Reply with exactly: {args.marker} provider close proof complete
"""
    spawn = request(base, "POST", f"/api/tickets/{ticket_id}/assign-agent", {
        "model": args.model,
        "prompt": prompt,
    })
    agent_id = spawn["agent_id"]
    task_id = spawn["task_id"]
    print(json.dumps({
        "spawned": True,
        "marker": args.marker,
        "ticket_id": ticket_id,
        "agent_id": agent_id,
        "task_id": task_id,
        "provider_ref": provider_ref,
        "provider_class": provider_class,
    }))

    deadline = time.time() + args.timeout_seconds
    last_status = None
    while time.time() < deadline:
        task = latest_task(base, agent_id)
        status = task.get("status")
        if status != last_status:
            print(json.dumps({
                "task_id": task_id,
                "status": status,
                "progress_pct_ui_hint": task.get("progress_pct"),
                "completed_at": task.get("completed_at"),
            }))
            last_status = status
        if status in ("completed", "failed", "stopped"):
            break
        time.sleep(args.poll_seconds)

    task = latest_task(base, agent_id)
    if task.get("status") != "completed":
        request(base, "POST", "/api/agents/audits/run")
        print(json.dumps({
            "wait_window_expired": True,
            "stop_on_timeout": args.stop_on_timeout,
            "agent_id": agent_id,
            "ticket_id": ticket_id,
            "task": task,
        }, indent=2))
        if args.stop_on_timeout:
            request(base, "POST", f"/api/agents/{agent_id}/stop", {"reason": "itop_agent_close_e2e_wait_window_expired"})
        raise SystemExit(f"agent did not complete: {task}")

    request(base, "POST", "/api/agents/audits/run")
    request(base, "POST", f"/api/tickets/{ticket_id}/sync")
    dashboard_ticket = request(base, "GET", f"/api/tickets/{ticket_id}")
    context = request(base, "GET", f"/api/tickets/{ticket_id}/context")
    note_bodies = [note.get("body", "") for note in context.get("notes", [])]
    require(dashboard_ticket.get("status") == "resolved", f"dashboard ticket not resolved: {dashboard_ticket}")
    require(dashboard_ticket.get("provider_sync_status") == "synced", f"dashboard ticket not synced: {dashboard_ticket}")
    require(any(f"{args.marker} evidence note 1" in body for body in note_bodies), "missing evidence note 1")
    require(any(f"{args.marker} evidence note 2" in body for body in note_bodies), "missing evidence note 2")

    itop = read_itop_object(args.itop_client, provider_class, provider_ref)
    objects = itop.get("objects") or {}
    require(objects, f"iTop object not found: {itop}")
    first = next(iter(objects.values()))
    fields = first.get("fields") or {}
    require(fields.get("status") == "resolved", f"iTop object not resolved: {fields}")
    require(args.marker in (fields.get("solution") or ""), f"iTop solution missing marker: {fields}")

    audits = request(base, "GET", f"/api/agents/audits?agent_id={agent_id}&ticket_id={ticket_id}&limit=5")
    print(json.dumps({
        "status": "ok",
        "marker": args.marker,
        "ticket_id": ticket_id,
        "agent_id": agent_id,
        "task_id": task_id,
        "dashboard_status": dashboard_ticket.get("status"),
        "provider_sync_status": dashboard_ticket.get("provider_sync_status"),
        "itop_class": provider_class,
        "itop_ref": provider_ref,
        "itop_status": fields.get("status"),
        "itop_solution": fields.get("solution"),
        "audit_findings": [row.get("finding") for row in audits.get("audits", [])],
    }, indent=2))


if __name__ == "__main__":
    main()
