#!/usr/bin/env python3
"""Smoke test the service desk intake, RACI routing, ticket creation, and approval gate."""
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

    submit = request("POST", "/api/intake/submit", {
        "requester_name": "Smoke Test User",
        "requester_email": "smoke@example.local",
        "title": "Smoke phishing report",
        "message": "Smoke user reported phishing email with bad link and attachment.",
        "attachments": [{"filename": "reported-message.eml", "content_type": "message/rfc822"}],
        "sync_provider": False,
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
    }))


if __name__ == "__main__":
    main()
