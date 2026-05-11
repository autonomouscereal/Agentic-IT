#!/usr/bin/env python3
"""Smoke test provider adapter registration and fail-closed outbound behavior."""
import json
import sys
import urllib.error
import urllib.request


BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://localhost:25480"


def request(method, path, body=None):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print(exc.read().decode("utf-8"), file=sys.stderr)
        raise


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    providers = request("GET", "/api/providers")["providers"]
    names = {provider["name"] for provider in providers}
    for required in ("local", "itop", "servicenow", "jira", "generic-webhook"):
        require(required in names, f"missing provider {required}")

    ticket = request("POST", "/api/tickets", {
        "title": "Provider adapter smoke",
        "description": "Verifies provider registry and fail-closed external adapters.",
        "ticket_class": "Incident",
        "provider": "local",
        "sync_provider": False,
        "created_by": "provider-smoke",
    })
    ticket_id = ticket["id"]

    local_push = request("POST", f"/api/tickets/{ticket_id}/push-provider", {"provider": "local"})
    require(local_push.get("status") == "local_only", f"local provider did not stay local_only: {local_push}")

    servicenow_push = request("POST", f"/api/tickets/{ticket_id}/push-provider", {"provider": "servicenow"})
    require("not configured" in servicenow_push.get("error", "").lower(), f"ServiceNow did not fail closed: {servicenow_push}")

    jira_push = request("POST", f"/api/tickets/{ticket_id}/push-provider", {"provider": "jira"})
    require("not configured" in jira_push.get("error", "").lower(), f"Jira did not fail closed: {jira_push}")

    ticket_after = request("GET", f"/api/tickets/{ticket_id}")
    require(ticket_after.get("provider_sync_status") == "create_failed", "failed external push was not recorded")
    require(ticket_after.get("provider_last_error"), "provider_last_error not recorded")

    print(json.dumps({
        "status": "ok",
        "providers": sorted(names),
        "ticket_id": ticket_id,
        "local_push": local_push.get("status"),
        "servicenow": servicenow_push.get("error"),
        "jira": jira_push.get("error"),
    }, indent=2))


if __name__ == "__main__":
    main()
