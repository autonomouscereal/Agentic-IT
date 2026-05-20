import fnmatch
import base64
import hashlib
import hmac
import os
import json
import re
import secrets
import time

from database import fetchall, fetchrow, execute, json_dumps
from services.event_logger import log_event
try:
    from services import vault_providers
except ImportError:  # unit-test stubs may not preload the service package
    class _VaultProviderFallback:
        @staticmethod
        def provider_name():
            return "server-manager"

        @staticmethod
        def resolver_mode():
            return "reference-only"

        @staticmethod
        def broker_metadata(system=None, broker_mode="lease-reference"):
            return {
                "vault_provider": "server-manager",
                "resolver_mode": "reference-only",
                "system": system,
                "broker_mode": broker_mode,
                "secret_values_returned": False,
                "credential_value_returned": False,
            }

    vault_providers = _VaultProviderFallback()
try:
    from services.workflow_keys import workflow_key_for_ticket
except ImportError:  # unit-test stubs may not preload workflow helpers
    def workflow_key_for_ticket(ticket, *extra_values):
        ticket_class = (ticket or {}).get("itop_class") or (ticket or {}).get("provider_class") or "ticket"
        return f"{str(ticket_class).strip().lower()}:general"


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
        "ui:read",
        "health:read",
        "dashboard:read",
        "tickets:*",
        "agents:*",
        "changes:*",
        "workflows:*",
        "postmortems:*",
        "tools:*",
        "providers:*",
        "skills:*",
        "knowledge:*",
        "setup:*",
        "intake:*",
        "cicd:*",
        "ops-chat:*",
        "search:read",
        "audit:read",
        "access:*",
    ],
    "analyst": [
        "ui:read",
        "dashboard:read",
        "tickets:read",
        "tickets:note",
        "tickets:request_info",
        "access:request",
        "changes:request",
        "intake:write",
        "intake:read",
        "ops-chat:write",
        "agents:assigned",
        "search:read",
    ],
    "auditor": [
        "ui:read",
        "health:read",
        "dashboard:read",
        "tickets:read",
        "changes:read",
        "audit:read",
        "evidence:read",
        "access:read",
        "agents:read",
        "tools:read",
        "workflows:read",
        "postmortems:read",
        "knowledge:read",
        "cicd:read",
        "ops-chat:read",
        "search:read",
    ],
    "agent-operator": [
        "ui:read",
        "dashboard:read",
        "agents:spawn",
        "agents:read",
        "tickets:read",
        "tickets:note",
        "tickets:request_info",
        "access:request",
        "changes:read",
        "changes:request",
        "changes:complete",
        "workflows:read",
        "postmortems:read",
        "postmortems:write",
        "knowledge:read",
        "ops-chat:write",
        "search:read",
    ],
}

ROUTE_REQUIREMENTS = [
    ("GET", "/api/access/me", "ui:read"),
    ("GET", "/api/tickets*", "tickets:read"),
    ("POST", "/api/tickets/*/notes", "tickets:note"),
    ("POST", "/api/tickets/*/assignment", "tickets:note"),
    ("POST", "/api/tickets/*/request-info", "tickets:request_info"),
    ("POST", "/api/tickets/*/user-response", "tickets:note"),
    ("POST", "/api/tickets/*/assign-agent", "agents:spawn"),
    ("POST", "/api/tickets/*/postmortem", "agents:spawn"),
    ("POST", "/api/tickets/*/workflow", "agents:spawn"),
    ("POST", "/api/tickets/*/access-request", "access:request"),
    ("POST", "/api/tickets/*/status", "tickets:note"),
    ("POST", "/api/tickets/*/attachments", "tickets:note"),
    ("GET", "/api/tickets/*/access-requests", "access:read"),
    ("POST", "/api/tickets/*/sync", "providers:sync"),
    ("POST", "/api/tickets/*/push-provider", "providers:sync"),
    ("POST", "/api/tickets/*/unassign-agent", "agents:stop"),
    ("POST", "/api/tickets*", "tickets:create"),
    ("GET", "/api/agents*", "agents:read"),
    ("POST", "/api/agents/spawn", "agents:spawn"),
    ("POST", "/api/agents/create-from-prompt", "agents:spawn"),
    ("POST", "/api/agents/audits/run", "agents:audit"),
    ("POST", "/api/agents/heartbeat/*", "agents:heartbeat"),
    ("POST", "/api/agents/*/vault/lease", "agents:read"),
    ("POST", "/api/agents/*/steering/*/ack", "agents:heartbeat"),
    ("POST", "/api/agents/*/stop", "agents:stop"),
    ("POST", "/api/agents/*/restart", "agents:restart"),
    ("POST", "/api/agents/*/wake", "agents:wake"),
    ("POST", "/api/agents/*/update", "agents:update"),
    ("POST", "/api/agents*", "agents:write"),
    ("GET", "/api/changes*", "changes:read"),
    ("POST", "/api/changes/request", "changes:request"),
    ("POST", "/api/changes/*/approve", "changes:approve"),
    ("POST", "/api/changes/*/reject", "changes:approve"),
    ("POST", "/api/changes/*/complete", "changes:complete"),
    ("GET", "/api/dashboard/audit*", "audit:read"),
    ("GET", "/api/dashboard*", "dashboard:read"),
    ("GET", "/api/access*", "access:read"),
    ("POST", "/api/access*", "access:admin"),
    ("GET", "/api/tools*", "tools:read"),
    ("POST", "/api/tools*", "tools:operate"),
    ("GET", "/api/providers*", "providers:read"),
    ("POST", "/api/providers*", "providers:sync"),
    ("GET", "/api/skills*", "skills:read"),
    ("POST", "/api/skills*", "skills:write"),
    ("PUT", "/api/skills*", "skills:write"),
    ("DELETE", "/api/skills*", "skills:write"),
    ("GET", "/api/intake*", "intake:read"),
    ("POST", "/api/intake*", "intake:write"),
    ("PUT", "/api/intake*", "intake:write"),
    ("DELETE", "/api/intake*", "intake:write"),
    ("GET", "/api/ops-chat*", "ops-chat:read"),
    ("POST", "/api/ops-chat*", "ops-chat:write"),
    ("GET", "/api/cicd*", "cicd:read"),
    ("POST", "/api/cicd*", "cicd:write"),
    ("GET", "/api/search*", "search:read"),
    ("GET", "/api/workflows*", "workflows:read"),
    ("POST", "/api/workflows*", "workflows:write"),
    ("PUT", "/api/workflows*", "workflows:write"),
    ("GET", "/api/postmortems*", "postmortems:read"),
    ("POST", "/api/postmortems*", "postmortems:write"),
    ("PUT", "/api/postmortems*", "postmortems:write"),
    ("GET", "/api/knowledge*", "knowledge:read"),
    ("POST", "/api/knowledge*", "knowledge:write"),
    ("PUT", "/api/knowledge*", "knowledge:write"),
    ("GET", "/api/setup*", "setup:read"),
    ("POST", "/api/setup*", "setup:write"),
]

PUBLIC_PATHS = ("/favicon.ico",)
PASSWORD_HASH_ALGORITHM = "pbkdf2_sha256"
PASSWORD_HASH_ITERATIONS = 260000


def auth_mode():
    return os.getenv("DASHBOARD_AUTH_MODE", "disabled").strip().lower()


def enforcement_mode():
    return os.getenv("DASHBOARD_AUTH_ENFORCEMENT", "audit-only").strip().lower()


def protect_ui():
    return os.getenv("DASHBOARD_PROTECT_UI", "true").strip().lower() not in ("0", "false", "no", "off")


def public_health():
    return os.getenv("DASHBOARD_PUBLIC_HEALTH", "false").strip().lower() in ("1", "true", "yes", "on")


def trusted_auth_secret():
    return os.getenv("DASHBOARD_TRUSTED_AUTH_SECRET", "").strip()


def service_token():
    return os.getenv("DASHBOARD_SERVICE_TOKEN", "").strip()


def session_secret():
    return (
        os.getenv("DASHBOARD_SESSION_SECRET", "").strip()
        or trusted_auth_secret()
        or service_token()
    )


def session_ttl_seconds():
    try:
        return max(300, int(os.getenv("DASHBOARD_SESSION_TTL_SECONDS", "3600")))
    except ValueError:
        return 3600


def cookie_secure():
    return os.getenv("DASHBOARD_COOKIE_SECURE", "true").strip().lower() not in ("0", "false", "no", "off")


def hash_password(password):
    if not password:
        raise ValueError("password is required")
    salt = secrets.token_urlsafe(24)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PASSWORD_HASH_ITERATIONS,
    )
    return "$".join([
        PASSWORD_HASH_ALGORITHM,
        str(PASSWORD_HASH_ITERATIONS),
        salt,
        base64.urlsafe_b64encode(digest).decode("ascii").rstrip("="),
    ])


def verify_password(password, stored_hash):
    if not password or not stored_hash:
        return False
    try:
        algorithm, iterations, salt, encoded_digest = stored_hash.split("$", 3)
        if algorithm != PASSWORD_HASH_ALGORITHM:
            return False
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            int(iterations),
        )
        expected = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    except (ValueError, TypeError, OverflowError):
        return False
    return hmac.compare_digest(expected, encoded_digest)


def _b64url(data):
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(data):
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode((data + padding).encode("ascii"))


def _session_signature(payload):
    secret = session_secret()
    if not secret:
        return ""
    return hmac.new(secret.encode("utf-8"), payload.encode("ascii"), hashlib.sha256).hexdigest()


def create_session_cookie(identity, subject=None):
    if not identity or not identity.get("authenticated") or identity.get("auth_mode") == "service-token":
        return None
    body = {
        "username": identity.get("username"),
        "email": identity.get("email"),
        "provider": identity.get("provider") or "trusted-proxy",
        "exp": int(time.time()) + session_ttl_seconds(),
    }
    if subject:
        body["subject"] = {
            "roles": subject.get("roles") or [],
            "capabilities": subject.get("capabilities") or [],
            "scopes": subject.get("scopes") or [],
            "max_classification": subject.get("max_classification") or "internal",
        }
    payload = _b64url(json.dumps(body, separators=(",", ":")).encode("utf-8"))
    sig = _session_signature(payload)
    if not sig:
        return None
    return f"{payload}.{sig}"


def _identity_from_session_cookie(headers, mode):
    raw_cookie = _header_value(headers, "cookie") or ""
    cookies = {}
    for item in raw_cookie.split(";"):
        if "=" in item:
            key, value = item.split("=", 1)
            cookies[key.strip()] = value.strip()
    token = cookies.get("dashboard_session")
    if not token or "." not in token:
        return None
    payload, sig = token.rsplit(".", 1)
    expected = _session_signature(payload)
    if not _token_matches(sig, expected):
        return {
            "username": "anonymous",
            "email": None,
            "provider": "session-cookie",
            "auth_mode": mode,
            "authenticated": False,
            "auth_failure": "invalid_session_cookie",
        }
    try:
        body = json.loads(_b64url_decode(payload))
    except Exception:
        return {
            "username": "anonymous",
            "email": None,
            "provider": "session-cookie",
            "auth_mode": mode,
            "authenticated": False,
            "auth_failure": "malformed_session_cookie",
        }
    if int(body.get("exp") or 0) < int(time.time()):
        return {
            "username": body.get("username") or "anonymous",
            "email": body.get("email"),
            "provider": body.get("provider") or "session-cookie",
            "auth_mode": mode,
            "authenticated": False,
            "auth_failure": "expired_session_cookie",
        }
    return {
        "username": body.get("username") or "anonymous",
        "email": body.get("email"),
        "provider": body.get("provider") or "session-cookie",
        "auth_mode": mode,
        "authenticated": bool(body.get("username")),
        "auth_strength": "signed-session-cookie",
        "session_subject": body.get("subject") if isinstance(body.get("subject"), dict) else None,
    }


def _header_value(headers, name):
    if not headers:
        return None
    return headers.get(name) or headers.get(name.lower()) or headers.get(name.upper())


def _token_matches(actual, expected):
    return bool(actual and expected and hmac.compare_digest(str(actual), str(expected)))


def _service_identity(headers):
    token = _header_value(headers, "x-dashboard-service-token")
    if not token:
        authorization = _header_value(headers, "authorization") or ""
        prefix = "bearer "
        if authorization.lower().startswith(prefix):
            token = authorization[len(prefix):].strip()
    expected = service_token()
    if not _token_matches(token, expected):
        return None
    username = _header_value(headers, "x-dashboard-service-user") or "platform-service"
    return {
        "username": username,
        "email": None,
        "provider": "service-token",
        "auth_mode": "service-token",
        "authenticated": True,
        "auth_strength": "service-token",
    }


def _trusted_header_identity(headers, mode):
    username = (
        _header_value(headers, "x-auth-request-user")
        or _header_value(headers, "x-forwarded-user")
    )
    email = (
        _header_value(headers, "x-auth-request-email")
        or _header_value(headers, "x-forwarded-email")
    )
    provider = _header_value(headers, "x-auth-provider") or "trusted-proxy"
    secret = trusted_auth_secret()
    supplied = _header_value(headers, "x-dashboard-auth-secret")
    secret_ok = _token_matches(supplied, secret)
    if enforcement_mode() == "enforce" and not secret:
        return {
            "username": username or "anonymous",
            "email": email,
            "provider": provider,
            "auth_mode": mode,
            "authenticated": False,
            "auth_failure": "trusted_auth_secret_not_configured",
        }
    if secret and not secret_ok:
        return {
            "username": username or "anonymous",
            "email": email,
            "provider": provider,
            "auth_mode": mode,
            "authenticated": False,
            "auth_failure": "missing_or_invalid_trusted_auth_secret",
        }
    return {
        "username": username or "anonymous",
        "email": email,
        "provider": provider,
        "auth_mode": mode,
        "authenticated": bool(username),
        "auth_failure": None if username else "missing_authenticated_user",
        "auth_strength": "trusted-proxy-header",
    }


def request_identity_from_headers(headers):
    mode = auth_mode()
    service_identity = _service_identity(headers)
    if service_identity:
        return service_identity
    if mode == "disabled":
        return {
            "username": "local-admin",
            "email": None,
            "provider": "local",
            "auth_mode": mode,
            "authenticated": True,
            "auth_strength": "disabled-admin",
        }
    if mode == "header":
        header_identity = _trusted_header_identity(headers, mode)
        if header_identity.get("authenticated") or _header_value(headers, "x-auth-request-user"):
            return header_identity
        cookie_identity = _identity_from_session_cookie(headers, mode)
        if cookie_identity:
            return cookie_identity
        return header_identity
    return {
        "username": "anonymous",
        "email": None,
        "provider": "unsupported",
        "auth_mode": mode,
        "authenticated": False,
        "auth_failure": "unsupported_auth_mode",
    }


def request_identity(request):
    return request_identity_from_headers(getattr(request, "headers", {}) or {})


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
    if upper_method == "OPTIONS":
        return None
    if path == "/login" or path.startswith("/login?"):
        return None
    if path in ("/api/auth/login", "/api/auth/logout"):
        return None
    if path == "/health":
        return None if public_health() else "health:read"
    if path == "/" or path.startswith("/static/") or path in ("/docs", "/redoc", "/openapi.json"):
        return "ui:read" if protect_ui() else None
    if path in PUBLIC_PATHS or any(path.startswith(prefix) for prefix in PUBLIC_PATHS if prefix.endswith("/")):
        return None
    for route_method, pattern, permission in ROUTE_REQUIREMENTS:
        if route_method == upper_method and fnmatch.fnmatch(path, pattern):
            return permission
    if path.startswith("/api/"):
        return "platform:unknown"
    return "ui:read" if protect_ui() else None


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


async def evaluate_headers(method, path, headers):
    identity = request_identity_from_headers(headers or {})
    mode = identity["auth_mode"]
    required = required_permission(method, path)
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
    if identity.get("auth_mode") == "service-token":
        return {
            "allow": True,
            "decision": "allow",
            "reason": "service_token_authenticated",
            "identity": identity,
            "roles": ["platform-admin"],
            "capabilities": ["*"],
            "required_permission": required,
            "enforcement": enforcement_mode(),
            "max_classification": "secret",
            "scopes": [],
        }
    if not identity.get("authenticated"):
        return {
            "allow": enforcement_mode() != "enforce",
            "decision": "deny",
            "reason": identity.get("auth_failure") or "unauthenticated",
            "identity": identity,
            "roles": [],
            "capabilities": [],
            "required_permission": required,
            "enforcement": enforcement_mode(),
        }

    session_subject = identity.get("session_subject")
    if isinstance(session_subject, dict):
        roles = session_subject.get("roles") or []
        capabilities = session_subject.get("capabilities") or []
        scopes = session_subject.get("scopes") or []
        max_allowed = session_subject.get("max_classification") or "internal"
        allowed = capability_matches(capabilities, required)
        return {
            "allow": allowed or enforcement_mode() != "enforce",
            "decision": "allow" if allowed else "deny",
            "reason": "signed_session_subject_match" if allowed else "missing_required_permission",
            "identity": identity,
            "roles": roles,
            "capabilities": capabilities,
            "scopes": scopes,
            "max_classification": max_allowed,
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


async def evaluate_request(request):
    return await evaluate_headers(
        getattr(request, "method", "GET"),
        getattr(getattr(request, "url", None), "path", "/"),
        getattr(request, "headers", {}) or {},
    )


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
    policy_snapshot = policy_snapshot or {}
    human_summary = policy_snapshot.get("human_summary") or (
        f"{actor or 'unknown'} {decision} for {action} on {resource_type}/{resource_id}: {reason}. "
        "No credential value was returned."
    )
    policy_snapshot = {
        **policy_snapshot,
        "human_summary": human_summary,
        "secret_values_returned": False,
        "vault_provider": policy_snapshot.get("vault_provider") or vault_providers.provider_name(),
    }
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
        json_dumps(policy_snapshot),
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
            "human_summary": human_summary,
            "secret_values_returned": False,
            "vault_provider": policy_snapshot.get("vault_provider"),
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
    requested_permissions = requested_permissions or [
        "tickets:read",
        "tickets:note",
        "tickets:request_info",
        "access:request",
        "changes:read",
        "changes:request",
        "changes:complete",
        "agents:read",
        "workflows:read",
        "postmortems:read",
        "postmortems:write",
        "knowledge:read",
    ]
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


def _workflow_policy_lease_specs(workflow):
    policy = _json_value((workflow or {}).get("approval_policy"), {})
    raw_specs = (
        policy.get("preapproved_leases")
        or policy.get("agent_vault_leases")
        or policy.get("vault_leases")
        or []
    )
    if isinstance(raw_specs, dict):
        raw_specs = [raw_specs]
    specs = []
    for item in raw_specs:
        if not isinstance(item, dict) or item.get("enabled") is False:
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
                "granted_by": f"workflow:{workflow.get('id')}",
                "policy_snapshot": {
                    "source": "workflow_preapproved_lease",
                    "workflow_id": workflow.get("id"),
                    "workflow_key": workflow.get("workflow_key"),
                    "workflow_status": workflow.get("status"),
                    "workflow_name": workflow.get("name"),
                    "requires_change_approval_for_mutation": item.get("requires_change_approval_for_mutation", True),
                    "secret_values_stored": False,
                },
            })
    return specs


async def _workflow_lease_specs(ticket):
    workflow_key = workflow_key_for_ticket(ticket or {})
    if not workflow_key:
        return []
    rows = await fetchall(
        """
        SELECT id, name, status, reviewed_at, workflow_key, approval_policy
        FROM agent_workflows
        WHERE workflow_key = $1
          AND status IN ('active', 'approved')
          AND reviewed_at IS NOT NULL
        ORDER BY
          CASE WHEN status = 'active' THEN 0 ELSE 1 END,
          reviewed_at DESC NULLS LAST,
          updated_at DESC
        LIMIT 1
        """,
        workflow_key,
    )
    specs = []
    for row in rows or []:
        specs.extend(_workflow_policy_lease_specs(row))
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
        """
        SELECT id, title, description, itop_class, provider_class,
               owning_group, security_classification
        FROM tickets
        WHERE id = $1
        """,
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
    workflow_leases = await _workflow_lease_specs(ticket) if ticket else []
    leases.extend(workflow_leases)

    for lease in leases:
        policy_snapshot = {
            "spawned_by": subject.get("identity", {}).get("username", "system"),
            "roles": subject.get("roles", []),
            "max_classification": subject.get("max_classification", "internal"),
            "note": "Credential values remain in the external vault; this row is only a scoped lease reference.",
            "vault_provider": vault_providers.provider_name(),
            "resolver_mode": vault_providers.resolver_mode(),
            "secret_values_stored": False,
        }
        policy_snapshot.update(lease.get("policy_snapshot") or {})
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
            lease.get("granted_by") or subject.get("identity", {}).get("username", "system"),
            lease.get("expires_at"),
            json_dumps(policy_snapshot),
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
        {
            "ticket_id": ticket_id,
            "lease_count": len(rows),
            "workflow_preapproved_lease_count": len(workflow_leases),
            "vault_provider": vault_providers.provider_name(),
            "secret_values_returned": False,
            "human_summary": (
                f"Agent {agent_id} received {len(rows)} scoped vault lease references "
                f"at spawn; {len(workflow_leases)} came from an approved workflow policy. "
                "No credential values were written or returned."
            ),
        },
    )
    return {
        "agent_id": agent_id,
        "ticket_id": ticket_id,
        "leases": rows,
        "workflow_preapproved_lease_count": len(workflow_leases),
        "broker_metadata": vault_providers.broker_metadata(),
    }


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
            human_summary = (
                f"Agent {agent_id} was allowed {action} access to "
                f"{system}:{resource_type}/{resource_id} through scoped lease {row.get('id')}. "
                f"The dashboard returned vault reference {row.get('credential_ref')} and no secret value."
            )
            broker_trace = {
                **vault_providers.broker_metadata(system),
                "audited": True,
                "decision": "allow",
                "reason": "agent_vault_lease_match",
                "human_summary": human_summary,
            }
            await audit_resource_decision(
                f"agent_{agent_id}",
                "agent",
                agent_id,
                action,
                f"{system}:{resource_type}",
                resource_id,
                "allow",
                "agent_vault_lease_match",
                {
                    "lease_id": row.get("id"),
                    "credential_ref": row.get("credential_ref"),
                    **broker_trace,
                },
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
                "broker_trace": broker_trace,
                "note": "Use the credential vault resolver for this reference; secret values are never returned by the dashboard.",
            }
    human_summary = (
        f"Agent {agent_id} was denied {action} access to "
        f"{system}:{resource_type}/{resource_id} because no active scoped lease matched. "
        "No credential value was returned; the agent must create an access request."
    )
    broker_trace = {
        **vault_providers.broker_metadata(system),
        "audited": True,
        "decision": "deny",
        "reason": "missing_agent_vault_lease",
        "human_summary": human_summary,
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
        {"active_lease_count": len(rows), **broker_trace},
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
        "broker_trace": broker_trace,
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
            "vault_provider": vault_providers.provider_name(),
            "secret_values_returned": False,
            "human_summary": (
                f"Approved access gate granted agent {agent_id} {action} access to "
                f"{system}:{resource_type}/{resource_id} as scoped vault reference {credential_ref}. "
                "No credential value was returned."
            ),
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
