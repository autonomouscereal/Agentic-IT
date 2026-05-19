"""Platform manifest and setup planning helpers.

The manifest is intentionally data-driven so the setup wizard can stay harness
and provider agnostic. This module reads JSON, checks local skill availability
when possible, and builds deterministic installation plans without storing any
secrets.
"""
import json
import os
from pathlib import Path


def _manifest_path():
    override = os.getenv("PLATFORM_MANIFEST_PATH")
    if override:
        return Path(override)
    here = Path(__file__).resolve()
    candidates = [
        Path("/app/platform/manifest.json"),
        here.parents[2] / "platform" / "manifest.json",
        here.parents[1].parent / "platform" / "manifest.json",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


MANIFEST_PATH = _manifest_path()


def load_manifest():
    with MANIFEST_PATH.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    modules = manifest.get("modules", [])
    manifest["modules"] = [_with_skill_status(module) for module in modules]
    return manifest


def list_profiles():
    manifest = load_manifest()
    return manifest.get("profiles", {})


def module_index():
    manifest = load_manifest()
    return {module["id"]: module for module in manifest.get("modules", [])}


def _skill_roots():
    raw = os.getenv(
        "PLATFORM_SKILL_ROOTS",
        "/skills,/app/skills,/root/.claude/skills,/root/.agents/skills,"
        "C:/Users/cereal/.agents/skills,C:/Users/cereal/.claude/skills",
    )
    return [Path(item.strip()) for item in raw.split(",") if item.strip()]


def _with_skill_status(module):
    module = dict(module)
    skill = module.get("skill")
    if not skill:
        module["skill_available"] = True
        module["skill_paths"] = []
        return module

    paths = []
    for root in _skill_roots():
        candidate = root / skill / "SKILL.md"
        if candidate.exists():
            paths.append(str(candidate))
    module["skill_available"] = bool(paths)
    module["skill_paths"] = paths
    return module


def _normalize_module_actions(module_actions=None):
    actions = {}
    if isinstance(module_actions, dict):
        items = module_actions.items()
    elif isinstance(module_actions, list):
        items = []
        for row in module_actions:
            if isinstance(row, dict):
                module_id = row.get("module_id") or row.get("id")
                action = row.get("action") or row.get("mode")
                if module_id:
                    items.append((module_id, action))
    else:
        items = []
    for module_id, action in items:
        normalized = str(action or "").strip().lower().replace("-", "_")
        if normalized in ("off", "skip", "skipped", "disable", "disabled", "not_in_scope", "none"):
            actions[str(module_id)] = "disabled"
        elif normalized in ("existing", "integrate", "integrate_existing", "use_existing"):
            actions[str(module_id)] = "integrate"
        elif normalized in ("deploy", "deploy_reference", "reference", "install"):
            actions[str(module_id)] = "deploy"
    return actions


def _ordered_modules(profile, include=None, exclude=None):
    manifest = load_manifest()
    profiles = manifest.get("profiles", {})
    selected = list(profiles.get(profile, profiles.get("minimal", {})).get("modules", []))
    for module_id in include or []:
        if module_id not in selected:
            selected.append(module_id)
    excluded = set(exclude or [])
    modules = module_index()

    ordered = []
    seen = set()

    def visit(module_id):
        if module_id in seen or module_id in excluded:
            return
        module = modules.get(module_id)
        if not module:
            return
        disabled_dependencies = []
        for dep_id in module.get("depends_on", []):
            if dep_id in excluded:
                disabled_dependencies.append(dep_id)
            else:
                visit(dep_id)
        seen.add(module_id)
        module = dict(module)
        module["disabled_dependencies"] = disabled_dependencies
        ordered.append(module)

    for module_id in selected:
        visit(module_id)
    return ordered


def build_setup_plan(profile="soc", include=None, exclude=None, existing_tools=None, deploy_missing=True, module_actions=None):
    actions = _normalize_module_actions(module_actions)
    existing = set(existing_tools or [])
    existing.update(module_id for module_id, action in actions.items() if action == "integrate")
    disabled = set(exclude or [])
    disabled.update(module_id for module_id, action in actions.items() if action == "disabled")
    forced_deploy = {module_id for module_id, action in actions.items() if action == "deploy"}
    steps = []
    modules = _ordered_modules(profile, include, disabled)

    for module in modules:
        module_id = module["id"]
        has_existing = module_id in existing
        blocked_dependencies = module.get("disabled_dependencies") or []
        if blocked_dependencies:
            status = "blocked_disabled_dependency"
        elif has_existing:
            status = "integrate_existing"
        elif module_id in forced_deploy and module.get("deployable"):
            status = "deploy"
        elif module.get("status") in ("planned", "blueprint"):
            status = "blueprint"
        elif module.get("deploy_strategy") == "external":
            status = "external_optional"
        else:
            status = "deploy" if deploy_missing and module.get("deployable") else "document"

        steps.append({
            "module_id": module_id,
            "name": module.get("name"),
            "category": module.get("category"),
            "status": status,
            "module_action": actions.get(module_id) or ("integrate" if has_existing else "deploy"),
            "deploy_strategy": module.get("deploy_strategy"),
            "skill": module.get("skill"),
            "skill_available": module.get("skill_available"),
            "depends_on": module.get("depends_on", []),
            "disabled_dependencies": blocked_dependencies,
            "required_secrets": module.get("required_secrets", []),
            "health_checks": module.get("health_checks", []),
            "test_commands": module.get("test_commands", []),
            "notes": module.get("notes", ""),
        })

    return {
        "profile": profile,
        "deploy_missing": deploy_missing,
        "existing_tools": sorted(existing),
        "steps": steps,
        "summary": {
            "total": len(steps),
            "deploy": len([s for s in steps if s["status"] == "deploy"]),
            "integrate_existing": len([s for s in steps if s["status"] == "integrate_existing"]),
            "blueprint": len([s for s in steps if s["status"] == "blueprint"]),
            "external_optional": len([s for s in steps if s["status"] == "external_optional"]),
            "document": len([s for s in steps if s["status"] == "document"]),
            "blocked": len([s for s in steps if s["status"] == "blocked_disabled_dependency"]),
            "disabled": len(disabled),
            "disabled_modules": sorted(disabled),
            "missing_skills": [s["module_id"] for s in steps if s.get("skill") and not s.get("skill_available")],
        },
        "guardrails": [
            "Use raw PostgreSQL through parameterized SQL only.",
            "Store secrets in environment variables or the encrypted server-manager vault, never in source.",
            "Treat ticketing, SIEM, IAM, email, and CI/CD as providers behind platform contracts.",
            "Require approval records before destructive or environment-changing actions.",
            "Run module health checks and smoke tests before marking a deployment complete.",
            "Create a postmortem for meaningful completed tickets and use it to improve skills/workflows.",
        ],
    }


def plan_to_ticket_description(plan, ai_base_url=None, model=None, notes=None, runtime=None):
    runtime = runtime or {}
    lines = [
        "Agentic IT/SOC platform setup plan",
        "",
        f"Profile: {plan.get('profile')}",
        f"Deploy missing modules: {plan.get('deploy_missing')}",
        f"Proxy mode: {runtime.get('proxy_mode') or '<unknown>'}",
        f"Proxy URL: {runtime.get('proxy_url') or ai_base_url or '<configure in environment>'}",
        f"Agent harness: {runtime.get('harness') or '<auto/configured>'}",
        f"Provider route: {runtime.get('provider') or '<auto/configured>'}",
        f"AI endpoint: {ai_base_url or '<configure in environment>'}",
        f"Agent model: {model or '<configure in dashboard>'}",
        "",
        "Agentic onboarding handoff:",
        "- Inspect installed modules and compare source/runtime drift.",
        "- Verify dashboard health, proxy health, harness health, and available models.",
        "- Run a model smoke test and validate agent spawn/checkpoint/note behavior.",
        "- Propose missing integrations and request credential/access approvals as needed.",
        "- Use approval gates before environment-changing actions.",
        "- Update setup notes, postmortem evidence, skills, and reusable workflows.",
        "",
        "Guardrails:",
    ]
    lines.extend([f"- {item}" for item in plan.get("guardrails", [])])
    lines.extend(["", "Module steps:"])
    for idx, step in enumerate(plan.get("steps", []), start=1):
        lines.append(
            f"{idx}. [{step['status']}] {step['name']} ({step['module_id']}) "
            f"via {step.get('deploy_strategy') or 'n/a'}"
        )
        if step.get("skill"):
            lines.append(f"   Skill: {step['skill']} available={step.get('skill_available')}")
        if step.get("required_secrets"):
            lines.append(f"   Required secret inputs: {', '.join(step['required_secrets'])}")
        if step.get("health_checks"):
            lines.append(f"   Health checks: {', '.join(step['health_checks'])}")
        if step.get("disabled_dependencies"):
            lines.append(f"   Blocked by disabled module(s): {', '.join(step['disabled_dependencies'])}")
    disabled = plan.get("summary", {}).get("disabled_modules") or []
    if disabled:
        lines.extend(["", "Disabled / not in scope modules:", ", ".join(disabled)])
    if notes:
        lines.extend(["", "Operator notes:", notes])
    return "\n".join(lines)


def module_ticket_description(parent_ticket_id, step, runtime=None, notes=None):
    runtime = runtime or {}
    lines = [
        f"Scoped setup work item for module `{step.get('module_id')}`.",
        "",
        f"Parent setup ticket: {parent_ticket_id}",
        f"Module: {step.get('name')}",
        f"Category: {step.get('category') or '<unknown>'}",
        f"Action: {step.get('status')}",
        f"Requested mode: {step.get('module_action')}",
        f"Deploy strategy: {step.get('deploy_strategy') or '<none>'}",
        f"Skill: {step.get('skill') or '<none>'} available={step.get('skill_available')}",
        f"Proxy mode: {runtime.get('proxy_mode') or '<unknown>'}",
        f"Proxy URL: {runtime.get('proxy_url') or '<not required>'}",
        f"Agent harness: {runtime.get('harness') or '<auto/configured>'}",
        f"Provider route: {runtime.get('provider') or '<auto/configured>'}",
        "",
        "Scope:",
        "- Work only this module or integration.",
        "- Request credentials or access through approval gates before using them.",
        "- Run listed health checks and smoke tests before marking complete.",
        "- Add human-readable notes and evidence to this ticket.",
    ]
    if step.get("required_secrets"):
        lines.extend(["", "Required secret inputs:"])
        lines.extend([f"- {item}" for item in step.get("required_secrets") or []])
    if step.get("health_checks"):
        lines.extend(["", "Health checks:"])
        lines.extend([f"- {item}" for item in step.get("health_checks") or []])
    if step.get("test_commands"):
        lines.extend(["", "Suggested tests:"])
        lines.extend([f"- {item}" for item in step.get("test_commands") or []])
    if step.get("notes"):
        lines.extend(["", "Module notes:", step.get("notes")])
    if notes:
        lines.extend(["", "Operator notes:", notes])
    return "\n".join(lines)
