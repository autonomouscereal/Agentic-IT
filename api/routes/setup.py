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
    model: str = Body("qwen/qwen3.6-27b"),
    notes: str = Body(""),
    sync_provider: bool = Body(False),
    spawn_agent: bool = Body(False),
):
    """Create a tracked setup ticket and optionally assign an agent.

    This keeps deployment work visible in the same ticket/approval/audit system
    used for customer operations. External ITSM sync is explicit and provider
    agnostic.
    """
    plan = platform_manifest.build_setup_plan(
        profile=profile,
        include=include,
        exclude=exclude,
        existing_tools=existing_tools,
        deploy_missing=deploy_missing,
    )
    description = platform_manifest.plan_to_ticket_description(plan, ai_base_url, model, notes)
    ticket = await ticket_service.create_ticket(
        title=f"Deploy agentic IT/SOC platform profile: {profile}",
        description=description,
        ticket_class="NormalChange",
        status="new",
        priority="P2",
        provider="local",
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
                    f"ticket_{ticket['id']}", {"profile": profile, "spawn_agent": spawn_agent})

    result = {"ticket": ticket, "plan": plan}
    if spawn_agent:
        from services import agent_runner
        prompt = (
            "You are deploying a modular, product-agnostic agentic IT/SOC platform from a setup ticket. "
            "Read the ticket context, identify existing products versus gaps, integrate providers where they exist, "
            "deploy only approved missing modules, create change requests before environment-changing actions, "
            "run health checks and smoke tests, document every decision as ticket notes, and stop for human review "
            "before production-impacting changes. Do not assume iTop/Wazuh/Mailcow/GitLab are mandatory; they are "
            "reference open-source modules behind provider contracts."
        )
        spawn = await agent_runner.spawn_agent(ticket["id"], model, prompt, "platform_setup")
        result["agent"] = spawn
    return result
