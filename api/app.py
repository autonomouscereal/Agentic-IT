from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import asyncio
import os

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
)
from services import itop_sync, health_check, task_tracker
from services.event_logger import log_event

APP_TITLE = "SOC Dashboard API"
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
    _background_tasks = [task for task in (sync_task, health_task, tracker_task) if task]
    print(f"Started {len(_background_tasks)} background services")
    await log_event("system", "info", "app", "background_services_started",
                    str(len(_background_tasks)))
    yield
    for task in _background_tasks:
        task.cancel()
    print("Background services stopped")
    await log_event("system", "info", "app", "shutdown", "services_stopped")

app = FastAPI(title=APP_TITLE, version=APP_VERSION, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

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

frontend_dir = "/frontend"

if os.path.isdir(frontend_dir):
    app.mount("/static", StaticFiles(directory=frontend_dir), name="static")

@app.get("/")
async def root():
    index_path = os.path.join(frontend_dir, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return JSONResponse({"error": "Frontend not found"}, status_code=404)

@app.get("/health")
async def health():
    return {"status": "ok", "version": APP_VERSION}
