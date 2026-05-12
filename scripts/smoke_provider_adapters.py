#!/usr/bin/env python3
"""Smoke test provider adapter registration and outbound behavior."""
import json
import sys
import urllib.error
import urllib.request


BASE = "http://localhost:25480"
ITOP_CREATE = False

for arg in sys.argv[1:]:
    if arg == "--itop-create":
        ITOP_CREATE = True
    else:
        BASE = arg.rstrip("/")


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

    itop_results = []
    if ITOP_CREATE:
        for ticket_class, priority in (("UserRequest", "P3"), ("Incident", "P2")):
            created = request("POST", "/api/tickets", {
                "title": f"Provider adapter iTop smoke {ticket_class}",
                "description": "Verifies dashboard outbound create reaches iTop.",
                "ticket_class": ticket_class,
                "priority": priority,
                "provider": "itop",
                "sync_provider": True,
                "created_by": "provider-smoke",
            })
            require(created.get("provider") == "itop", f"iTop create did not select iTop: {created}")
            require(created.get("provider_sync_status") == "synced", f"iTop create did not sync: {created}")
            require(str(created.get("provider_ref", "")).isdigit(), f"iTop create did not return numeric ref: {created}")
            itop_results.append({
                "ticket_id": created.get("id"),
                "class": ticket_class,
                "provider_ref": created.get("provider_ref"),
            })

    print(json.dumps({
        "status": "ok",
        "providers": sorted(names),
        "ticket_id": ticket_id,
        "local_push": local_push.get("status"),
        "servicenow": servicenow_push.get("error"),
        "jira": jira_push.get("error"),
        "itop_create": itop_results,
    }, indent=2))


if __name__ == "__main__":
    main()
