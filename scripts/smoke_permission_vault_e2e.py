#!/usr/bin/env python3
"""
HTTP proof for user RBAC, row-level ticket scope, and per-agent vault leases.

This script does not need secrets. It expects the API to run with:
  DASHBOARD_AUTH_MODE=header
  DASHBOARD_AUTH_ENFORCEMENT=enforce

Demo users/scopes can be seeded with the SQL printed by --print-seed-sql.
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request


ADMIN = "codex-rbac-admin"
DEV_Y = "codex-dev-y"
DEV_Z = "codex-dev-z"


def request(base, method, path, payload=None, user=ADMIN, expect=(200,)):
    data = None
    headers = {
        "Content-Type": "application/json",
        "X-Auth-Request-User": user,
        "X-Auth-Provider": "codex-smoke",
    }
    trusted_secret = os.getenv("DASHBOARD_TRUSTED_AUTH_SECRET", "")
    if trusted_secret:
        headers["X-Dashboard-Auth-Secret"] = trusted_secret
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(base.rstrip("/") + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
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


def print_seed_sql():
    permissions_y = json.dumps([
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
    permissions_z = json.dumps([
        {
            "system": "gitlab",
            "resource_type": "project",
            "resource_id": "dev-z/*",
            "actions": ["read"],
            "credential_ref": "<vault:gitlab_dev_z_read>",
        },
        {
            "system": "gitlab",
            "resource_type": "project",
            "resource_id": "dev-y/*",
            "actions": ["read"],
            "credential_ref": "<vault:gitlab_dev_y_read_for_team_z>",
        },
    ])
    print(f"""
INSERT INTO dashboard_roles (name, description) VALUES
  ('platform-admin', 'Full platform administration'),
  ('analyst', 'View and work assigned tickets'),
  ('agent-operator', 'Create agents and supervise runs')
ON CONFLICT (name) DO NOTHING;

INSERT INTO dashboard_users (username, display_name, provider, enabled)
VALUES
  ('{ADMIN}', 'Codex RBAC Admin', 'codex-smoke', true),
  ('{DEV_Y}', 'Codex Dev Y Analyst', 'codex-smoke', true),
  ('{DEV_Z}', 'Codex Dev Z Analyst', 'codex-smoke', true)
ON CONFLICT (username) DO UPDATE SET enabled = true, provider = EXCLUDED.provider;

INSERT INTO dashboard_user_roles (user_id, role_id)
SELECT u.id, r.id FROM dashboard_users u, dashboard_roles r
WHERE u.username = '{ADMIN}' AND r.name = 'platform-admin'
ON CONFLICT DO NOTHING;

INSERT INTO dashboard_user_roles (user_id, role_id)
SELECT u.id, r.id FROM dashboard_users u, dashboard_roles r
WHERE u.username IN ('{DEV_Y}', '{DEV_Z}') AND r.name IN ('analyst', 'agent-operator')
ON CONFLICT DO NOTHING;

INSERT INTO dashboard_user_scopes (user_id, scope_type, scope_value, permissions)
SELECT id, 'group', 'Dev Team Y', '{permissions_y}'::jsonb FROM dashboard_users WHERE username = '{DEV_Y}'
ON CONFLICT (user_id, scope_type, scope_value) DO UPDATE SET permissions = EXCLUDED.permissions, updated_at = NOW();

INSERT INTO dashboard_user_scopes (user_id, scope_type, scope_value, permissions)
SELECT id, 'classification', 'confidential', '[]'::jsonb FROM dashboard_users WHERE username = '{DEV_Y}'
ON CONFLICT (user_id, scope_type, scope_value) DO UPDATE SET permissions = EXCLUDED.permissions, updated_at = NOW();

INSERT INTO dashboard_user_scopes (user_id, scope_type, scope_value, permissions)
SELECT id, 'group', 'Dev Team Z', '{permissions_z}'::jsonb FROM dashboard_users WHERE username = '{DEV_Z}'
ON CONFLICT (user_id, scope_type, scope_value) DO UPDATE SET permissions = EXCLUDED.permissions, updated_at = NOW();

INSERT INTO dashboard_user_scopes (user_id, scope_type, scope_value, permissions)
SELECT id, 'group', 'Dev Team Y', '[]'::jsonb FROM dashboard_users WHERE username = '{DEV_Z}'
ON CONFLICT (user_id, scope_type, scope_value) DO UPDATE SET permissions = EXCLUDED.permissions, updated_at = NOW();

INSERT INTO dashboard_user_scopes (user_id, scope_type, scope_value, permissions)
SELECT id, 'classification', 'restricted', '[]'::jsonb FROM dashboard_users WHERE username = '{DEV_Z}'
ON CONFLICT (user_id, scope_type, scope_value) DO UPDATE SET permissions = EXCLUDED.permissions, updated_at = NOW();
""".strip())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("base", nargs="?", default="http://127.0.0.1:25480")
    parser.add_argument("--print-seed-sql", action="store_true")
    parser.add_argument("--stop-agent", action="store_true", default=True)
    args = parser.parse_args()

    if args.print_seed_sql:
        print_seed_sql()
        return 0

    _, policies = request(args.base, "GET", "/api/access/policies", user=ADMIN)
    assert policies["auth_mode"] != "disabled", policies
    assert policies["enforcement"] == "enforce", policies

    marker = f"PERMISSION_VAULT_E2E_{int(time.time())}"
    _, y_ticket = request(args.base, "POST", "/api/tickets", {
        "title": f"{marker} Dev Team Y scoped ticket",
        "description": "Permission proof ticket for Dev Team Y.",
        "ticket_class": "UserRequest",
        "provider": "local",
        "sync_provider": False,
        "auto_assign": False,
        "owning_group": "Dev Team Y",
        "security_classification": "confidential",
    })
    _, z_ticket = request(args.base, "POST", "/api/tickets", {
        "title": f"{marker} Dev Team Z scoped ticket",
        "description": "Permission proof ticket for Dev Team Z.",
        "ticket_class": "UserRequest",
        "provider": "local",
        "sync_provider": False,
        "auto_assign": False,
        "owning_group": "Dev Team Z",
        "security_classification": "restricted",
    })
    y_id = y_ticket["id"]
    z_id = z_ticket["id"]

    _, y_list = request(args.base, "GET", "/api/tickets?limit=1000", user=DEV_Y)
    visible_ids = {row["id"] for row in y_list["tickets"]}
    assert y_id in visible_ids, visible_ids
    assert z_id not in visible_ids, visible_ids

    _, z_list = request(args.base, "GET", "/api/tickets?limit=1000", user=DEV_Z)
    visible_to_z = {row["id"] for row in z_list["tickets"]}
    assert y_id in visible_to_z, visible_to_z
    assert z_id in visible_to_z, visible_to_z

    request(args.base, "GET", f"/api/tickets/{y_id}", user=DEV_Y)
    request(args.base, "GET", f"/api/tickets/{z_id}", user=DEV_Y, expect=(403,))
    request(args.base, "POST", f"/api/tickets/{y_id}/notes", {
        "body": f"{marker} Dev Team Y note allowed.",
        "author": DEV_Y,
    }, user=DEV_Y)
    request(args.base, "POST", f"/api/tickets/{z_id}/notes", {
        "body": f"{marker} Dev Team Y note should be denied.",
        "author": DEV_Y,
    }, user=DEV_Y, expect=(403,))

    _, spawn = request(args.base, "POST", f"/api/tickets/{y_id}/assign-agent", {
        "model": "qwen/qwen3.6-27b",
        "prompt": (
            f"Permission proof {marker}. Read agent_vault.json, request gitlab dev-y/read "
            "and gitlab dev-z/read leases, document any 403 as a permission wall, then stop."
        ),
    }, user=DEV_Y)
    agent_id = spawn["agent_id"]

    _, manifest = request(args.base, "GET", f"/api/agents/{agent_id}/vault", user=ADMIN)
    assert manifest["secret_values_returned"] is False

    _, allowed_lease = request(args.base, "POST", f"/api/agents/{agent_id}/vault/lease", {
        "system": "gitlab",
        "resource_type": "project",
        "resource_id": "dev-y/app",
        "action": "read",
    }, user=ADMIN)
    assert allowed_lease["allow"] is True
    assert allowed_lease["credential_ref"] == "<vault:gitlab_dev_y_read>"
    assert allowed_lease["credential_value"] is None

    _, denied_lease = request(args.base, "POST", f"/api/agents/{agent_id}/vault/lease", {
        "system": "gitlab",
        "resource_type": "project",
        "resource_id": "dev-z/app",
        "action": "read",
    }, user=ADMIN, expect=(403,))
    assert denied_lease["detail"]["reason"] == "missing_agent_vault_lease"

    if args.stop_agent:
        request(args.base, "POST", f"/api/agents/{agent_id}/stop", {
            "reason": f"{marker} permission proof complete; stopped only this test-lane agent"
        }, user=ADMIN, expect=(200,))

    print(json.dumps({
        "status": "passed",
        "marker": marker,
        "dev_y_ticket": y_id,
        "dev_z_ticket": z_id,
        "agent_id": agent_id,
        "visible_to_dev_y": sorted(visible_ids),
        "visible_to_dev_z": sorted(visible_to_z),
        "allowed_lease_id": allowed_lease["lease_id"],
        "denied_reason": denied_lease["detail"]["reason"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
