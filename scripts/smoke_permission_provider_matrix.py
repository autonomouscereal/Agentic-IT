#!/usr/bin/env python3
"""End-to-end permission matrix with local and iTop-backed tickets.

This is a control-plane proof, not a provider-secret proof. It verifies:

* header/enforced RBAC and row-level ticket visibility
* denied actions produce 403 instead of silent overreach
* agents still spawn under the spawner's bounded subject
* per-agent vault leases allow scoped resources and deny missing leases
* denied access can create an access request synced to iTop
* approving/completing the access gate mints the approved agent vault lease

Secret values are never requested or returned. All credential values stay as
vault references.
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request


ADMIN = "codex-rbac-admin"
DEV_Y = "codex-dev-y"
DEV_Z = "codex-dev-z"
AUDITOR = "codex-auditor"
APPROVER = "codex-soc-manager"


def request(base, method, path, payload=None, user=ADMIN, expect=(200,), timeout=90):
    headers = {
        "Content-Type": "application/json",
        "X-Auth-Request-User": user,
        "X-Auth-Provider": "codex-permission-provider-matrix",
    }
    trusted_secret = os.getenv("DASHBOARD_TRUSTED_AUTH_SECRET", "")
    if trusted_secret:
        headers["X-Dashboard-Auth-Secret"] = trusted_secret
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(base.rstrip("/") + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            parsed = json.loads(body) if body else {}
            if resp.status not in expect:
                raise AssertionError(f"{method} {path} returned {resp.status}, expected {expect}: {parsed}")
            return resp.status, parsed
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body) if body else {}
        except json.JSONDecodeError:
            parsed = {"raw": body}
        if exc.code not in expect:
            raise AssertionError(f"{method} {path} returned {exc.code}, expected {expect}: {parsed}") from exc
        return exc.code, parsed


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def compose_auth(mode, enforcement, cwd):
    cmd = f"DASHBOARD_AUTH_MODE={mode} DASHBOARD_AUTH_ENFORCEMENT={enforcement} docker compose up -d api"
    completed = subprocess.run(cmd, cwd=cwd, shell=True, text=True, capture_output=True)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or completed.stdout)


def wait_health(base, user=ADMIN, timeout=180):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        try:
            return request(base, "GET", "/health", user=user)
        except Exception as exc:
            last = exc
            time.sleep(2)
    raise TimeoutError(f"health did not recover: {last}")


def wait_no_active(base, timeout=120):
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        _, active = request(base, "GET", "/api/agents/active", user=ADMIN)
        last = active
        if active.get("count") == 0:
            return active
        time.sleep(5)
    raise TimeoutError(f"active agents did not drain: {last}")


def ensure_identity(base, username, display_name, roles):
    request(base, "POST", "/api/access/users", {
        "username": username,
        "display_name": display_name,
        "provider": "codex-permission-provider-matrix",
        "enabled": True,
    }, user=ADMIN)
    _, users = request(base, "GET", "/api/access/users", user=ADMIN)
    by_name = {row["username"]: row for row in users.get("users", [])}
    user_id = by_name[username]["id"]
    request(base, "POST", f"/api/access/users/{user_id}/roles", roles, user=ADMIN)
    return user_id


def upsert_scope(base, user_id, scope_type, scope_value, permissions=None):
    request(base, "POST", f"/api/access/users/{user_id}/scopes", {
        "scope_type": scope_type,
        "scope_value": scope_value,
        "permissions": permissions or [],
    }, user=ADMIN)


def ensure_demo_identities(base):
    admin_id = ensure_identity(base, ADMIN, "Codex RBAC Admin", ["platform-admin"])
    y_id = ensure_identity(base, DEV_Y, "Codex Dev Y Analyst", ["analyst", "agent-operator"])
    z_id = ensure_identity(base, DEV_Z, "Codex Dev Z Analyst", ["analyst", "agent-operator"])
    auditor_id = ensure_identity(base, AUDITOR, "Codex Read Only Auditor", ["auditor"])
    approver_id = ensure_identity(base, APPROVER, "Codex SOC Manager", ["soc-manager"])

    upsert_scope(base, y_id, "group", "Dev Team Y", [
        {
            "system": "gitlab",
            "resource_type": "project",
            "resource_id": "dev-y/*",
            "actions": ["read"],
            "credential_ref": "<vault:gitlab_dev_y_read>",
        },
        {
            "system": "itop",
            "resource_type": "ticket",
            "resource_id": "team-y/*",
            "actions": ["read", "comment"],
            "credential_ref": "<vault:itop_team_y_agent>",
        },
    ])
    upsert_scope(base, y_id, "classification", "confidential")
    upsert_scope(base, z_id, "group", "Dev Team Z", [
        {
            "system": "gitlab",
            "resource_type": "project",
            "resource_id": "dev-z/*",
            "actions": ["read"],
            "credential_ref": "<vault:gitlab_dev_z_read>",
        },
    ])
    upsert_scope(base, z_id, "group", "Dev Team Y", [
        {
            "system": "gitlab",
            "resource_type": "project",
            "resource_id": "dev-y/*",
            "actions": ["read"],
            "credential_ref": "<vault:gitlab_dev_y_read_for_team_z>",
        },
    ])
    upsert_scope(base, z_id, "classification", "restricted")
    upsert_scope(base, auditor_id, "group", "Dev Team Y")
    upsert_scope(base, auditor_id, "classification", "restricted")
    upsert_scope(base, approver_id, "classification", "restricted")
    return {
        "admin_id": admin_id,
        "dev_y_id": y_id,
        "dev_z_id": z_id,
        "auditor_id": auditor_id,
        "approver_id": approver_id,
    }


def maybe_read_itop_object(ticket_class, provider_ref, itop_client):
    if not itop_client or not provider_ref:
        return {"status": "skipped", "reason": "missing_itop_client_or_ref"}
    completed = subprocess.run(
        [
            sys.executable,
            itop_client,
            "get",
            str(ticket_class),
            str(provider_ref),
            "--fields",
            "id,ref,title,status,last_update",
        ],
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    if completed.returncode != 0:
        return {"status": "error", "error": completed.stderr or completed.stdout}
    try:
        return json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {"status": "error", "raw": completed.stdout}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("base", nargs="?", default="http://127.0.0.1:25480")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--manage-auth", action="store_true")
    parser.add_argument("--model", default="qwen/qwen3.6-27b")
    parser.add_argument("--itop-client", default="/home/cereal/SOC_TESTING/itop-deployment/scripts/itop_client.py")
    args = parser.parse_args()

    base = args.base.rstrip("/")
    wait_no_active(base)
    ensure_demo_identities(base)
    marker = f"PERMISSION_PROVIDER_MATRIX_{int(time.time())}"

    if args.manage_auth:
        compose_auth("header", "enforce", args.repo)
        wait_health(base, user=ADMIN)

    spawned_agent_id = None
    try:
        _, policies = request(base, "GET", "/api/access/policies", user=ADMIN)
        require(policies.get("auth_mode") != "disabled", f"auth not enabled: {policies}")
        require(policies.get("enforcement") == "enforce", f"enforcement not active: {policies}")

        _, y_local = request(base, "POST", "/api/tickets", {
            "title": f"{marker} Dev Y local scoped request",
            "description": "Permission matrix local ticket.",
            "ticket_class": "UserRequest",
            "provider": "local",
            "sync_provider": False,
            "auto_assign": False,
            "owning_group": "Dev Team Y",
            "security_classification": "confidential",
        }, user=ADMIN)
        _, z_local = request(base, "POST", "/api/tickets", {
            "title": f"{marker} Dev Z restricted negative control",
            "description": "Permission matrix restricted ticket.",
            "ticket_class": "UserRequest",
            "provider": "local",
            "sync_provider": False,
            "auto_assign": False,
            "owning_group": "Dev Team Z",
            "security_classification": "restricted",
        }, user=ADMIN)
        _, y_itop = request(base, "POST", "/api/tickets", {
            "title": f"{marker} Dev Y iTop synced request",
            "description": "Permission matrix iTop-backed parent ticket.",
            "ticket_class": "UserRequest",
            "provider": "itop",
            "sync_provider": True,
            "auto_assign": False,
            "owning_group": "Dev Team Y",
            "security_classification": "confidential",
        }, user=ADMIN, timeout=180)
        require(y_itop.get("provider") == "itop", f"parent not iTop-backed: {y_itop}")
        require(y_itop.get("provider_sync_status") == "synced", f"parent did not sync: {y_itop}")
        require(str(y_itop.get("provider_ref", "")).isdigit(), f"parent missing iTop ref: {y_itop}")

        y_id = y_local["id"]
        z_id = z_local["id"]
        itop_parent_id = y_itop["id"]

        _, y_list = request(base, "GET", "/api/tickets?limit=1000", user=DEV_Y)
        y_visible = {row["id"] for row in y_list.get("tickets", [])}
        require(y_id in y_visible, "Dev Y cannot see own local ticket")
        require(itop_parent_id in y_visible, "Dev Y cannot see own iTop-backed ticket")
        require(z_id not in y_visible, "Dev Y can see restricted Dev Z ticket")

        request(base, "GET", f"/api/tickets/{z_id}", user=DEV_Y, expect=(403,))
        request(base, "POST", f"/api/tickets/{z_id}/notes", {
            "body": f"{marker} forbidden note should fail.",
            "author": DEV_Y,
        }, user=DEV_Y, expect=(403,))
        request(base, "POST", f"/api/tickets/{y_id}/notes", {
            "body": f"{marker} allowed note by Dev Y.",
            "author": DEV_Y,
        }, user=DEV_Y)
        request(base, "POST", f"/api/tickets/{y_id}/notes", {
            "body": f"{marker} auditor write should fail.",
            "author": AUDITOR,
        }, user=AUDITOR, expect=(403,))
        request(base, "POST", f"/api/tickets/{y_id}/assign-agent", {
            "model": args.model,
            "prompt": "auditor should not be able to spawn this",
        }, user=AUDITOR, expect=(403,))
        request(base, "POST", "/api/agents/spawn", {
            "ticket_id": z_id,
            "model": args.model,
            "prompt": "Dev Y should not spawn on hidden Dev Z ticket",
        }, user=DEV_Y, expect=(403,))

        _, spawn = request(base, "POST", f"/api/tickets/{y_id}/assign-agent", {
            "model": args.model,
            "requested_permissions": [
                "tickets:read",
                "tickets:note",
                "changes:request",
                "changes:approve",
                "access:admin",
            ],
            "prompt": (
                f"{marker}: no-op permission boundary probe. Do not use provider secrets. "
                "The control plane will stop this test-lane agent after vault checks."
            ),
        }, user=DEV_Y, timeout=180)
        spawned_agent_id = spawn["agent_id"]
        request(base, "POST", f"/api/agents/{spawned_agent_id}/stop", {
            "reason": f"{marker}: permission matrix uses the agent record and vault leases only; stopping this test-lane agent before manual boundary probes.",
        }, user=ADMIN)

        _, manifest = request(base, "GET", f"/api/agents/{spawned_agent_id}/vault", user=ADMIN)
        require(manifest.get("secret_values_returned") is False, "vault endpoint returned secret values")
        manifest_blob = json.dumps(manifest)
        require("<vault:gitlab_dev_y_read>" in manifest_blob, "manifest missing Dev Y lease ref")
        require("<vault:gitlab_dev_z_read>" not in manifest_blob, "manifest leaked Dev Z lease ref")

        _, allowed_gitlab = request(base, "POST", f"/api/agents/{spawned_agent_id}/vault/lease", {
            "system": "gitlab",
            "resource_type": "project",
            "resource_id": "dev-y/app",
            "action": "read",
        }, user=ADMIN)
        require(allowed_gitlab.get("allow") is True, f"Dev Y GitLab lease denied: {allowed_gitlab}")
        require(allowed_gitlab.get("credential_value") is None, "GitLab lease returned a secret value")

        _, denied_gitlab = request(base, "POST", f"/api/agents/{spawned_agent_id}/vault/lease", {
            "system": "gitlab",
            "resource_type": "project",
            "resource_id": "dev-z/app",
            "action": "read",
        }, user=ADMIN, expect=(403,))
        require(denied_gitlab["detail"]["reason"] == "missing_agent_vault_lease", denied_gitlab)

        _, allowed_itop = request(base, "POST", f"/api/agents/{spawned_agent_id}/vault/lease", {
            "system": "itop",
            "resource_type": "ticket",
            "resource_id": "team-y/incident-123",
            "action": "comment",
        }, user=ADMIN)
        require(allowed_itop.get("credential_ref") == "<vault:itop_team_y_agent>", allowed_itop)

        _, denied_itop = request(base, "POST", f"/api/agents/{spawned_agent_id}/vault/lease", {
            "system": "itop",
            "resource_type": "ticket",
            "resource_id": "team-z/incident-999",
            "action": "read",
        }, user=ADMIN, expect=(403,))
        require(denied_itop["detail"]["reason"] == "missing_agent_vault_lease", denied_itop)

        _, access = request(base, "POST", f"/api/tickets/{itop_parent_id}/access-request", {
            "resource": "iTop ticket team-z/incident-999",
            "permission": "read",
            "reason": f"{marker}: denied iTop lease for team-z/incident-999 read; access request must sync to iTop.",
            "agent_id": spawned_agent_id,
            "requester": f"agent_{spawned_agent_id}",
            "account_ref": f"agent-{spawned_agent_id}",
            "assignment_group": "Identity & Access",
            "risk_level": "medium",
            "sync_provider": True,
            "created_by": "permission-provider-matrix",
            "lease_request": {
                "system": "itop",
                "resource_type": "ticket",
                "resource_id": "team-z/incident-999",
                "action": "read",
                "credential_ref": "<vault:itop_team_z_read_after_approval>",
            },
        }, user=DEV_Y, timeout=180)
        access_ticket = access.get("access_ticket") or {}
        require(access.get("status") == "pending_approval", f"access request not pending: {access}")
        require(access_ticket.get("provider") == "itop", f"access ticket did not use iTop: {access_ticket}")
        require(access_ticket.get("provider_sync_status") == "synced", f"access ticket did not sync: {access_ticket}")
        require(str(access_ticket.get("provider_ref", "")).isdigit(), f"access ticket missing iTop ref: {access_ticket}")

        change_id = access["change_id"]
        request(base, "POST", f"/api/changes/{change_id}/approve", {
            "approved_by": APPROVER,
            "reason": f"{marker}: approving least-privilege iTop read lease for lab proof.",
        }, user=APPROVER)
        _, completed = request(base, "POST", f"/api/changes/{change_id}/complete", {
            "completed_by": f"agent_{spawned_agent_id}",
            "result": f"{marker}: lab-safe iTop lease grant completed; no credential value exposed.",
        }, user=ADMIN)
        granted = completed.get("access_sync", {}).get("granted_leases") or []
        require(any(row.get("status") == "granted" for row in granted), f"lease was not granted: {completed}")

        _, granted_itop = request(base, "POST", f"/api/agents/{spawned_agent_id}/vault/lease", {
            "system": "itop",
            "resource_type": "ticket",
            "resource_id": "team-z/incident-999",
            "action": "read",
        }, user=ADMIN)
        require(granted_itop.get("allow") is True, granted_itop)
        require(granted_itop.get("credential_ref") == "<vault:itop_team_z_read_after_approval>", granted_itop)
        require(granted_itop.get("credential_value") is None, "granted lease returned a secret value")

    finally:
        if args.manage_auth:
            compose_auth("disabled", "audit-only", args.repo)
            wait_health(base)

    parent_itop = maybe_read_itop_object(
        y_itop.get("provider_class") or y_itop.get("itop_class") or "UserRequest",
        y_itop.get("provider_ref") or y_itop.get("itop_ref"),
        args.itop_client,
    )
    access_itop = maybe_read_itop_object(
        access_ticket.get("provider_class") or access_ticket.get("itop_class") or "UserRequest",
        access_ticket.get("provider_ref") or access_ticket.get("itop_ref"),
        args.itop_client,
    )
    access_objects = access_itop.get("objects") or {}
    if access_objects:
        access_fields = next(iter(access_objects.values())).get("fields") or {}
        require(
            access_fields.get("status") in ("resolved", "closed"),
            f"iTop access ticket did not close after gate completion: {access_fields}",
        )

    _, active = request(base, "GET", "/api/agents/active", user=ADMIN)
    require(active.get("count") == 0, f"test left active agents: {active}")

    print(json.dumps({
        "status": "passed",
        "marker": marker,
        "local_dev_y_ticket": y_id,
        "local_dev_z_ticket": z_id,
        "itop_parent_ticket": itop_parent_id,
        "itop_parent_provider_ref": y_itop.get("provider_ref"),
        "access_ticket": access.get("access_ticket_id"),
        "access_ticket_provider_ref": access_ticket.get("provider_ref"),
        "agent_id": spawned_agent_id,
        "allowed_gitlab_lease": allowed_gitlab.get("lease_id"),
        "denied_gitlab_reason": denied_gitlab["detail"]["reason"],
        "allowed_itop_lease": allowed_itop.get("lease_id"),
        "denied_itop_reason": denied_itop["detail"]["reason"],
        "granted_itop_lease": granted_itop.get("lease_id"),
        "parent_itop_read": parent_itop,
        "access_itop_read": access_itop,
        "active_agents": active,
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
