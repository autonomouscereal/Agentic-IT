#!/usr/bin/env python3
"""Smoke test service desk intake, RACI CRUD, auto-classification, provider sync, and approval gate."""
import json
import sys
import urllib.request


BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:25480").rstrip("/")


def request(method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def main():
    raci = request("GET", "/api/intake/raci")
    require(len(raci.get("groups", [])) >= 10, "expected seeded service groups")
    require(any(rule.get("intent") == "phishing" for rule in raci.get("rules", [])), "missing phishing RACI rule")

    classify = request("POST", "/api/intake/classify", {
        "title": "Suspicious email with bad link",
        "message": "User reported a phishing email with a bad link and suspicious sender headers.",
    })
    classification = classify.get("classification", {})
    require(classification.get("intent") == "phishing", f"expected phishing, got {classification}")
    require(classification.get("ticket_class") == "Incident", "phishing should route as Incident")
    require(classification.get("approval_required") is True, "phishing remediation should require approval")
    require(classification.get("auto_assign_agent") is True, "phishing RACI rule should enable auto agent assignment")

    clarify = request("POST", "/api/intake/clarify", {
        "title": "Suspicious email",
        "message": "User says there was a weird email.",
        "requester_email": "smoke@example.local",
    })
    require("questions" in clarify, f"clarify failed: {clarify}")

    stamp = str(len(raci.get("rules", [])) + len(raci.get("groups", [])))
    group = request("POST", "/api/intake/raci/groups", {
        "name": f"Smoke RACI Group {stamp}",
        "description": "Temporary smoke-test group",
        "default_assignee": "smoke-operator",
        "risk_level": "low",
    })
    require(group.get("id"), f"group create failed: {group}")
    rule = request("POST", "/api/intake/raci/rules", {
        "name": f"Smoke RACI Rule {stamp}",
        "intent": "smoke-intake",
        "keywords": ["smoke-raci-keyword"],
        "ticket_class": "UserRequest",
        "priority": "P4",
        "assignment_group": f"Smoke RACI Group {stamp}",
        "responsible": f"Smoke RACI Group {stamp}",
        "accountable": "Smoke Owner",
        "consulted": [],
        "informed": [],
        "approval_required": False,
        "risk_level": "low",
        "knowledge_tags": ["smoke"],
        "auto_assign_agent": False,
    })
    require(rule.get("id"), f"rule create failed: {rule}")
    updated = request("PUT", f"/api/intake/raci/rules/{rule['id']}", {"priority": "P3"})
    require(updated.get("status") == "updated", f"rule update failed: {updated}")
    disabled = request("DELETE", f"/api/intake/raci/rules/{rule['id']}")
    require(disabled.get("status") == "disabled", f"rule disable failed: {disabled}")

    submit = request("POST", "/api/intake/submit", {
        "requester_name": "Smoke Test User",
        "requester_email": "smoke@example.local",
        "title": "Smoke phishing report",
        "message": "Smoke user reported phishing email with bad link and attachment.",
        "attachments": [{"filename": "reported-message.eml", "content_type": "message/rfc822"}],
        "auto_assign": False,
    })
    ticket_id = submit.get("ticket", {}).get("id")
    require(ticket_id, f"intake did not create ticket: {submit}")
    require(submit.get("change_id"), "approval-gated phishing intake should create a change request")

    context = request("GET", f"/api/tickets/{ticket_id}/context")
    require(any("Service desk intake classification" in note.get("body", "") for note in context.get("notes", [])), "missing intake note")
    require(context.get("attachments"), "missing attachment metadata")

    sessions = request("GET", "/api/intake/sessions?limit=10")
    require(any(row.get("ticket_id") == ticket_id for row in sessions.get("sessions", [])), "missing intake session")
    print(json.dumps({
        "ok": True,
        "ticket_id": ticket_id,
        "change_id": submit.get("change_id"),
        "intent": submit.get("classification", {}).get("intent"),
        "provider_sync_status": submit.get("ticket", {}).get("provider_sync_status"),
        "auto_assignment": submit.get("auto_assignment", {}),
        "raci_rule_id": rule.get("id"),
    }))


if __name__ == "__main__":
    main()
