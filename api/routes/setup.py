from fastapi import APIRouter, Body
from database import fetchall
from services import platform_manifest, ticket_service
from services.event_logger import log_event

router = APIRouter(prefix="/api/setup", tags=["setup"])


MODULE_TOOL_ALIASES = {
    "soc-dashboard": ["agentic operations", "soc dashboard", "soc dashboard control plane"],
    "local-ticketing": ["local canonical ticket provider"],
    "agent-memory": ["agent memory"],
    "ai-proxy": ["ai proxy", "ai model proxy", "model gateway"],
    "itop": ["itop"],
    "wazuh": ["wazuh"],
    "mailcow": ["mailcow", "mailcow api/ui shim"],
    "roundcube-webmail": ["roundcube", "roundcube webmail"],
    "keycloak": ["keycloak"],
    "gitlab": ["gitlab"],
    "searxng": ["searxng"],
    "zeek": ["zeek"],
    "suricata": ["suricata"],
}
BUILT_IN_READY_MODULES = {
    "soc-dashboard",
    "local-ticketing",
    "provider-contracts",
    "service-desk-intake",
    "ticketing-provider-adapter",
    "cicd-provider-adapter",
}


def _norm(value):
    return str(value or "").lower().replace("-", " ").replace("_", " ").strip()


def _module_notes_for(module_notes, module_id):
    if isinstance(module_notes, dict):
        return str(module_notes.get(module_id) or "").strip()
    return ""


def _combined_notes(global_notes, module_notes, module_id):
    parts = []
    if str(global_notes or "").strip():
        parts.append(str(global_notes).strip())
    scoped = _module_notes_for(module_notes, module_id)
    if scoped:
        parts.append(f"Module-specific operator notes: {scoped}")
    return "\n\n".join(parts)


async def _module_statuses():
    rows = await fetchall("""
        SELECT t.name, t.status, t.last_check, t.host, t.port, tc.status AS last_check_status
        FROM tools t
        LEFT JOIN (
            SELECT tool_id, status,
                   ROW_NUMBER() OVER (PARTITION BY tool_id ORDER BY timestamp DESC) as rn
            FROM tool_checks
        ) tc ON t.id = tc.tool_id AND tc.rn = 1
        WHERE lower(t.name) <> 'comfyui'
    """)
    tool_rows = []
    for row in rows:
        row_status = row.get("last_check_status") or row.get("status") or "unknown"
        tool_rows.append({
            "name": row.get("name"),
            "status": row_status,
            "host": row.get("host"),
            "port": row.get("port"),
        })
    statuses = {}
    for module in platform_manifest.load_manifest().get("modules", []):
        module_id = module.get("id")
        module_names = [_norm(module_id), _norm(module.get("name"))]
        module_names.extend(MODULE_TOOL_ALIASES.get(module_id, []))
        matched = None
        for tool in tool_rows:
            tool_name = _norm(tool.get("name"))
            if any(alias and (alias == tool_name or alias in tool_name) for alias in module_names):
                matched = tool
                break
        if matched:
            check_status = matched.get("status") or "unknown"
            if check_status == "healthy":
                deployment_status = "ready"
            elif check_status in ("down", "failed"):
                deployment_status = "down"
            elif check_status == "degraded":
                deployment_status = "degraded"
            else:
                deployment_status = "configured"
            source = "tool_inventory"
        elif module_id in BUILT_IN_READY_MODULES or (
            module.get("deploy_strategy") == "dashboard" and module.get("status") == "implemented"
        ):
            check_status = "healthy"
            deployment_status = "built_in"
            source = "dashboard_builtin"
        else:
            check_status = "unknown"
            deployment_status = "not_configured"
            source = "manifest"
        statuses[module_id] = {
            "module_id": module_id,
            "deployment_status": deployment_status,
            "check_status": check_status,
            "source": source,
            "tool": matched,
        }
    return statuses


@router.get("/manifest")
async def get_manifest():
    """Return the provider-agnostic platform module registry."""
    return platform_manifest.load_manifest()


@router.get("/profiles")
async def get_profiles():
    return {"profiles": platform_manifest.list_profiles()}


@router.get("/status")
async def get_setup_status():
    statuses = await _module_statuses()
    return {"module_statuses": statuses, "count": len(statuses)}


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
    module_notes=Body(None),
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
    actionable_statuses = {"deploy", "integrate_existing", "blueprint", "external_optional", "undeploy", "redeploy"}
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
            description=platform_manifest.module_ticket_description(
                parent_ticket["id"],
                step,
                runtime=runtime,
                notes=_combined_notes(notes, module_notes, step.get("module_id")),
            ),
            ticket_class="NormalChange" if step.get("status") in ("deploy", "undeploy", "redeploy") else "UserRequest",
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


@router.post("/module-ticket")
async def create_module_ticket(
    module_id: str = Body(...),
    action: str = Body("deploy"),
    notes: str = Body(""),
    ai_base_url: str = Body(None),
    model: str = Body("deepseek/deepseek-v4-flash"),
    proxy_mode: str = Body(None),
    proxy_url: str = Body(None),
    harness: str = Body(None),
    provider: str = Body(None),
    sync_provider: bool = Body(None),
    spawn_agent: bool = Body(False),
):
    """Create a one-module setup/integration/teardown ticket."""
    statuses = await _module_statuses()
    step = platform_manifest.module_step(
        module_id,
        action=action,
        deployment_status=statuses.get(module_id) or {},
    )
    if not step:
        return {"error": "module_not_found", "module_id": module_id}
    runtime = {
        "proxy_mode": proxy_mode,
        "proxy_url": proxy_url or ai_base_url,
        "harness": harness,
        "provider": provider,
    }
    status = step.get("status")
    verb = {
        "deploy": "Deploy",
        "integrate_existing": "Integrate",
        "already_active": "Verify",
        "undeploy": "Undeploy",
        "redeploy": "Reinstall",
        "blueprint": "Blueprint",
        "external_optional": "Review external",
    }.get(status, "Setup")
    ticket = await ticket_service.create_ticket(
        title=f"{verb} module: {step.get('name')} ({module_id})",
        description=platform_manifest.module_ticket_description(None, step, runtime=runtime, notes=notes),
        ticket_class="NormalChange" if status in ("deploy", "undeploy", "redeploy") else "UserRequest",
        status="new",
        priority="P3",
        sync_provider=sync_provider,
        created_by="setup-wizard",
        auto_assign=False,
    )
    await ticket_service.add_note(
        ticket["id"],
        (
            f"Single-module setup ticket for `{module_id}` action `{status}`. "
            "Keep all evidence, approvals, teardown notes, and completion notes scoped to this module."
        ),
        author="setup-wizard",
        source="dashboard",
        external_ref=f"setup_module:{module_id}:{status}",
    )
    await log_event("setup", "info", "setup-wizard", "setup_module_ticket_created",
                    f"ticket_{ticket['id']}", {
                        "module_id": module_id,
                        "action": status,
                        "spawn_agent": spawn_agent,
                        "deployment_status": (statuses.get(module_id) or {}).get("deployment_status"),
                    })
    result = {"ticket": ticket, "module": step, "deployment_status": statuses.get(module_id)}
    if spawn_agent:
        from services import agent_runner
        prompt = (
            f"You are working single-module setup ticket {ticket['id']} for module `{module_id}` action `{status}`. "
            "Work only this module. Read the ticket context, verify current deployment status, and write a plan/evidence note. "
            "For deploy, redeploy, integrate, or undeploy work, create approval gates before changing infrastructure, credentials, routing, data, or provider settings. "
            "If credentials or access are missing, create an access request and stop at a waiting checkpoint. "
            "Write checkpoint.json with a clear status and reply with a one-line summary."
        )
        result["agent"] = await agent_runner.spawn_agent(ticket["id"], model, prompt, "platform_setup")
    return result
