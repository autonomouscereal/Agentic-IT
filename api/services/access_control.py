import fnmatch
import os

from database import fetchall, fetchrow, execute, json_dumps
from services.event_logger import log_event


CLASSIFICATION_RANK = {
    "public": 0,
    "internal": 1,
    "confidential": 2,
    "restricted": 3,
    "secret": 4,
}

DEFAULT_ROLE_CAPABILITIES = {
    "platform-admin": ["*"],
    "soc-manager": [
        "tickets:*",
        "agents:*",
        "changes:*",
        "workflows:*",
        "audit:read",
        "access:read",
    ],
    "analyst": [
        "tickets:read",
        "tickets:note",
        "tickets:request_info",
        "changes:request",
        "agents:assigned",
    ],
    "auditor": [
        "tickets:read",
        "changes:read",
        "audit:read",
        "evidence:read",
        "access:read",
    ],
    "agent-operator": [
        "agents:spawn",
        "agents:read",
        "tickets:read",
        "changes:request",
    ],
}

ROUTE_REQUIREMENTS = [
    ("GET", "/api/tickets*", "tickets:read"),
    ("POST", "/api/tickets/*/notes", "tickets:note"),
    ("POST", "/api/tickets/*/request-info", "tickets:request_info"),
    ("POST", "/api/tickets/*/user-response", "tickets:note"),
    ("POST", "/api/tickets/*/assign-agent", "agents:spawn"),
    ("POST", "/api/tickets/*/postmortem", "agents:spawn"),
    ("POST", "/api/tickets/*/workflow", "agents:spawn"),
    ("POST", "/api/tickets/*/access-request", "access:request"),
    ("POST", "/api/tickets*", "tickets:create"),
    ("GET", "/api/agents*", "agents:read"),
    ("POST", "/api/agents/spawn", "agents:spawn"),
    ("POST", "/api/agents/*/stop", "agents:stop"),
    ("POST", "/api/agents/*/restart", "agents:restart"),
    ("POST", "/api/agents/*/wake", "agents:wake"),
    ("GET", "/api/changes*", "changes:read"),
    ("POST", "/api/changes/request", "changes:request"),
    ("POST", "/api/changes/*/approve", "changes:approve"),
    ("POST", "/api/changes/*/reject", "changes:approve"),
    ("POST", "/api/changes/*/complete", "changes:complete"),
    ("GET", "/api/dashboard/audit*", "audit:read"),
    ("GET", "/api/access*", "access:read"),
    ("POST", "/api/access*", "access:admin"),
    ("GET", "/api/tools*", "tools:read"),
    ("POST", "/api/tools*", "tools:operate"),
    ("GET", "/api/cicd*", "cicd:read"),
    ("POST", "/api/cicd*", "cicd:write"),
    ("GET", "/api/workflows*", "workflows:read"),
    ("POST", "/api/workflows*", "workflows:write"),
    ("GET", "/api/postmortems*", "postmortems:read"),
    ("POST", "/api/postmortems*", "postmortems:write"),
    ("GET", "/api/knowledge*", "knowledge:read"),
    ("POST", "/api/knowledge*", "knowledge:write"),
    ("GET", "/api/setup*", "setup:read"),
    ("POST", "/api/setup*", "setup:write"),
]

PUBLIC_PATHS = (
    "/",
    "/health",
    "/static/",
)


def auth_mode():
    return os.getenv("DASHBOARD_AUTH_MODE", "disabled").strip().lower()


def enforcement_mode():
    return os.getenv("DASHBOARD_AUTH_ENFORCEMENT", "audit-only").strip().lower()


def request_identity(request):
    headers = getattr(request, "headers", {}) or {}
    return {
        "username": headers.get("x-auth-request-user")
        or headers.get("x-forwarded-user")
        or "local-admin",
        "email": headers.get("x-auth-request-email")
        or headers.get("x-forwarded-email"),
        "provider": headers.get("x-auth-provider") or "local",
        "auth_mode": auth_mode(),
    }


def required_permission(method, path):
    upper_method = (method or "GET").upper()
    if path == "/" or path in PUBLIC_PATHS or any(path.startswith(prefix) for prefix in PUBLIC_PATHS if prefix.endswith("/") and prefix != "/"):
        return None
    for route_method, pattern, permission in ROUTE_REQUIREMENTS:
        if route_method == upper_method and fnmatch.fnmatch(path, pattern):
            return permission
    if path.startswith("/api/"):
        return "platform:unknown"
    return None


def capability_matches(granted, required):
    if not required:
        return True
    for capability in granted or []:
        if capability == "*" or capability == required:
            return True
        if capability.endswith(":*") and required.startswith(capability[:-1]):
            return True
    return False


def max_classification(roles, scopes):
    values = []
    for role in roles or []:
        if role == "platform-admin":
            values.append("secret")
        elif role in ("soc-manager", "auditor"):
            values.append("restricted")
        else:
            values.append("confidential")
    for scope in scopes or []:
        if scope.get("scope_type") == "classification":
            values.append(scope.get("scope_value"))
    ranked = sorted(
        (value for value in values if value in CLASSIFICATION_RANK),
        key=lambda value: CLASSIFICATION_RANK[value],
        reverse=True,
    )
    return ranked[0] if ranked else "internal"


def normalize_capabilities(role_rows, permission_rows=None):
    roles = [row["name"] for row in role_rows or []]
    capabilities = []
    for role in roles:
        capabilities.extend(DEFAULT_ROLE_CAPABILITIES.get(role, []))
    for row in permission_rows or []:
        key = row.get("permission_key")
        if key:
            capabilities.append(key)
    deduped = []
    for value in capabilities:
        if value not in deduped:
            deduped.append(value)
    return roles, deduped


async def load_subject(username):
    user = await fetchrow(
        "SELECT * FROM dashboard_users WHERE username = $1 AND enabled = true",
        username,
    )
    if not user:
        return None
    role_rows = await fetchall(
        """
        SELECT r.name
        FROM dashboard_user_roles ur
        JOIN dashboard_roles r ON r.id = ur.role_id
        WHERE ur.user_id = $1
        ORDER BY r.name
        """,
        user["id"],
    )
    permission_rows = await fetchall(
        """
        SELECT DISTINCT rp.permission_key
        FROM dashboard_role_permissions rp
        JOIN dashboard_roles r ON r.name = rp.role_name
        JOIN dashboard_user_roles ur ON ur.role_id = r.id
        WHERE ur.user_id = $1
        ORDER BY rp.permission_key
        """,
        user["id"],
    )
    scopes = await fetchall(
        """
        SELECT scope_type, scope_value, permissions
        FROM dashboard_user_scopes
        WHERE user_id = $1
        ORDER BY scope_type, scope_value
        """,
        user["id"],
    )
    roles, capabilities = normalize_capabilities(role_rows, permission_rows)
    return {
        "user": user,
        "roles": roles,
        "capabilities": capabilities,
        "scopes": scopes,
        "max_classification": max_classification(roles, scopes),
    }


async def evaluate_request(request):
    identity = request_identity(request)
    mode = identity["auth_mode"]
    required = required_permission(getattr(request, "method", "GET"), getattr(getattr(request, "url", None), "path", "/"))
    if required is None:
        return {
            "allow": True,
            "decision": "allow",
            "reason": "public_or_unclassified_route",
            "identity": identity,
            "roles": [],
            "capabilities": [],
            "required_permission": required,
            "enforcement": enforcement_mode(),
        }
    if mode == "disabled":
        return {
            "allow": True,
            "decision": "allow",
            "reason": "auth_disabled",
            "identity": identity,
            "roles": ["platform-admin"],
            "capabilities": ["*"],
            "required_permission": required,
            "enforcement": enforcement_mode(),
        }

    subject = await load_subject(identity["username"])
    if not subject:
        return {
            "allow": enforcement_mode() != "enforce",
            "decision": "deny",
            "reason": "unknown_or_disabled_user",
            "identity": identity,
            "roles": [],
            "capabilities": [],
            "required_permission": required,
            "enforcement": enforcement_mode(),
        }

    allowed = capability_matches(subject["capabilities"], required)
    return {
        "allow": allowed or enforcement_mode() != "enforce",
        "decision": "allow" if allowed else "deny",
        "reason": "capability_match" if allowed else "missing_required_permission",
        "identity": identity,
        "roles": subject["roles"],
        "capabilities": subject["capabilities"],
        "scopes": subject["scopes"],
        "max_classification": subject["max_classification"],
        "required_permission": required,
        "enforcement": enforcement_mode(),
    }


async def audit_decision(decision, method, path, status_code=None):
    if not decision.get("required_permission") and decision.get("reason") == "auth_disabled":
        return
    details = {
        "method": method,
        "path": path,
        "decision": decision.get("decision"),
        "reason": decision.get("reason"),
        "roles": decision.get("roles", []),
        "required_permission": decision.get("required_permission"),
        "enforcement": decision.get("enforcement"),
        "status_code": status_code,
    }
    await log_event(
        "access",
        "info" if decision.get("decision") == "allow" else "warning",
        decision.get("identity", {}).get("username", "unknown"),
        "access_decision",
        f"{method} {path}",
        details,
    )


def requested_permissions_within_subject(subject_capabilities, requested_permissions):
    denied = []
    for permission in requested_permissions or []:
        if not capability_matches(subject_capabilities, permission):
            denied.append(permission)
    return denied


async def record_agent_permission_context(agent_id, ticket_id, subject=None, requested_permissions=None):
    subject = subject or {
        "identity": {"username": "system"},
        "roles": ["platform-admin"],
        "capabilities": ["*"],
        "scopes": [],
        "max_classification": "secret",
    }
    requested_permissions = requested_permissions or ["tickets:read", "tickets:note", "changes:request"]
    denied = requested_permissions_within_subject(subject.get("capabilities", []), requested_permissions)
    if denied:
        await log_event(
            "access",
            "warning",
            subject.get("identity", {}).get("username", "unknown"),
            "agent_permission_snapshot_denied",
            f"agent_{agent_id}",
            {"ticket_id": ticket_id, "denied_permissions": denied},
        )
        return {"status": "denied", "denied_permissions": denied}

    await execute(
        """
        INSERT INTO agent_permission_context (
            agent_id, ticket_id, spawned_by_username, roles, allowed_permissions,
            scopes, max_classification, policy_snapshot
        )
        VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6::jsonb, $7, $8::jsonb)
        ON CONFLICT (agent_id) DO UPDATE SET
            ticket_id = EXCLUDED.ticket_id,
            spawned_by_username = EXCLUDED.spawned_by_username,
            roles = EXCLUDED.roles,
            allowed_permissions = EXCLUDED.allowed_permissions,
            scopes = EXCLUDED.scopes,
            max_classification = EXCLUDED.max_classification,
            policy_snapshot = EXCLUDED.policy_snapshot,
            updated_at = NOW()
        """,
        agent_id,
        ticket_id,
        subject.get("identity", {}).get("username", "system"),
        json_dumps(subject.get("roles", [])),
        json_dumps(requested_permissions),
        json_dumps(subject.get("scopes", [])),
        subject.get("max_classification", "internal"),
        json_dumps({
            "source": "spawn",
            "capabilities_at_spawn": subject.get("capabilities", []),
            "enforcement": enforcement_mode(),
        }),
    )
    await log_event(
        "access",
        "info",
        subject.get("identity", {}).get("username", "system"),
        "agent_permission_snapshot_recorded",
        f"agent_{agent_id}",
        {
            "ticket_id": ticket_id,
            "allowed_permissions": requested_permissions,
            "max_classification": subject.get("max_classification", "internal"),
        },
    )
    return {"status": "recorded", "agent_id": agent_id, "ticket_id": ticket_id}
