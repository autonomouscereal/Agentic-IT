from fastapi import APIRouter, Body
from services import platform_manifest, ticket_service
from services.event_logger import log_event

router = APIRouter(prefix="/api/setup", tags=["setup"])


@router.get("/manifest")
async def get_manifest():
    """Return the provider-agnostic platform module registry."""
    return platform_manifest.load_manifest()


@router.get("/profiles")
async def get_profiles():
    return {"profiles": platform_manifest.list_profiles()}


@router.post("/plan")
async def create_plan(
    profile: str = Body("soc"),
    include: list = Body([]),
    exclude: list = Body([]),
    existing_tools: list = Body([]),
    deploy_missing: bool = Body(True),
):
    """Build a deterministic setup plan from the manifest and operator choices."""
    plan = platform_manifest.build_setup_plan(
        profile=profile,
        include=include,
        exclude=exclude,
        existing_tools=existing_tools,
        deploy_missing=deploy_missing,
    )
    await log_event("setup", "info", "dashboard", "setup_plan_generated", profile, plan.get("summary"))
    return plan


@router.post("/ticket")
async def create_setup_ticket(
    profile: str = Body("soc"),
    include: list = Body([]),
    exclude: list = Body([]),
    existing_tools: list = Body([]),
    deploy_missing: bool = Body(True),
    ai_base_url: str = Body(None),
    model: str = Body("deepseek/deepseek-v4-flash"),
    proxy_mode: str = Body(None),
    proxy_url: str = Body(None),
    harness: str = Body(None),
    provider: str = Body(None),
    notes: str = Body(""),
    sync_provider: bool = Body(None),
    spawn_agent: bool = Body(False),
):
    """Create a tracked setup ticket and optionally assign an agent.

    This keeps deployment work visible in the same ticket/approval/audit system
    used for customer operations. External ITSM sync uses the active provider
    automatically unless the caller explicitly selects the local provider.
    """
    plan = platform_manifest.build_setup_plan(
        profile=profile,
        include=include,
        exclude=exclude,
        existing_tools=existing_tools,
        deploy_missing=deploy_missing,
    )
    description = platform_manifest.plan_to_ticket_description(
        plan,
        ai_base_url,
        model,
        notes,
        runtime={
            "proxy_mode": proxy_mode,
            "proxy_url": proxy_url,
            "harness": harness,
            "provider": provider,
        },
    )
    ticket = await ticket_service.create_ticket(
        title=f"Deploy agentic IT/SOC platform profile: {profile}",
        description=description,
        ticket_class="NormalChange",
        status="new",
        priority="P2",
        sync_provider=sync_provider,
        created_by="setup-wizard",
        auto_assign=False,
    )
    await ticket_service.add_note(
        ticket["id"],
        "Setup plan generated from platform manifest. Agent must use provider adapters, approval gates, and health checks before marking complete.",
        author="setup-wizard",
        source="dashboard",
    )
    await log_event("setup", "info", "setup-wizard", "setup_ticket_created",
                    f"ticket_{ticket['id']}", {
                        "profile": profile,
                        "spawn_agent": spawn_agent,
                        "proxy_mode": proxy_mode,
                        "proxy_url": proxy_url,
                        "harness": harness,
                        "provider": provider,
                    })

    result = {"ticket": ticket, "plan": plan}
    if spawn_agent:
        from services import agent_runner
        prompt = (
            f"You are performing the bounded first-pass onboarding verification for setup ticket {ticket['id']}. "
            "Do not deploy modules, do not change infrastructure, and do not call external provider admin APIs. "
            "Use only the dashboard API at http://localhost:8000 and files in this workspace. "
            f"Steps: 1. GET /api/tickets/{ticket['id']}/context. "
            "2. GET /api/agents/runner-health. "
            "3. GET /api/setup/manifest. "
            "4. GET /api/setup/profiles. "
            f"5. POST /api/tickets/{ticket['id']}/notes with author setup-agent, source agent, "
            "visibility internal, and a body starting exactly "
            "\"SETUP_ONBOARDING_BOOTSTRAP_COMPLETE\" that summarizes dashboard health, proxy/model visibility, "
            "selected harness, missing credentials or approvals, and the next operator actions. "
            "6. Write checkpoint.json with step setup-onboarding-bootstrap, status done, progress_pct 100, "
            "output SETUP_ONBOARDING_BOOTSTRAP_COMPLETE, and an ISO timestamp. "
            "7. Reply exactly: SETUP_ONBOARDING_BOOTSTRAP_COMPLETE"
        )
        spawn = await agent_runner.spawn_agent(ticket["id"], model, prompt, "platform_setup")
        result["agent"] = spawn
    return result
