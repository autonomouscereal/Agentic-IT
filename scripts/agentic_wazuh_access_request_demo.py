#!/usr/bin/env python3
"""Run a real local-model Wazuh access request -> lease -> provider lookup proof."""
import json
import os
import sys
import time
import urllib.error
import urllib.request


BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://localhost:25480"
MODEL = sys.argv[2] if len(sys.argv) > 2 else "qwen/qwen3.6-27b"
WAIT_SECONDS = int(os.environ.get("WAZUH_ACCESS_AGENT_WAIT_SECONDS", "3600"))
IDLE_WAIT_SECONDS = int(os.environ.get("WAZUH_ACCESS_AGENT_IDLE_WAIT_SECONDS", "3600"))
POLL_SECONDS = int(os.environ.get("WAZUH_ACCESS_AGENT_POLL_SECONDS", "15"))
STOP_ON_TIMEOUT = os.environ.get("WAZUH_ACCESS_AGENT_STOP_ON_TIMEOUT", "").lower() in ("1", "true", "yes")


def request(method, path, payload=None, timeout=60, expect=(200,)):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            if response.status not in expect:
                raise RuntimeError(f"{method} {path} returned {response.status}: {body}")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        if exc.code in expect:
            try:
                return json.loads(body) if body else {}
            except json.JSONDecodeError:
                return {"raw": body}
        raise RuntimeError(f"{method} {path} failed {exc.code}: {body}") from exc


def wait_for_idle_agent_lane():
    deadline = time.time() + IDLE_WAIT_SECONDS
    while time.time() < deadline:
        active = request("GET", "/api/agents/active")
        count = active.get("count", 0)
        print(json.dumps({
            "phase": "waiting_for_idle_agent_lane",
            "active_count": count,
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
        if count == 0:
            return
        request("POST", "/api/agents/audits/run", {})
        time.sleep(POLL_SECONDS)
    raise SystemExit("Agent lane did not become idle before Wazuh access proof")


def latest_task(agent_id):
    tasks = request("GET", f"/api/agents/tasks?agent_id={agent_id}")
    rows = tasks.get("tasks") or []
    return rows[0] if rows else {}


def ticket_context(ticket_id):
    return request("GET", f"/api/tickets/{ticket_id}/context")


def wait_for_access_request(ticket_id, agent_id):
    deadline = time.time() + WAIT_SECONDS
    seen = set()
    while time.time() < deadline:
        task = latest_task(agent_id)
        access = request("GET", f"/api/tickets/{ticket_id}/access-requests")
        key = (task.get("status"), access.get("total", 0))
        if key not in seen:
            print(json.dumps({
                "phase": "waiting_for_wazuh_access_request",
                "agent_id": agent_id,
                "task_status": task.get("status"),
                "progress_pct": task.get("progress_pct"),
                "access_request_count": access.get("total", 0),
            }))
            seen.add(key)
        if access.get("total", 0) > 0 and task.get("status") in (
            "awaiting_access",
            "pending_approval",
            "blocked",
            "failed",
            "completed",
        ):
            return task, access
        time.sleep(POLL_SECONDS)
    raise SystemExit("Timed out waiting for Wazuh access request")


def wait_for_completion(ticket_id, original_agent_id, marker):
    deadline = time.time() + WAIT_SECONDS
    seen = set()
    while time.time() < deadline:
        ticket = request("GET", f"/api/tickets/{ticket_id}")
        context = ticket_context(ticket_id)
        note_text = "\n".join(note.get("body", "") for note in context.get("notes", []))
        current_agent_id = ticket.get("agent_id") or ticket.get("agent_instance_id")
        access_granted = any(row.get("status") == "granted" for row in context.get("access_requests", []))
        complete = (
            ticket.get("status") == "resolved"
            and access_granted
            and f"WAZUH ACCESS PROOF COMPLETE {marker}" in note_text
        )
        key = (current_agent_id, ticket.get("status"), access_granted, complete)
        if key not in seen:
            print(json.dumps({
                "phase": "waiting_for_wazuh_completion",
                "current_agent_id": current_agent_id,
                "original_agent_id": original_agent_id,
                "ticket_status": ticket.get("status"),
                "access_granted": access_granted,
                "final_note_seen": f"WAZUH ACCESS PROOF COMPLETE {marker}" in note_text,
            }))
            seen.add(key)
        if complete:
            return {"ticket": ticket, "context": context, "current_agent_id": current_agent_id}
        time.sleep(POLL_SECONDS)
    if STOP_ON_TIMEOUT:
        ticket = request("GET", f"/api/tickets/{ticket_id}")
        if ticket.get("agent_id"):
            request("POST", f"/api/agents/{ticket['agent_id']}/stop", {
                "reason": f"wazuh_access_demo_timeout_{marker}",
            })
    raise SystemExit("Timed out waiting for Wazuh access proof completion")


def main():
    wait_for_idle_agent_lane()
    marker = f"WAZUH_ACCESS_{int(time.time())}"
    ticket = request("POST", "/api/tickets", {
        "title": f"Wazuh access request proof {marker}",
        "description": (
            "Real agentic Wazuh access test. The first agent must hit a denied "
            "Wazuh manager API lease, create an access request without an explicit "
            "lease_request so the control plane inference is tested, then after "
            "approval use the dashboard-gated Wazuh endpoints to read manager/rule evidence."
        ),
        "ticket_class": "Incident",
        "status": "new",
        "priority": "P2",
        "provider": "local",
        "sync_provider": False,
        "created_by": "agentic-wazuh-access-demo",
        "auto_assign": False,
        "owning_group": "Security Operations",
    })
    ticket_id = ticket["id"]

    prompt = f"""Use only the dashboard API at http://localhost:8000 and files in this work directory. This is a real Wazuh access-control proof for ticket {ticket_id}, marker {marker}.

Do not ask for secrets and do not call Wazuh hosts directly. Secret values must never be printed.

First path before approval:
1. Read checkpoint.json directly.
2. GET /api/tickets/{ticket_id} and identify your agent_id from agent_instance_id.
3. POST /api/agents/<agent_id>/vault/lease with JSON {{"system":"wazuh","resource_type":"api","resource_id":"wazuh.manager","action":"read"}}. This should return HTTP 403/missing_agent_vault_lease before approval.
4. Add a ticket note exactly containing: WAZUH PERMISSION WALL {marker}: wazuh.manager API read denied by missing_agent_vault_lease.
5. POST /api/tickets/{ticket_id}/access-request with agent_id, resource "wazuh.manager API", permission "read", account_ref "wazuh.manager", assignment_group "Security Operations", risk_level "low", sync_provider false, reason "WAZUH PERMISSION WALL {marker}: Wazuh manager API read is required to investigate rule 11." Do not include lease_request; this proof intentionally tests dashboard lease inference.
6. Write checkpoint.json with step "waiting-for-wazuh-api-{marker}", status "waiting_for_access", progress_pct 45, output "WAZUH PERMISSION WALL {marker}", and an ISO timestamp. Reply exactly: waiting for wazuh access {marker}

Resume path after approval:
1. GET /api/tickets/{ticket_id}/context and find the access request/change.
2. If the change status is approved, POST /api/changes/<change_id>/complete with completed_by "agent_<agent_id>" and result "WAZUH ACCESS GRANTED {marker}: inferred scoped Wazuh manager API lease approved; no secret values exposed."
3. POST /api/agents/<agent_id>/vault/lease again for Wazuh manager API read. It must now be allowed and return credential_value null.
4. GET /api/agents/<agent_id>/wazuh/manager/status, GET /api/agents/<agent_id>/wazuh/rules/11, and GET /api/agents/<agent_id>/wazuh/alerts/search?rule_id=11&source_ip=192.168.50.115&limit=3.
5. Add a ticket note exactly containing: WAZUH ACCESS PROOF COMPLETE {marker}: lease allowed, secret values were not returned, Wazuh manager status and rule/alert lookups were performed through dashboard-gated audited endpoints.
6. POST /api/tickets/{ticket_id}/status with status "resolved", actor "agent_<agent_id>", reason "WAZUH ACCESS PROOF COMPLETE {marker}: approved access request minted usable Wazuh lease and provider evidence was retrieved.", close_provider false.
7. Write checkpoint.json with step "wazuh-access-complete-{marker}", status "done", progress_pct 100, output "WAZUH ACCESS PROOF COMPLETE {marker}", and an ISO timestamp. Reply exactly: WAZUH ACCESS PROOF COMPLETE {marker}
"""
    spawn = request("POST", f"/api/tickets/{ticket_id}/assign-agent", {
        "model": MODEL,
        "prompt": prompt,
    })
    agent_id = spawn["agent_id"]
    print(json.dumps({
        "spawned": True,
        "ticket_id": ticket_id,
        "agent_id": agent_id,
        "task_id": spawn.get("task_id"),
        "marker": marker,
    }))

    task, access = wait_for_access_request(ticket_id, agent_id)
    if task.get("status") == "completed":
        raise SystemExit(f"First agent completed instead of waiting for access: {task}")
    rows = access.get("access_requests") or []
    if not rows:
        raise SystemExit(f"No access request rows returned: {access}")
    change_id = rows[0].get("change_id")
    if not change_id:
        raise SystemExit(f"Access request missing change_id: {rows[0]}")

    approved = request("POST", f"/api/changes/{change_id}/approve", {
        "approved_by": "wazuh-access-demo-approver",
        "reason": f"Approve inferred least-privilege Wazuh manager read lease for {marker}.",
    })
    print(json.dumps({"approved": approved, "change_id": change_id}))

    final = wait_for_completion(ticket_id, agent_id, marker)
    print(json.dumps({
        "ok": True,
        "marker": marker,
        "ticket_id": ticket_id,
        "original_agent_id": agent_id,
        "final_agent_id": final.get("current_agent_id"),
        "change_id": change_id,
        "ticket_status": final["ticket"].get("status"),
        "access_statuses": [row.get("status") for row in final["context"].get("access_requests", [])],
    }, indent=2))


if __name__ == "__main__":
    main()
