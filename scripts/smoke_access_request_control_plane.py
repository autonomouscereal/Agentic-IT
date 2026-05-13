#!/usr/bin/env python3
"""Smoke test account access request tickets and approval gates."""
import json
import sys
import time
import urllib.error
import urllib.request


BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:25480").rstrip("/")


def request(method, path, body=None, timeout=60):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed {exc.code}: {payload}") from exc


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def main():
    marker = f"ACCESS-CONTROL-PLANE-{int(time.time())}"
    ticket = request("POST", "/api/tickets", {
        "title": f"Access request control-plane smoke {marker}",
        "description": "Synthetic ticket that needs repository access before work can continue.",
        "ticket_class": "UserRequest",
        "priority": "P3",
        "provider": "local",
        "sync_provider": False,
        "created_by": "access-request-smoke",
        "auto_assign": False,
    })
    ticket_id = ticket.get("id")
    require(ticket_id, f"ticket create failed: {ticket}")

    access = request("POST", f"/api/tickets/{ticket_id}/access-request", {
        "resource": "GitLab project demo/private-infra",
        "permission": "Developer repository access",
        "reason": f"Agent received a 403 while reading the repository. Marker: {marker}",
        "requester": "access-request-smoke",
        "account_ref": "agent-smoke",
        "assignment_group": "DevSecOps",
        "risk_level": "medium",
        "sync_provider": False,
        "created_by": "access-request-smoke",
    })
    require(access.get("status") == "pending_approval", f"access request failed: {access}")
    access_request_id = access.get("access_request_id")
    change_id = access.get("change_id")
    access_ticket_id = access.get("access_ticket_id")
    require(access_request_id and change_id and access_ticket_id, f"missing ids: {access}")

    listed = request("GET", f"/api/tickets/{ticket_id}/access-requests")
    require(listed.get("total", 0) >= 1, f"access request not listed: {listed}")

    approved = request("POST", f"/api/changes/{change_id}/approve", {
        "approved_by": "access-smoke-approver",
        "reason": "Lab approval for least-privilege repository access.",
    })
    require(approved.get("status") == "approved", f"approve failed: {approved}")

    completed = request("POST", f"/api/changes/{change_id}/complete", {
        "completed_by": "access-smoke-iam",
        "result": f"Lab-safe grant recorded for {marker}; no production permission changed.",
    })
    require(completed.get("status") == "completed", f"complete failed: {completed}")

    after = request("GET", f"/api/tickets/{ticket_id}/access-requests")
    record = next((row for row in after.get("access_requests", []) if row.get("id") == access_request_id), None)
    require(record and record.get("status") == "granted", f"access request not granted: {after}")

    context = request("GET", f"/api/tickets/{ticket_id}/context")
    notes = "\n".join(note.get("body", "") for note in context.get("notes", []))
    require("Access request opened" in notes, "missing parent access request note")
    require("Access granted" in notes, "missing access granted note")

    print(json.dumps({
        "ok": True,
        "ticket_id": ticket_id,
        "access_request_id": access_request_id,
        "access_ticket_id": access_ticket_id,
        "change_id": change_id,
        "status": record.get("status"),
    }, indent=2))


if __name__ == "__main__":
    main()
