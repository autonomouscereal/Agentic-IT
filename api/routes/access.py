from fastapi import APIRouter, Body, Request
from database import fetchall, fetchrow, execute, fetchval, json_dumps
from services.event_logger import log_event
from services import access_control

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
        SELECT u.*,
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
    }
