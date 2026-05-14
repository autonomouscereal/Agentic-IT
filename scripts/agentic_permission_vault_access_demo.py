#!/usr/bin/env python3
"""
Real local-agent proof for per-agent vault permissions.

This test intentionally makes the model:
1. Read its own per-agent vault manifest.
2. Request an allowed Dev Y GitLab lease.
3. Request a denied Dev Z GitLab lease.
4. Document the permission wall.
5. Create an access request carrying a lease_request payload.
6. Stop at waiting_for_access.
7. Resume after approval.
8. Complete the grant gate, receive the new Dev Z lease, and close the ticket.

No secret values are created or returned. Credential refs are vault references.
"""

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request


ADMIN = "codex-rbac-admin"
DEV_Y = "codex-dev-y"
DEV_Z = "codex-dev-z"


def request(base, method, path, payload=None, user=None, expect=(200,)):
    data = None
    headers = {"Content-Type": "application/json"}
    if user:
        headers["X-Auth-Request-User"] = user
        headers["X-Auth-Provider"] = "codex-agentic-permission-demo"
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(base.rstrip("/") + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            parsed = json.loads(body) if body else {}
            if resp.status not in expect:
                raise AssertionError(f"{method} {path} returned {resp.status}, expected {expect}: {parsed}")
            return parsed
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(body) if body else {}
        except json.JSONDecodeError:
            parsed = {"raw": body}
        if exc.code not in expect:
            raise AssertionError(f"{method} {path} returned {exc.code}, expected {expect}: {parsed}") from exc
        return parsed


def run(cmd, cwd=None):
    completed = subprocess.run(cmd, cwd=cwd, check=False, text=True, capture_output=True)
    if completed.returncode != 0:
        raise RuntimeError(f"command failed {cmd}: {completed.stderr or completed.stdout}")
    return completed.stdout


def compose_auth(mode, enforcement, cwd):
    env = {"DASHBOARD_AUTH_MODE": mode, "DASHBOARD_AUTH_ENFORCEMENT": enforcement}
    cmd = " ".join([f"{key}={value}" for key, value in env.items()]) + " docker compose up -d api"
    completed = subprocess.run(cmd, cwd=cwd, shell=True, text=True, capture_output=True)
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or completed.stdout)


def wait_health(base, user=None, timeout=180):
    start = time.time()
    last = None
    while time.time() - start < timeout:
        try:
            return request(base, "GET", "/health", user=user)
        except Exception as exc:
            last = exc
            time.sleep(2)
    raise TimeoutError(f"health did not recover: {last}")


def ensure_demo_identities(base):
    for username, display in (
        (ADMIN, "Codex RBAC Admin"),
        (DEV_Y, "Codex Dev Y Analyst"),
        (DEV_Z, "Codex Dev Z Analyst"),
    ):
        request(base, "POST", "/api/access/users", {
            "username": username,
            "display_name": display,
            "provider": "codex-agentic-permission-demo",
            "enabled": True,
        })
    users = request(base, "GET", "/api/access/users")["users"]
    by_name = {row["username"]: row for row in users}
    request(base, "POST", f"/api/access/users/{by_name[ADMIN]['id']}/roles", ["platform-admin"])
    request(base, "POST", f"/api/access/users/{by_name[DEV_Y]['id']}/roles", ["analyst", "agent-operator"])
    request(base, "POST", f"/api/access/users/{by_name[DEV_Z]['id']}/roles", ["analyst", "agent-operator"])
    request(base, "POST", f"/api/access/users/{by_name[DEV_Y]['id']}/scopes", {
        "scope_type": "group",
        "scope_value": "Dev Team Y",
        "permissions": [
            {
                "system": "gitlab",
                "resource_type": "project",
                "resource_id": "dev-y/*",
                "actions": ["read"],
                "credential_ref": "<vault:gitlab_dev_y_read>",
            }
        ],
    })
    request(base, "POST", f"/api/access/users/{by_name[DEV_Y]['id']}/scopes", {
        "scope_type": "classification",
        "scope_value": "confidential",
        "permissions": [],
    })
    request(base, "POST", f"/api/access/users/{by_name[DEV_Z]['id']}/scopes", {
        "scope_type": "group",
        "scope_value": "Dev Team Z",
        "permissions": [
            {
                "system": "gitlab",
                "resource_type": "project",
                "resource_id": "dev-z/*",
                "actions": ["read"],
                "credential_ref": "<vault:gitlab_dev_z_read>",
            }
        ],
    })
    request(base, "POST", f"/api/access/users/{by_name[DEV_Z]['id']}/scopes", {
        "scope_type": "group",
        "scope_value": "Dev Team Y",
        "permissions": [],
    })
    request(base, "POST", f"/api/access/users/{by_name[DEV_Z]['id']}/scopes", {
        "scope_type": "classification",
        "scope_value": "restricted",
        "permissions": [],
    })
    return by_name


def wait_no_active(base, timeout=60):
    start = time.time()
    while time.time() - start < timeout:
        active = request(base, "GET", "/api/agents/active")
        if active.get("count") == 0:
            return active
        time.sleep(5)
    raise TimeoutError("active agents did not drain")


def wait_access_request(base, ticket_id, marker, timeout=1800):
    start = time.time()
    last = None
    while time.time() - start < timeout:
        context = request(base, "GET", f"/api/tickets/{ticket_id}/context")
        notes = "\n".join(row.get("body") or "" for row in context.get("notes") or [])
        access = context.get("access_requests") or []
        if access and f"PERMISSION WALL {marker}" in notes:
            return context, access[0]
        agent_id = ((context.get("ticket") or {}).get("agent_id"))
        if agent_id:
            task = latest_task(base, agent_id)
            if task.get("status") in ("failed", "stopped", "terminated"):
                raise RuntimeError(f"agent {agent_id} ended before access request: {task}")
        last = {
            "notes": notes[-500:],
            "access_count": len(access),
            "ticket_status": (context.get("ticket") or {}).get("status"),
        }
        time.sleep(10)
    raise TimeoutError(f"access request not created: {last}")


def wait_completion(base, ticket_id, marker, timeout=3600):
    start = time.time()
    last = None
    while time.time() - start < timeout:
        context = request(base, "GET", f"/api/tickets/{ticket_id}/context")
        ticket = context.get("ticket") or {}
        notes = "\n".join(row.get("body") or "" for row in context.get("notes") or [])
        access = context.get("access_requests") or []
        granted = any(row.get("status") == "granted" for row in access)
        complete = (
            ticket.get("status") == "resolved"
            and granted
            and f"ACCESS LEASE GRANTED {marker}" in notes
        )
        if complete:
            return context
        agent_id = ticket.get("agent_id")
        if agent_id:
            task = latest_task(base, agent_id)
            if task.get("status") in ("failed", "stopped", "terminated"):
                raise RuntimeError(f"agent {agent_id} ended before completion: {task}")
        last = {
            "ticket_status": ticket.get("status"),
            "granted": granted,
            "note_tail": notes[-500:],
        }
        time.sleep(15)
    raise TimeoutError(f"completion not observed: {last}")


def latest_task(base, agent_id):
    tasks = request(base, "GET", f"/api/agents/tasks?agent_id={agent_id}")
    rows = tasks.get("tasks") or []
    return rows[0] if rows else {}


def spawn_with_subject(repo, ticket_id, model, prompt, username, stall_seconds, run_timeout):
    """Spawn inside the API container with a stored user subject.

    This keeps the API process stable during the live model run. The enforced
    RBAC matrix proves header auth separately; this proof needs the agent to
    inherit Dev Y vault leases without adding synthetic auth headers to all of
    its curls.
    """
    payload = {
        "ticket_id": ticket_id,
        "model": model,
        "prompt": prompt,
        "username": username,
        "stall_seconds": stall_seconds,
        "requested_permissions": [
            "tickets:read",
            "tickets:note",
            "changes:request",
            "access:request",
            "changes:approve",
            "access:admin",
        ],
    }
    code = f"""
import asyncio, json
from database import fetchrow
from services import access_control, agent_runner

payload = {json.dumps(payload)!r}
payload = json.loads(payload)

async def main():
    loaded = await access_control.load_subject(payload["username"])
    if not loaded:
        raise RuntimeError(f"subject not found: {{payload['username']}}")
    subject = {{
        "identity": {{"username": payload["username"], "provider": "codex-agentic-permission-demo"}},
        "roles": loaded["roles"],
        "capabilities": loaded["capabilities"],
        "scopes": loaded["scopes"],
        "max_classification": loaded["max_classification"],
    }}
    result = await agent_runner.spawn_agent(
        payload["ticket_id"],
        payload["model"],
        payload["prompt"],
        "ticket_resolution",
        actor_context=subject,
        requested_permissions=payload["requested_permissions"],
    )
    task = await fetchrow(
        "SELECT id, agent_id, work_dir, prompt FROM agent_tasks WHERE id = $1 AND agent_id = $2",
        result["task_id"],
        result["agent_id"],
    )
    if not task:
        raise RuntimeError(f"spawned task not found: {{result}}")
    await agent_runner._spawn_with_semaphore(
        task["work_dir"],
        task["prompt"],
        task["id"],
        task["agent_id"],
    )
    print(json.dumps(result))

asyncio.run(main())
"""
    completed = subprocess.run(
        [
            "docker",
            "compose",
            "exec",
            "-T",
            "-e",
            f"AGENT_NO_OUTPUT_STALL_SECONDS={max(60, int(stall_seconds))}",
            "api",
            "python",
            "-",
        ],
        cwd=repo,
        input=code,
        text=True,
        capture_output=True,
        timeout=max(int(run_timeout), int(stall_seconds) + 300),
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr or completed.stdout)
    lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("agent spawn returned no output")
    return json.loads(lines[-1])


def build_prompt(marker, ticket_id):
    return f"""
You are testing per-agent vault permissions for marker {marker}.

Use only the dashboard API at http://localhost:8000. Do not use any external
provider credential directly. Secret values must never be requested or printed.
You may only use vault lease references returned by /api/agents/<agent_id>/vault/lease.
Use simple sequential Bash/curl commands. Do not use parallel tool calls.

Find your agent_id from agent_vault.json in the current work directory.

First-run path:
1. GET /api/tickets/{ticket_id}/context.
2. POST /api/agents/<agent_id>/vault/lease for {{"system":"gitlab","resource_type":"project","resource_id":"dev-y/app","action":"read"}}. This must be allowed.
3. POST /api/agents/<agent_id>/vault/lease for {{"system":"gitlab","resource_type":"project","resource_id":"dev-z/app","action":"read"}}. This must return access_denied / 403.
4. Add a ticket note exactly containing: PERMISSION WALL {marker}: gitlab project dev-z/app read was denied by missing_agent_vault_lease; access request required.
5. POST /api/tickets/{ticket_id}/access-request with agent_id, resource "GitLab project dev-z/app", permission "read", account_ref "agent-<agent_id>", assignment_group "DevSecOps", risk_level "medium", sync_provider false, reason "PERMISSION WALL {marker}: denied lease missing_agent_vault_lease for gitlab project dev-z/app read.", and lease_request {{"system":"gitlab","resource_type":"project","resource_id":"dev-z/app","action":"read","credential_ref":"<vault:gitlab_dev_z_read_after_approval>"}}.
6. Write checkpoint.json with step "waiting-for-vault-access-{marker}", status "waiting_for_access", progress_pct 45, output "waiting for approved GitLab dev-z/app lease {marker}", and a timestamp. Reply exactly "waiting for access {marker}" and stop.

Resume path after approval:
1. GET /api/tickets/{ticket_id}/context and find the approved or granted access request and its change_id.
2. If the linked change is approved, POST /api/changes/<change_id>/complete with completed_by "agent_<agent_id>" and result "Lab-safe vault lease grant completed for {marker}; no production credential value was exposed."
3. POST /api/agents/<agent_id>/vault/lease again for gitlab project dev-z/app read. It must now be allowed and return credential_ref "<vault:gitlab_dev_z_read_after_approval>" with credential_value null.
4. Add a ticket note exactly containing: ACCESS LEASE GRANTED {marker}: gitlab project dev-z/app read lease is now available as <vault:gitlab_dev_z_read_after_approval>; no secret value returned.
5. POST /api/tickets/{ticket_id}/status with status "resolved", actor "agent_<agent_id>", reason "ACCESS LEASE GRANTED {marker}: denied lease became approved scoped lease after access gate.", close_provider false.
6. Write checkpoint.json with step "vault-access-complete-{marker}", status "done", progress_pct 100, output "ACCESS LEASE GRANTED {marker}", and a timestamp. Reply exactly "ACCESS LEASE GRANTED {marker}".
""".strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("base", nargs="?", default="http://127.0.0.1:25480")
    parser.add_argument("model", nargs="?", default="qwen/qwen3.6-27b")
    parser.add_argument("--manage-auth", action="store_true")
    parser.add_argument("--repo", default=".")
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--stall-seconds", type=int, default=300)
    args = parser.parse_args()

    wait_no_active(args.base)
    ensure_demo_identities(args.base)
    marker = f"AGENTIC_PERMISSION_VAULT_{int(time.time())}"
    if args.manage_auth:
        policies = request(args.base, "GET", "/api/access/policies")
        if policies.get("auth_mode") != "disabled":
            compose_auth("disabled", "audit-only", args.repo)
            wait_health(args.base)
    y_ticket = request(args.base, "POST", "/api/tickets", {
        "title": f"{marker} Dev Y permission-vault agentic proof",
        "description": "Local model must hit a denied Dev Z GitLab lease, request access, resume, and prove the approved lease.",
        "ticket_class": "UserRequest",
        "provider": "local",
        "sync_provider": False,
        "auto_assign": False,
        "owning_group": "Dev Team Y",
        "security_classification": "confidential",
    }, user=ADMIN)
    request(args.base, "POST", "/api/tickets", {
        "title": f"{marker} Dev Z negative-control ticket",
        "description": "Negative-control ticket for Dev Z row-level scope.",
        "ticket_class": "UserRequest",
        "provider": "local",
        "sync_provider": False,
        "auto_assign": False,
        "owning_group": "Dev Team Z",
        "security_classification": "restricted",
    }, user=ADMIN)
    ticket_id = y_ticket["id"]
    spawn = spawn_with_subject(
        args.repo,
        ticket_id,
        args.model,
        build_prompt(marker, ticket_id),
        DEV_Y,
        args.stall_seconds,
        args.timeout,
    )

    agent_id = spawn["agent_id"]
    context, access_row = wait_access_request(args.base, ticket_id, marker, args.timeout)
    change_id = access_row["change_id"]
    request(args.base, "POST", f"/api/changes/{change_id}/approve", {
        "approved_by": "agentic-permission-vault-approver",
        "reason": f"Approving lab-safe scoped vault lease for {marker}.",
    })
    final_context = wait_completion(args.base, ticket_id, marker, args.timeout)
    final_ticket = final_context.get("ticket") or {}
    current_agent_id = final_ticket.get("agent_id") or agent_id
    task = latest_task(args.base, current_agent_id)
    print(json.dumps({
        "status": "passed",
        "marker": marker,
        "ticket_id": ticket_id,
        "initial_agent_id": agent_id,
        "final_agent_id": current_agent_id,
        "change_id": change_id,
        "access_request_id": access_row["id"],
        "ticket_status": final_ticket.get("status"),
        "task_status": task.get("status"),
        "task_progress": task.get("progress_pct"),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
