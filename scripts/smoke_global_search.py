#!/usr/bin/env python3
"""Smoke test authenticated global dashboard search."""
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:25480").rstrip("/")
SERVICE_TOKEN = os.environ.get("DASHBOARD_SERVICE_TOKEN", "")


def request(method, path, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={
            "Content-Type": "application/json",
            **({"X-Dashboard-Service-Token": SERVICE_TOKEN} if SERVICE_TOKEN else {}),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed: HTTP {exc.code}: {body}") from exc


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def main():
    stamp = int(time.time())
    marker = f"global-search-smoke-{stamp}"
    ticket = request("POST", "/api/tickets", {
        "title": f"Global search smoke {stamp}",
        "description": f"Searchable marker {marker} for dashboard global search.",
        "ticket_class": "UserRequest",
        "status": "new",
        "priority": "P4",
        "provider": "local",
        "sync_provider": False,
        "created_by": "global-search-smoke",
    })
    ticket_id = ticket.get("id")
    require(ticket_id, f"ticket not created: {ticket}")
    request("POST", f"/api/tickets/{ticket_id}/notes", {
        "body": f"Note evidence for {marker}",
        "author": "global-search-smoke",
        "source": "smoke",
        "visibility": "internal",
    })
    result = request("GET", f"/api/search/global?q={urllib.parse.quote(marker)}&limit=20")
    results = result.get("results") or []
    require(any(row.get("type") == "ticket" and row.get("id") == ticket_id for row in results),
            "global search did not return created ticket")
    require(any(row.get("type") == "ticket_note" and row.get("metadata", {}).get("ticket_id") == ticket_id for row in results),
            "global search did not return created ticket note")
    print(json.dumps({
        "status": "passed",
        "base": BASE,
        "ticket_id": ticket_id,
        "result_count": result.get("total"),
        "groups": result.get("groups"),
    }, indent=2))


if __name__ == "__main__":
    main()
