from fastapi import APIRouter, Body, Request
from database import fetchall, fetchrow, execute, fetchval, json_dumps
from services.event_logger import log_event
from services import access_control, sensitive_intake

router = APIRouter(prefix="/api/access", tags=["access"])


DEFAULT_ROLES = [
    ("platform-admin", "Full platform administration"),
    ("soc-manager", "Manage tickets, workflows, agents, and approvals"),
    ("analyst", "View and work assigned tickets"),
    ("auditor", "Read-only access to tickets, logs, approvals, and evidence"),
    ("agent-operator", "Create agents and supervise runs"),
]


async def ensure_defaults():
    for name, description in DEFAULT_ROLES:
        await execute(
            """
            INSERT INTO dashboard_roles (name, description)
            VALUES ($1, $2)
            ON CONFLICT (name) DO UPDATE SET description = EXCLUDED.description
            """,
            name,
            description,
        )


@router.get("/me")
async def me(request: Request):
    await ensure_defaults()
    identity = access_control.request_identity(request)
    roles = []
    if identity["auth_mode"] == "disabled":
        roles = ["platform-admin"]
    else:
        row = await fetchrow("SELECT id FROM dashboard_users WHERE username = $1", identity["username"])
        if row:
            role_rows = await fetchall(
                """
                SELECT r.name
                FROM dashboard_user_roles ur
                JOIN dashboard_roles r ON r.id = ur.role_id
                WHERE ur.user_id = $1
                ORDER BY r.name
                """,
                row["id"],
            )
            roles = [r["name"] for r in role_rows]
    return {"identity": identity, "roles": roles}


@router.get("/roles")
async def list_roles():
    await ensure_defaults()
    rows = await fetchall("SELECT * FROM dashboard_roles ORDER BY name")
    return {"roles": rows}


@router.get("/users")
async def list_users():
    await ensure_defaults()
    rows = await fetchall(
        """
        SELECT u.id,
               u.username,
               u.display_name,
               u.email,
               u.provider,
               u.provider_ref,
               u.enabled,
               u.created_at,
               u.updated_at,
               u.password_changed_at,
               u.failed_login_count,
               u.last_failed_login_at,
               u.last_login_at,
               COALESCE(json_agg(r.name ORDER BY r.name) FILTER (WHERE r.name IS NOT NULL), '[]') AS roles
        FROM dashboard_users u
        LEFT JOIN dashboard_user_roles ur ON ur.user_id = u.id
        LEFT JOIN dashboard_roles r ON r.id = ur.role_id
        GROUP BY u.id
        ORDER BY u.username
        """
    )
    return {"users": rows}


@router.post("/users")
async def upsert_user(
    username: str = Body(...),
    display_name: str = Body(None),
    email: str = Body(None),
    provider: str = Body("local"),
    provider_ref: str = Body(None),
    enabled: bool = Body(True),
):
    await ensure_defaults()
    user_id = await fetchval(
        """
        INSERT INTO dashboard_users (username, display_name, email, provider, provider_ref, enabled)
        VALUES ($1, $2, $3, $4, $5, $6)
        ON CONFLICT (username) DO UPDATE SET
            display_name = EXCLUDED.display_name,
            email = EXCLUDED.email,
            provider = EXCLUDED.provider,
            provider_ref = EXCLUDED.provider_ref,
            enabled = EXCLUDED.enabled,
            updated_at = NOW()
        RETURNING id
        """,
        username,
        display_name,
        email,
        provider,
        provider_ref,
        enabled,
    )
    await log_event("access", "info", "dashboard", "access_user_upserted",
                    f"user_{user_id}", {"username": username, "provider": provider})
    return {"id": user_id, "status": "upserted"}


def _select_secure_value(values, field_key=None, field_types=None, label_contains=None):
    field_types = {str(item).lower() for item in (field_types or []) if item}
    label_contains = [str(item).lower() for item in (label_contains or []) if item]
    if field_key:
        wanted = str(field_key).strip().lower()
        for item in values or []:
            if str(item.get("field_key") or "").strip().lower() == wanted:
                return item
    for item in values or []:
        if field_types and str(item.get("field_type") or "").strip().lower() in field_types:
            return item
    for item in values or []:
        label = str(item.get("field_label") or "").strip().lower()
        if label and any(token in label for token in label_contains):
            return item
    return None


@router.post("/users/secure-local-account")
async def create_secure_local_dashboard_account(
    request_ref: str = Body(...),
    username: str = Body(...),
    display_name: str = Body(None),
    email: str = Body(None),
    role: str = Body("auditor"),
    enabled: bool = Body(True),
    password_field_key: str = Body(None),
):
    """Create a local dashboard login from brokered secure-intake values.

    The adapter resolves the password server-side, hashes it, and returns only
    refs/evidence. Agents never receive the submitted password value.
    """
    await ensure_defaults()
    username = (username or "").strip()
    if not username:
        return {"error": "username_required", "raw_values_returned": False}
    role = (role or "auditor").strip()
    role_row = await fetchrow("SELECT id, name FROM dashboard_roles WHERE name = $1", role)
    if not role_row:
        return {"error": "role_not_found", "role": role, "raw_values_returned": False}

    brokered = await sensitive_intake.get_submitted_values_for_adapter(request_ref)
    if brokered.get("error"):
        return {
            "error": brokered["error"],
            "request_ref": brokered.get("request_ref"),
            "status": brokered.get("status"),
            "raw_values_returned": False,
        }
    values = brokered.get("values") or []
    password_value = _select_secure_value(
        values,
        field_key=password_field_key,
        field_types={"credential"},
        label_contains=("password", "credential", "passcode"),
    )
    if not password_value or not password_value.get("value"):
        return {
            "error": "credential_field_not_found",
            "request_ref": request_ref,
            "available_fields": [
                {
                    "field_key": item.get("field_key"),
                    "field_label": item.get("field_label"),
                    "field_type": item.get("field_type"),
                    "value_ref": item.get("value_ref"),
                }
                for item in values
            ],
            "raw_values_returned": False,
        }

    password_hash = access_control.hash_password(password_value["value"])
    user_row = await fetchrow("SELECT id FROM dashboard_users WHERE username = $1", username)
    if user_row:
        await execute(
            """
            UPDATE dashboard_users
            SET display_name = COALESCE($1, display_name, username),
                email = COALESCE($2, email),
                provider = 'local',
                provider_ref = COALESCE(provider_ref, $3),
                enabled = $4,
                password_hash = $5,
                password_changed_at = NOW(),
                failed_login_count = 0,
                updated_at = NOW()
            WHERE id = $6
            """,
            display_name or username,
            email,
            f"secure-intake:{request_ref}",
            bool(enabled),
            password_hash,
            user_row["id"],
        )
        user_id = user_row["id"]
        status = "updated"
    else:
        user_id = await fetchval(
            """
            INSERT INTO dashboard_users (
                username, display_name, email, provider, provider_ref, enabled,
                password_hash, password_changed_at
            )
            VALUES ($1, $2, $3, 'local', $4, $5, $6, NOW())
            RETURNING id
            """,
            username,
            display_name or username,
            email,
            f"secure-intake:{request_ref}",
            bool(enabled),
            password_hash,
        )
        status = "created"

    await execute("DELETE FROM dashboard_user_roles WHERE user_id = $1", user_id)
    await execute(
        "INSERT INTO dashboard_user_roles (user_id, role_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
        user_id,
        role_row["id"],
    )
    await log_event(
        "access",
        "info",
        "dashboard",
        "secure_local_dashboard_account_upserted",
        f"user_{user_id}",
        {
            "username": username,
            "role": role_row["name"],
            "request_ref": request_ref,
            "password_value_ref": password_value.get("value_ref"),
            "raw_values_logged": False,
        },
    )
    return {
        "id": user_id,
        "status": status,
        "username": username,
        "role": role_row["name"],
        "provider": "local",
        "enabled": bool(enabled),
        "request_ref": request_ref,
        "password_set": True,
        "password_value_ref": password_value.get("value_ref"),
        "raw_values_returned": False,
    }


@router.post("/users/{user_id}/roles")
async def set_user_roles(user_id: int, roles: list = Body(...)):
    await ensure_defaults()
    user = await fetchrow("SELECT id, username FROM dashboard_users WHERE id = $1", user_id)
    if not user:
        return {"error": "User not found"}
    await execute("DELETE FROM dashboard_user_roles WHERE user_id = $1", user_id)
    assigned = []
    for role in roles:
        role_row = await fetchrow("SELECT id, name FROM dashboard_roles WHERE name = $1", role)
        if role_row:
            await execute(
                "INSERT INTO dashboard_user_roles (user_id, role_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                user_id,
                role_row["id"],
            )
            assigned.append(role_row["name"])
    await log_event("access", "info", "dashboard", "access_roles_updated",
                    f"user_{user_id}", {"username": user["username"], "roles": assigned})
    return {"id": user_id, "roles": assigned}


@router.get("/users/{user_id}/scopes")
async def list_user_scopes(user_id: int):
    user = await fetchrow("SELECT id, username FROM dashboard_users WHERE id = $1", user_id)
    if not user:
        return {"error": "User not found"}
    rows = await fetchall(
        """
        SELECT id, user_id, scope_type, scope_value, permissions, created_at, updated_at
        FROM dashboard_user_scopes
        WHERE user_id = $1
        ORDER BY scope_type, scope_value
        """,
        user_id,
    )
    return {"user_id": user_id, "username": user["username"], "scopes": rows}


@router.post("/users/{user_id}/scopes")
async def upsert_user_scope(
    user_id: int,
    scope_type: str = Body(...),
    scope_value: str = Body(...),
    permissions: list = Body([]),
):
    user = await fetchrow("SELECT id, username FROM dashboard_users WHERE id = $1", user_id)
    if not user:
        return {"error": "User not found"}
    scope_id = await fetchval(
        """
        INSERT INTO dashboard_user_scopes (user_id, scope_type, scope_value, permissions)
        VALUES ($1, $2, $3, $4::jsonb)
        ON CONFLICT (user_id, scope_type, scope_value) DO UPDATE SET
            permissions = EXCLUDED.permissions,
            updated_at = NOW()
        RETURNING id
        """,
        user_id,
        scope_type,
        scope_value,
        json_dumps(permissions or []),
    )
    await log_event(
        "access",
        "info",
        "dashboard",
        "access_scope_upserted",
        f"user_{user_id}",
        {"username": user["username"], "scope_type": scope_type, "scope_value": scope_value},
    )
    return {"id": scope_id, "user_id": user_id, "scope_type": scope_type, "scope_value": scope_value}


@router.get("/policies")
async def policies():
    return {
        "auth_mode": access_control.auth_mode(),
        "enforcement": access_control.enforcement_mode(),
        "provider_headers": {
            "username": ["x-auth-request-user", "x-forwarded-user"],
            "email": ["x-auth-request-email", "x-forwarded-email"],
            "provider": ["x-auth-provider"],
        },
        "role_capabilities": access_control.DEFAULT_ROLE_CAPABILITIES,
        "classification_order": access_control.CLASSIFICATION_RANK,
        "route_requirements": [
            {"method": method, "path": path, "permission": permission}
            for method, path, permission in access_control.ROUTE_REQUIREMENTS
        ],
        "agent_permission_boundary": (
            "Agents receive a policy snapshot at spawn time and requested "
            "permissions outside the spawning subject capabilities are trimmed "
            "from the effective envelope and audited. Agents still spawn so "
            "they can hit real permission walls and request access."
        ),
        "agent_vault_boundary": (
            "Each agent gets scoped vault lease references per system/resource/action. "
            "The dashboard returns vault references only, never secret values, and "
            "denies missing leases with HTTP 403 plus audit evidence."
        ),
        "credential_broker": {
            "vault_provider": access_control.vault_providers.provider_name(),
            "resolver_mode": access_control.vault_providers.resolver_mode(),
            "secret_values_returned": False,
            "modes": {
                "lease_reference": "Agent asks for a scoped lease and receives only a vault reference.",
                "prebuilt_provider_endpoint": "Dashboard validates the lease, calls a provider adapter, and returns redacted provider evidence.",
                "customer_adapter": "Deployments can replace the resolver behind the same lease contract.",
            },
        },
        "workflow_preapproved_leases": (
            "Approved workflows may define approval_policy.preapproved_leases "
            "for normal read/investigation access. The runner mints only those "
            "exact scoped references at spawn and still requires change approvals "
            "for mutation/remediation actions."
        ),
    }
