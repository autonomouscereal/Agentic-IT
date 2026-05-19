from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio
import os
from urllib.parse import quote

from database import get_pool
from routes import (
    tools,
    tickets,
    agents,
    changes,
    dashboard,
    agent_skills,
    postmortems,
    workflows,
    providers,
    knowledge,
    setup,
    access,
    intake,
    cicd,
    wazuh,
    auth,
)
from services import itop_sync, health_check, task_tracker, agent_auditor
from services import access_control
from services.event_logger import log_event

APP_TITLE = "Agentic Operations API"
APP_VERSION = "1.3.0"

_background_tasks = []
_broadcast = None


async def broadcast(message: dict):
    """Send a real-time update to all connected WebSocket clients."""
    if _broadcast:
        await _broadcast(message)


@asynccontextmanager
async def lifespan(application: FastAPI):
    global _broadcast, _background_tasks

    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
        print("DB connection verified")
        await log_event("system", "info", "app", "startup", "database_connected")
    except Exception as e:
        print(f"DB connection warning on startup: {e}")
        await log_event("system", "error", "app", "startup_failed", str(e))

    # Wire up WebSocket broadcast
    from routes.agents import broadcast_agent_update
    _broadcast = broadcast_agent_update
    task_tracker.set_broadcast(_broadcast)

    # Start background services
    if os.getenv("ITOP_SYNC_ENABLED", "true").lower() in ("1", "true", "yes", "on"):
        sync_task = asyncio.create_task(itop_sync.sync_loop(broadcast_fn=_broadcast))
    else:
        sync_task = None
        await log_event("sync", "info", "app", "itop_sync_disabled", "ITOP_SYNC_ENABLED=false")
    health_task = asyncio.create_task(health_check.health_loop())
    tracker_task = asyncio.create_task(task_tracker.track_loop())
    auditor_task = asyncio.create_task(agent_auditor.audit_loop())
    _background_tasks = [task for task in (sync_task, health_task, tracker_task, auditor_task) if task]
    print(f"Started {len(_background_tasks)} background services")
    await log_event("system", "info", "app", "background_services_started",
                    str(len(_background_tasks)))
    yield
    for task in _background_tasks:
        task.cancel()
    print("Background services stopped")
    await log_event("system", "info", "app", "shutdown", "services_stopped")

app = FastAPI(title=APP_TITLE, version=APP_VERSION, lifespan=lifespan)

def _cors_origins():
    raw = os.getenv("DASHBOARD_CORS_ORIGINS", "").strip()
    return [item.strip() for item in raw.split(",") if item.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins(),
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def access_control_middleware(request, call_next):
    decision = await access_control.evaluate_request(request)
    request.state.access_decision = decision
    if not decision.get("allow"):
        await access_control.audit_decision(decision, request.method, request.url.path, 403)
        accept = (request.headers.get("accept") or "").lower()
        if "text/html" in accept and not request.url.path.startswith("/api/"):
            target = request.url.path
            if request.url.query:
                target += "?" + request.url.query
            return RedirectResponse(f"/login?next={quote(target)}", status_code=303)
        response = JSONResponse(
            {
                "error": "access_denied",
                "reason": decision.get("reason"),
                "required_permission": decision.get("required_permission"),
                "authenticated": bool((decision.get("identity") or {}).get("authenticated")),
            },
            status_code=403,
        )
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        return response
    response = await call_next(request)
    if access_control.auth_mode() != "disabled":
        await access_control.audit_decision(decision, request.method, request.url.path, response.status_code)
    session_cookie = access_control.create_session_cookie(decision.get("identity"))
    if session_cookie:
        response.set_cookie(
            "dashboard_session",
            session_cookie,
            max_age=access_control.session_ttl_seconds(),
            httponly=True,
            secure=access_control.cookie_secure(),
            samesite="lax",
        )
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "no-referrer")
    response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
    if os.getenv("DASHBOARD_HSTS", "true").strip().lower() not in ("0", "false", "no", "off"):
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
    return response

app.include_router(tools.router)
app.include_router(tickets.router)
app.include_router(agents.router)
app.include_router(changes.router)
app.include_router(dashboard.router)
app.include_router(agent_skills.router)
app.include_router(postmortems.router)
app.include_router(workflows.router)
app.include_router(providers.router)
app.include_router(knowledge.router)
app.include_router(setup.router)
app.include_router(access.router)
app.include_router(intake.router)
app.include_router(cicd.router)
app.include_router(wazuh.router)
app.include_router(auth.router)

frontend_dir = "/frontend"

if os.path.isdir(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

@app.get("/")
async def root():
    index_path = os.path.join(frontend_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return JSONResponse({"error": "Frontend not found"}, status_code=404)


@app.get("/login")
async def login_page():
    login_path = os.path.join(frontend_dir, "login.html")
    if os.path.exists(login_path):
        return FileResponse(login_path)
    return JSONResponse({"error": "Login page not found"}, status_code=404)

@app.get("/favicon.ico")
async def favicon():
    return Response(status_code=204)

@app.get("/health")
async def health():
    return {"status": "ok", "version": APP_VERSION}
