#!/usr/bin/env python3
"""Smoke test system-specific RACI routing for permission-wall access requests."""
import json
import os
import sys
import time
import urllib.error
import urllib.request


BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:25480").rstrip("/")
TOKEN = os.environ.get("DASHBOARD_SERVICE_TOKEN", "")


def request(method, path, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if TOKEN:
        headers["X-Dashboard-Service-Token"] = TOKEN
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
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
    marker = f"access-raci-{int(time.time())}"
    parent = request("POST", "/api/tickets", {
        "title": f"Access RACI routing smoke {marker}",
        "description": "Control-plane proof for system-specific access request routing.",
        "ticket_class": "UserRequest",
        "priority": "P4",
        "provider": "local",
        "sync_provider": False,
        "created_by": "access-raci-smoke",
    })
    ticket_id = parent["id"]
    cases = [
        ("Mailcow mailbox demo_account_1@mailcow.local", "read quarantine evidence", "Email Operations"),
        ("Wazuh alert index finance-edr-restricted", "read alert evidence", "Security Operations"),
        ("GitLab project demo/private-infra", "Developer repository read access", "DevSecOps"),
        ("Keycloak realm master OIDC clients", "manage client redirect URI", "Identity & Access"),
        ("iTop CMDB server objects", "read CMDB objects", "Business Applications"),
        ("Agentic Operations dashboard workflow admin", "workflow admin", "Platform Operations"),
        ("Firewall DNS egress control", "modify allowlist", "Network Operations"),
    ]
    results = []
    for resource, permission, expected_group in cases:
        result = request("POST", f"/api/tickets/{ticket_id}/access-request", {
            "resource": resource,
            "permission": permission,
            "reason": f"{marker}: permission wall requires a scoped test grant.",
            "requester": "access-raci-smoke",
            "account_ref": "agent-access-raci-smoke",
            "sync_provider": False,
            "created_by": "access-raci-smoke",
        })
        require(result.get("assignment_group") == expected_group,
                f"{resource} routed to {result.get('assignment_group')} instead of {expected_group}: {result}")
        raci = result.get("access_raci") or {}
        require(raci.get("source") == "raci-rule", f"{resource} did not use a RACI rule: {result}")
        results.append({
            "resource": resource,
            "assignment_group": result.get("assignment_group"),
            "access_request_id": result.get("access_request_id"),
            "change_id": result.get("change_id"),
            "rule": raci.get("rule_name"),
        })
    listed = request("GET", f"/api/tickets/{ticket_id}/access-requests")
    require(listed.get("total", 0) >= len(cases), "access request list did not include all routed cases")
    print(json.dumps({
        "status": "passed",
        "base": BASE,
        "parent_ticket_id": ticket_id,
        "cases": results,
    }, indent=2))


if __name__ == "__main__":
    main()
