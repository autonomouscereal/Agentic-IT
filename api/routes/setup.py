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
    module_actions=Body(None),
):
    """Build a deterministic setup plan from the manifest and operator choices."""
    plan = platform_manifest.build_setup_plan(
        profile=profile,
        include=include,
        exclude=exclude,
        existing_tools=existing_tools,
        deploy_missing=deploy_missing,
        module_actions=module_actions,
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
    module_actions=Body(None),
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
        module_actions=module_actions,
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
    parent_ticket = await ticket_service.create_ticket(
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
        parent_ticket["id"],
        "Setup plan generated from platform manifest. This parent ticket tracks the deployment package; scoped child tickets track each enabled module or integration.",
        author="setup-wizard",
        source="dashboard",
    )

    runtime = {
        "proxy_mode": proxy_mode,
        "proxy_url": proxy_url,
        "harness": harness,
        "provider": provider,
    }
    actionable_statuses = {"deploy", "integrate_existing", "blueprint", "external_optional"}
    module_tickets = []
    skipped_steps = []
    for step in plan.get("steps", []):
        if step.get("status") not in actionable_statuses:
            skipped_steps.append({
                "module_id": step.get("module_id"),
                "name": step.get("name"),
                "status": step.get("status"),
                "disabled_dependencies": step.get("disabled_dependencies") or [],
            })
            continue
        child = await ticket_service.create_ticket(
            title=f"Setup module: {step.get('name')} ({step.get('module_id')})",
            description=platform_manifest.module_ticket_description(parent_ticket["id"], step, runtime=runtime, notes=notes),
            ticket_class="NormalChange" if step.get("status") == "deploy" else "UserRequest",
            status="new",
            priority="P3",
            sync_provider=sync_provider,
            created_by="setup-wizard",
            auto_assign=False,
        )
        await ticket_service.add_note(
            child["id"],
            (
                f"Child setup ticket for parent `{parent_ticket['id']}`. "
                f"Module `{step.get('module_id')}` action `{step.get('status')}`. "
                "Keep evidence, approval gates, and completion notes scoped to this module."
            ),
            author="setup-wizard",
            source="dashboard",
            external_ref=f"setup_parent:{parent_ticket['id']}:module:{step.get('module_id')}",
        )
        module_tickets.append({
            "module_id": step.get("module_id"),
            "name": step.get("name"),
            "status": step.get("status"),
            "ticket": child,
        })

    child_lines = [
        f"- ticket {row['ticket']['id']}: {row['name']} ({row['module_id']}) [{row['status']}]"
        for row in module_tickets
    ]
    skipped_lines = [
        f"- {row['name']} ({row['module_id']}) [{row['status']}]"
        for row in skipped_steps
    ]
    note_parts = [
        f"Created {len(module_tickets)} scoped setup child tickets from parent `{parent_ticket['id']}`.",
    ]
    if child_lines:
        note_parts.extend(["", "Child tickets:", *child_lines])
    disabled_modules = plan.get("summary", {}).get("disabled_modules") or []
    if disabled_modules:
        note_parts.extend(["", "Disabled / not in scope modules:", ", ".join(disabled_modules)])
    if skipped_lines:
        note_parts.extend(["", "No child ticket created for non-actionable or blocked plan steps:", *skipped_lines])
    await ticket_service.add_note(
        parent_ticket["id"],
        "\n".join(note_parts),
        author="setup-wizard",
        source="dashboard",
        external_ref=f"setup_children:{parent_ticket['id']}",
    )
    await log_event("setup", "info", "setup-wizard", "setup_ticket_created",
                    f"ticket_{parent_ticket['id']}", {
                        "profile": profile,
                        "spawn_agent": spawn_agent,
                        "proxy_mode": proxy_mode,
                        "proxy_url": proxy_url,
                        "harness": harness,
                        "provider": provider,
                        "child_ticket_count": len(module_tickets),
                        "disabled_modules": plan.get("summary", {}).get("disabled_modules") or [],
                    })

    result = {
        "ticket": parent_ticket,
        "parent_ticket": parent_ticket,
        "module_tickets": module_tickets,
        "skipped_steps": skipped_steps,
        "plan": plan,
    }
    if spawn_agent:
        from services import agent_runner
        prompt = (
            f"You are performing the bounded first-pass onboarding verification for setup parent ticket {parent_ticket['id']}. "
            "Do not deploy modules, do not change infrastructure, and do not call external provider admin APIs. "
            "Use only the dashboard API at http://localhost:8000 and files in this workspace. "
            f"Steps: 1. GET /api/tickets/{parent_ticket['id']}/context. "
            "2. GET /api/agents/runner-health. "
            "3. GET /api/setup/manifest. "
            "4. GET /api/setup/profiles. "
            f"5. POST /api/tickets/{parent_ticket['id']}/notes with author setup-agent, source agent, "
            "visibility internal, and a body starting exactly "
            "\"SETUP_ONBOARDING_BOOTSTRAP_COMPLETE\" that summarizes dashboard health, proxy/model visibility, "
            f"selected harness, missing credentials or approvals, and the {len(module_tickets)} scoped child setup tickets. "
            "6. Write checkpoint.json with step setup-onboarding-bootstrap, status done, progress_pct 100, "
            "output SETUP_ONBOARDING_BOOTSTRAP_COMPLETE, and an ISO timestamp. "
            "7. Reply exactly: SETUP_ONBOARDING_BOOTSTRAP_COMPLETE"
        )
        spawn = await agent_runner.spawn_agent(parent_ticket["id"], model, prompt, "platform_setup")
        result["agent"] = spawn
    return result
