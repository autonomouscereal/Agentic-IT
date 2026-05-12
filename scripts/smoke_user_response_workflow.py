#!/usr/bin/env python3
"""Smoke test awaiting-user-response ticket workflow.

This is intentionally control-plane only by default: it proves an agent or
operator can request clarifying information, the ticket moves to
awaiting_user_response, a requester response is recorded as a note, and the
ticket returns to work without needing a fragile in-model polling loop.
"""
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
    with urllib.request.urlopen(req, timeout=45) as resp:
        return json.loads(resp.read().decode("utf-8"))


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def main():
    ticket = request("POST", "/api/tickets", {
        "title": "Awaiting user response smoke",
        "description": "Requester omitted the affected host and error details.",
        "ticket_class": "UserRequest",
        "priority": "P3",
        "created_by": "awaiting-user-smoke",
    })
    ticket_id = ticket.get("id")
    require(ticket_id, f"ticket create failed: {ticket}")

    ask = request("POST", f"/api/tickets/{ticket_id}/request-info", {
        "question": "Which hostname is affected, and what exact error message do you see?",
        "requested_by": "awaiting-user-smoke",
        "contact_method": "email",
        "recipient": "smoke@example.local",
        "context": "Need this before routing to endpoint support.",
    })
    require(ask.get("status") == "awaiting_user_response", f"request-info failed: {ask}")

    awaiting = request("GET", f"/api/tickets/{ticket_id}")
    require(awaiting.get("status") == "awaiting_user_response", f"ticket did not wait: {awaiting}")

    answer = request("POST", f"/api/tickets/{ticket_id}/user-response", {
        "response": "The affected host is DEMO-LAPTOP-44 and the error is VPN DNS lookup failed.",
        "responder_name": "Smoke Test User",
        "responder_email": "smoke@example.local",
        "resume_agent": False,
    })
    require(answer.get("status") == "user_response_recorded", f"user-response failed: {answer}")

    context = request("GET", f"/api/tickets/{ticket_id}/context")
    notes = context.get("notes", [])
    require(any("Awaiting user response" in n.get("body", "") for n in notes), "missing outbound request note")
    require(any("DEMO-LAPTOP-44" in n.get("body", "") for n in notes), "missing inbound response note")

    restored = request("GET", f"/api/tickets/{ticket_id}")
    require(restored.get("status") != "awaiting_user_response", f"ticket still awaiting user: {restored}")
    print(json.dumps({
        "ok": True,
        "ticket_id": ticket_id,
        "request_note_id": ask.get("note_id"),
        "response_note_id": answer.get("note_id"),
        "final_status": restored.get("status"),
    }))


if __name__ == "__main__":
    main()
