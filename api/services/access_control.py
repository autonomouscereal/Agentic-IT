import fnmatch
import os
import json
import re

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
        "access:request",
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
        "access:request",
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
    ("POST", "/api/tickets/*/status", "tickets:note"),
    ("POST", "/api/tickets*", "tickets:create"),
    ("GET", "/api/agents*", "agents:read"),
    ("POST", "/api/agents/spawn", "agents:spawn"),
    ("POST", "/api/agents/*/vault/lease", "agents:read"),
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
    mode = auth_mode()
    return {
        "username": headers.get("x-auth-request-user")
        or headers.get("x-forwarded-user")
        or ("local-admin" if mode == "disabled" else "anonymous"),
        "email": headers.get("x-auth-request-email")
        or headers.get("x-forwarded-email"),
        "provider": headers.get("x-auth-provider") or "local",
        "auth_mode": mode,
    }


def subject_from_decision(decision):
    """Return the bounded subject payload routes can pass into agent spawns."""
    decision = decision or {}
    return {
        "identity": decision.get("identity") or {"username": "system"},
        "roles": decision.get("roles") or [],
        "capabilities": decision.get("capabilities") or [],
        "scopes": decision.get("scopes") or [],
        "max_classification": decision.get("max_classification") or "internal",
    }


def subject_from_request(request):
    decision = getattr(getattr(request, "state", None), "access_decision", None)
    if decision:
        return subject_from_decision(decision)
    return {
        "identity": request_identity(request),
        "roles": ["platform-admin"] if auth_mode() == "disabled" else [],
        "capabilities": ["*"] if auth_mode() == "disabled" else [],
        "scopes": [],
        "max_classification": "secret" if auth_mode() == "disabled" else "internal",
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


def classification_rank(value):
    return CLASSIFICATION_RANK.get((value or "internal").strip().lower(), CLASSIFICATION_RANK["internal"])


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


async def load_agent_subject(agent_id):
    row = await fetchrow(
        """
        SELECT spawned_by_username, roles, allowed_permissions, scopes, max_classification
        FROM agent_permission_context
        WHERE agent_id = $1
        """,
        agent_id,
    )
    if not row:
        return {
            "identity": {"username": f"agent_{agent_id}"},
            "roles": ["agent-operator"],
            "capabilities": ["tickets:read", "changes:request"],
            "scopes": [],
            "max_classification": "internal",
        }
    return {
        "identity": {"username": row.get("spawned_by_username") or f"agent_{agent_id}"},
        "roles": _json_value(row.get("roles"), []),
        "capabilities": _json_value(row.get("allowed_permissions"), []),
        "scopes": _json_value(row.get("scopes"), []),
        "max_classification": row.get("max_classification") or "internal",
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


def _has_unbounded_ticket_access(subject):
    roles = set(subject.get("roles") or [])
    capabilities = subject.get("capabilities") or []
    return (
        capability_matches(capabilities, "*")
        or "platform-admin" in roles
        or "soc-manager" in roles
    )


def _scope_values(subject, names):
    values = []
    names = set(names)
    for scope in subject.get("scopes") or []:
        if scope.get("scope_type") in names and scope.get("scope_value"):
            values.append(str(scope.get("scope_value")))
    return values


def ticket_access_decision(ticket, subject, required_permission="tickets:read"):
    """Evaluate row-level ticket access for users and inherited agent subjects."""
    subject = subject or {}
    if auth_mode() == "disabled":
        return {"allow": True, "reason": "auth_disabled"}
    if not capability_matches(subject.get("capabilities") or [], required_permission):
        return {
            "allow": enforcement_mode() != "enforce",
            "reason": "missing_required_permission",
            "required_permission": required_permission,
        }
    ticket_classification = (ticket or {}).get("security_classification") or "internal"
    if classification_rank(ticket_classification) > classification_rank(subject.get("max_classification")):
        return {
            "allow": enforcement_mode() != "enforce",
            "reason": "classification_exceeds_subject",
            "ticket_classification": ticket_classification,
            "subject_max_classification": subject.get("max_classification"),
        }
    if _has_unbounded_ticket_access(subject):
        return {"allow": True, "reason": "unbounded_role_scope"}
    ticket_id = str((ticket or {}).get("id") or "")
    ticket_scopes = _scope_values(subject, ("ticket", "ticket_id"))
    if ticket_id and ticket_id in ticket_scopes:
        return {"allow": True, "reason": "ticket_scope_match"}
    owning_group = (ticket or {}).get("owning_group")
    group_scopes = _scope_values(subject, ("group", "owning_group", "assignment_group", "team"))
    if owning_group and owning_group in group_scopes:
        return {"allow": True, "reason": "owning_group_scope_match"}
    return {
        "allow": enforcement_mode() != "enforce",
        "reason": "ticket_outside_subject_scope",
        "ticket_id": ticket_id,
        "owning_group": owning_group,
    }


def ticket_filter_clause(subject, alias="t", start_param=1):
    """Return a SQL WHERE fragment and params for scoped ticket list reads."""
    subject = subject or {}
    if auth_mode() == "disabled" or _has_unbounded_ticket_access(subject):
        return "", [], start_param

    max_rank = classification_rank(subject.get("max_classification"))
    params = [max_rank]
    idx = start_param + 1
    clauses = [
        f"""CASE COALESCE({alias}.security_classification, 'internal')
            WHEN 'public' THEN 0
            WHEN 'internal' THEN 1
            WHEN 'confidential' THEN 2
            WHEN 'restricted' THEN 3
            WHEN 'secret' THEN 4
            ELSE 1
        END <= ${start_param}"""
    ]

    group_scopes = _scope_values(subject, ("group", "owning_group", "assignment_group", "team"))
    ticket_scopes = _scope_values(subject, ("ticket", "ticket_id"))
    scope_parts = []
    if group_scopes:
        params.append(group_scopes)
        scope_parts.append(f"{alias}.owning_group = ANY(${idx}::text[])")
        idx += 1
    if ticket_scopes:
        params.append([int(value) for value in ticket_scopes if str(value).isdigit()])
        scope_parts.append(f"{alias}.id = ANY(${idx}::int[])")
        idx += 1
    if not scope_parts:
        clauses.append("FALSE")
    else:
        clauses.append("(" + " OR ".join(scope_parts) + ")")
    return "(" + " AND ".join(clauses) + ")", params, idx


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


async def audit_resource_decision(actor, subject_type, subject_id, action, resource_type, resource_id, decision, reason, policy_snapshot=None):
    await execute(
        """
        INSERT INTO access_decision_log (
            actor, subject_type, subject_id, action, resource_type, resource_id,
            decision, reason, policy_snapshot
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb)
        """,
        actor or "unknown",
        subject_type,
        str(subject_id) if subject_id is not None else None,
        action,
        resource_type,
        str(resource_id) if resource_id is not None else None,
        decision,
        reason,
        json_dumps(policy_snapshot or {}),
    )
    await log_event(
        "access",
        "info" if decision == "allow" else "warning",
        actor or "unknown",
        "resource_access_decision",
        f"{resource_type}_{resource_id}",
        {
            "subject_type": subject_type,
            "subject_id": subject_id,
            "action": action,
            "decision": decision,
            "reason": reason,
        },
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
    allowed_permissions = [
        permission for permission in requested_permissions
        if permission not in denied
    ]
    if denied:
        await log_event(
            "access",
            "warning",
            subject.get("identity", {}).get("username", "unknown"),
            "agent_permission_snapshot_denied",
            f"agent_{agent_id}",
            {"ticket_id": ticket_id, "denied_permissions": denied},
        )

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
        json_dumps(allowed_permissions),
        json_dumps(subject.get("scopes", [])),
        subject.get("max_classification", "internal"),
        json_dumps({
            "source": "spawn",
            "capabilities_at_spawn": subject.get("capabilities", []),
            "requested_permissions": requested_permissions,
            "denied_permissions": denied,
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
            "allowed_permissions": allowed_permissions,
            "denied_permissions": denied,
            "max_classification": subject.get("max_classification", "internal"),
        },
    )
    return {
        "status": "recorded_with_denials" if denied else "recorded",
        "agent_id": agent_id,
        "ticket_id": ticket_id,
        "allowed_permissions": allowed_permissions,
        "denied_permissions": denied,
    }


def _json_value(value, default=None):
    if value is None:
        return default if default is not None else {}
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default if default is not None else {}
    return default if default is not None else {}


def _scope_lease_specs(subject):
    specs = []
    for scope in subject.get("scopes") or []:
        permissions = _json_value(scope.get("permissions"), [])
        if isinstance(permissions, dict):
            permissions = [permissions]
        if not isinstance(permissions, list):
            continue
        for item in permissions:
            if not isinstance(item, dict):
                continue
            system = item.get("system")
            credential_ref = item.get("credential_ref")
            if not system or not credential_ref:
                continue
            actions = item.get("actions") or item.get("action") or ["read"]
            if isinstance(actions, str):
                actions = [actions]
            for action in actions:
                specs.append({
                    "system": system,
                    "resource_type": item.get("resource_type") or "resource",
                    "resource_id": item.get("resource_id") or item.get("resource") or "*",
                    "action": action,
                    "credential_ref": credential_ref,
                    "expires_at": item.get("expires_at"),
                })
    return specs


async def create_agent_vault_manifest(agent_id, ticket_id, subject=None):
    """Create a per-agent vault manifest with scoped credential references only."""
    subject = subject or {
        "identity": {"username": "system"},
        "roles": ["platform-admin"],
        "capabilities": ["*"],
        "scopes": [],
        "max_classification": "secret",
    }
    ticket = await fetchrow(
        "SELECT id, owning_group, security_classification FROM tickets WHERE id = $1",
        ticket_id,
    )
    leases = []
    if ticket:
        for action in ("read", "note", "request_access"):
            leases.append({
                "system": "dashboard",
                "resource_type": "ticket",
                "resource_id": str(ticket_id),
                "action": action,
                "credential_ref": f"<vault:agent_{agent_id}_dashboard_ticket_{ticket_id}>",
                "expires_at": None,
            })
    leases.extend(_scope_lease_specs(subject))

    for lease in leases:
        await execute(
            """
            INSERT INTO agent_vault_leases (
                agent_id, system, resource_type, resource_id, action,
                credential_ref, lease_status, granted_by, expires_at, policy_snapshot
            )
            VALUES ($1, $2, $3, $4, $5, $6, 'active', $7, $8::timestamptz, $9::jsonb)
            ON CONFLICT (agent_id, system, resource_type, resource_id, action)
            DO UPDATE SET
                credential_ref = EXCLUDED.credential_ref,
                lease_status = EXCLUDED.lease_status,
                granted_by = EXCLUDED.granted_by,
                expires_at = EXCLUDED.expires_at,
                policy_snapshot = EXCLUDED.policy_snapshot,
                updated_at = NOW()
            """,
            agent_id,
            lease["system"],
            lease["resource_type"],
            str(lease["resource_id"]),
            lease["action"],
            lease["credential_ref"],
            subject.get("identity", {}).get("username", "system"),
            lease.get("expires_at"),
            json_dumps({
                "spawned_by": subject.get("identity", {}).get("username", "system"),
                "roles": subject.get("roles", []),
                "max_classification": subject.get("max_classification", "internal"),
                "note": "Credential values remain in the external vault; this row is only a scoped lease reference.",
            }),
        )

    rows = await fetchall(
        """
        SELECT id, agent_id, system, resource_type, resource_id, action,
               credential_ref, lease_status, expires_at, granted_by, created_at
        FROM agent_vault_leases
        WHERE agent_id = $1
        ORDER BY system, resource_type, resource_id, action
        """,
        agent_id,
    )
    await log_event(
        "access",
        "info",
        subject.get("identity", {}).get("username", "system"),
        "agent_vault_manifest_created",
        f"agent_{agent_id}",
        {"ticket_id": ticket_id, "lease_count": len(rows)},
    )
    return {"agent_id": agent_id, "ticket_id": ticket_id, "leases": rows}


def _lease_matches(lease, system, resource_type, resource_id, action):
    return (
        lease.get("system") == system
        and lease.get("resource_type") == resource_type
        and fnmatch.fnmatch(str(resource_id), str(lease.get("resource_id") or "*"))
        and (lease.get("action") == action or lease.get("action") == "*")
    )


async def request_agent_vault_lease(agent_id, system, resource_type, resource_id, action):
    rows = await fetchall(
        """
        SELECT *
        FROM agent_vault_leases
        WHERE agent_id = $1
          AND lease_status = 'active'
          AND (expires_at IS NULL OR expires_at > NOW())
        ORDER BY system, resource_type, resource_id, action
        """,
        agent_id,
    )
    for row in rows:
        if _lease_matches(row, system, resource_type, resource_id, action):
            await audit_resource_decision(
                f"agent_{agent_id}",
                "agent",
                agent_id,
                action,
                f"{system}:{resource_type}",
                resource_id,
                "allow",
                "agent_vault_lease_match",
                {"lease_id": row.get("id"), "credential_ref": row.get("credential_ref")},
            )
            return {
                "allow": True,
                "lease_id": row.get("id"),
                "agent_id": agent_id,
                "system": system,
                "resource_type": resource_type,
                "resource_id": resource_id,
                "action": action,
                "credential_ref": row.get("credential_ref"),
                "credential_value": None,
                "note": "Use the credential vault resolver for this reference; secret values are never returned by the dashboard.",
            }
    await audit_resource_decision(
        f"agent_{agent_id}",
        "agent",
        agent_id,
        action,
        f"{system}:{resource_type}",
        resource_id,
        "deny",
        "missing_agent_vault_lease",
        {"active_lease_count": len(rows)},
    )
    return {
        "allow": False,
        "error": "access_denied",
        "reason": "missing_agent_vault_lease",
        "agent_id": agent_id,
        "system": system,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "action": action,
        "next_step": "Create a ticket access request for this exact system/resource/action and wait for approval.",
    }


def _safe_vault_ref_part(value):
    text = re.sub(r"[^A-Za-z0-9_]+", "_", str(value or "resource")).strip("_").lower()
    return text[:80] or "resource"


def default_agent_vault_ref(agent_id, lease_request):
    return "<vault:agent_{agent}_{system}_{rtype}_{rid}_{action}>".format(
        agent=agent_id,
        system=_safe_vault_ref_part(lease_request.get("system")),
        rtype=_safe_vault_ref_part(lease_request.get("resource_type")),
        rid=_safe_vault_ref_part(lease_request.get("resource_id")),
        action=_safe_vault_ref_part(lease_request.get("action")),
    )


async def grant_agent_vault_lease(agent_id, lease_request, granted_by="access-gate", evidence=None):
    """Grant one scoped vault reference to one agent after an approved access gate.

    The credential_ref is still only a vault reference. Secret values remain in
    the deployment vault and are never stored in dashboard tables.
    """
    if not agent_id or not isinstance(lease_request, dict):
        return {"status": "skipped", "reason": "missing_agent_or_lease_request"}
    system = lease_request.get("system")
    resource_type = lease_request.get("resource_type") or "resource"
    resource_id = lease_request.get("resource_id") or "*"
    action = lease_request.get("action") or "read"
    if not system:
        return {"status": "skipped", "reason": "missing_system"}
    credential_ref = lease_request.get("credential_ref") or default_agent_vault_ref(agent_id, {
        "system": system,
        "resource_type": resource_type,
        "resource_id": resource_id,
        "action": action,
    })
    await execute(
        """
        INSERT INTO agent_vault_leases (
            agent_id, system, resource_type, resource_id, action, credential_ref,
            lease_status, granted_by, expires_at, policy_snapshot
        )
        VALUES ($1, $2, $3, $4, $5, $6, 'active', $7, $8::timestamptz, $9::jsonb)
        ON CONFLICT (agent_id, system, resource_type, resource_id, action)
        DO UPDATE SET
            credential_ref = EXCLUDED.credential_ref,
            lease_status = 'active',
            granted_by = EXCLUDED.granted_by,
            expires_at = EXCLUDED.expires_at,
            policy_snapshot = EXCLUDED.policy_snapshot,
            updated_at = NOW()
        """,
        agent_id,
        system,
        resource_type,
        str(resource_id),
        action,
        credential_ref,
        granted_by,
        lease_request.get("expires_at"),
        json_dumps({
            "source": "access_request_completion",
            "evidence": evidence or "",
            "secret_values_stored": False,
        }),
    )
    await log_event(
        "access",
        "info",
        granted_by,
        "agent_vault_lease_granted",
        f"agent_{agent_id}",
        {
            "system": system,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "action": action,
            "credential_ref": credential_ref,
        },
    )
    return {
        "status": "granted",
        "agent_id": agent_id,
        "system": system,
        "resource_type": resource_type,
        "resource_id": str(resource_id),
        "action": action,
        "credential_ref": credential_ref,
        "credential_value": None,
    }
