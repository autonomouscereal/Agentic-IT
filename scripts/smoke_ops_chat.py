#!/usr/bin/env python3
"""Smoke test Ops Chat ticket creation and real harness queue handoff."""
import json
import os
import sys
import time
import urllib.error
import urllib.request


BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:25480").rstrip("/")
SERVICE_TOKEN = os.environ.get("DASHBOARD_SERVICE_TOKEN", "")
SPAWN_AGENT = os.environ.get("OPS_CHAT_SMOKE_SPAWN_AGENT", "true").lower() not in ("0", "false", "no", "off")


def request(method, path, payload=None, bearer=False):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if SERVICE_TOKEN:
        if bearer:
            headers["Authorization"] = f"Bearer {SERVICE_TOKEN}"
        else:
            headers["X-Dashboard-Service-Token"] = SERVICE_TOKEN
    req = urllib.request.Request(BASE + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as res:
            return json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed: HTTP {exc.code}: {body}") from exc


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def main():
    stamp = int(time.time())
    message = f"I cannot log into my account before a customer call. Demo marker ops-chat-{stamp}."
    direct = request("POST", "/api/ops-chat/message", {
        "message": message,
        "requester_name": "Demo User",
        "requester_email": "demo@example.invalid",
        "spawn_agent": SPAWN_AGENT,
    })
    require(direct.get("created_ticket"), f"Ops Chat did not create ticket: {direct}")
    ticket_id = direct.get("ticket_id")
    if SPAWN_AGENT:
        require((direct.get("agent") or {}).get("agent_id"), f"Ops Chat did not queue real agent harness work: {direct}")
    context = request("GET", f"/api/tickets/{ticket_id}/context")
    notes = context.get("notes") or []
    require(any(
        "Ops Chat agent-created ticket" in str(note.get("body", "")) or
        "Ops Chat agent intake decision" in str(note.get("body", ""))
        for note in notes
    ), "ticket context missing Ops Chat agent-created ticket note")
    health = request("GET", "/api/ops-chat/matrix/health")
    require(health.get("client") == "Matrix Synapse + Element", f"unexpected chat health: {health}")

    follow = request("POST", "/api/ops-chat/message", {
        "session_id": direct.get("session_id"),
        "message": f"Follow-up for ops-chat-{stamp}: I can receive SMS MFA codes.",
        "requester_name": "Demo User",
        "requester_email": "demo@example.invalid",
        "spawn_agent": SPAWN_AGENT,
    })
    require(follow.get("continued_ticket"), f"Ops Chat follow-up did not continue existing ticket: {follow}")
    print(json.dumps({
        "status": "passed",
        "base": BASE,
        "direct_ticket_id": ticket_id,
        "agent": direct.get("agent"),
        "follow_up": follow.get("reply", "")[:180],
    }, indent=2))


if __name__ == "__main__":
    main()
