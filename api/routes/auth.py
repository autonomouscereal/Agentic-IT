from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, RedirectResponse
from urllib.parse import quote
from database import fetchrow, execute
from services import access_control
from services.event_logger import log_event

router = APIRouter(prefix="/api/auth", tags=["auth"])


def _wants_html(request):
    accept = (request.headers.get("accept") or "").lower()
    content_type = (request.headers.get("content-type") or "").lower()
    return "text/html" in accept or "application/x-www-form-urlencoded" in content_type


def _safe_next(value):
    value = (value or "/").strip()
    if not value.startswith("/") or value.startswith("//"):
        return "/"
    if value.startswith("/api/") or value == "/login":
        return "/"
    return value


@router.post("/login")
async def login(request: Request):
    username = ""
    password = ""
    next_url = "/"
    content_type = (request.headers.get("content-type") or "").lower()
    if "application/x-www-form-urlencoded" in content_type:
        form = await request.form()
        username = form.get("username")
        password = form.get("password")
        next_url = form.get("next") or "/"
    else:
        try:
            payload = await request.json()
        except Exception:
            payload = {}
        username = payload.get("username")
        password = payload.get("password")
        next_url = payload.get("next") or "/"

    username = (username or "").strip()
    password = password or ""
    user = await fetchrow(
        """
        SELECT id, username, display_name, email, provider, enabled, password_hash
        FROM dashboard_users
        WHERE username = $1
        """,
        username,
    )
    password_ok = bool(user and user.get("enabled") and access_control.verify_password(password, user.get("password_hash")))
    if not password_ok:
        if user:
            await execute(
                """
                UPDATE dashboard_users
                SET failed_login_count = COALESCE(failed_login_count, 0) + 1,
                    last_failed_login_at = NOW(),
                    updated_at = NOW()
                WHERE id = $1
                """,
                user["id"],
            )
        await log_event("access", "warning", username or "anonymous", "dashboard_login_failed",
                        "dashboard_login", {"username": username, "reason": "invalid_credentials"})
        if _wants_html(request):
            return RedirectResponse(f"/login?error=1&next={quote(_safe_next(next_url))}", status_code=303)
        return JSONResponse({"error": "invalid_credentials"}, status_code=401)

    await execute(
        """
        UPDATE dashboard_users
        SET failed_login_count = 0,
            last_login_at = NOW(),
            updated_at = NOW()
        WHERE id = $1
        """,
        user["id"],
    )
    identity = {
        "username": user["username"],
        "email": user.get("email"),
        "provider": user.get("provider") or "local",
        "auth_mode": "login",
        "authenticated": True,
        "auth_strength": "local-password",
    }
    cookie = access_control.create_session_cookie(identity)
    await log_event("access", "info", user["username"], "dashboard_login_success",
                    "dashboard_login", {"provider": user.get("provider") or "local"})
    if _wants_html(request):
        response = RedirectResponse(_safe_next(next_url), status_code=303)
    else:
        response = JSONResponse({"status": "ok", "username": user["username"]})
    response.set_cookie(
        "dashboard_session",
        cookie,
        max_age=access_control.session_ttl_seconds(),
        httponly=True,
        secure=access_control.cookie_secure(),
        samesite="lax",
    )
    return response


@router.post("/logout")
async def logout():
    response = RedirectResponse("/login?logged_out=1", status_code=303)
    response.delete_cookie("dashboard_session")
    return response
