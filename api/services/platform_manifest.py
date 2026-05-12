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
        for dep_id in module.get("depends_on", []):
            visit(dep_id)
        seen.add(module_id)
        ordered.append(module)

    for module_id in selected:
        visit(module_id)
    return ordered


def build_setup_plan(profile="soc", include=None, exclude=None, existing_tools=None, deploy_missing=True):
    existing = set(existing_tools or [])
    steps = []
    modules = _ordered_modules(profile, include, exclude)

    for module in modules:
        module_id = module["id"]
        has_existing = module_id in existing
        status = "integrate_existing" if has_existing else ("deploy" if deploy_missing and module.get("deployable") else "document")
        if module.get("status") in ("planned", "blueprint") and not has_existing:
            status = "blueprint"
        if module.get("deploy_strategy") == "external" and not has_existing:
            status = "external_optional"

        steps.append({
            "module_id": module_id,
            "name": module.get("name"),
            "category": module.get("category"),
            "status": status,
            "deploy_strategy": module.get("deploy_strategy"),
            "skill": module.get("skill"),
            "skill_available": module.get("skill_available"),
            "depends_on": module.get("depends_on", []),
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


def plan_to_ticket_description(plan, ai_base_url=None, model=None, notes=None):
    lines = [
        "Agentic IT/SOC platform setup plan",
        "",
        f"Profile: {plan.get('profile')}",
        f"Deploy missing modules: {plan.get('deploy_missing')}",
        f"AI endpoint: {ai_base_url or '<configure in environment>'}",
        f"Agent model: {model or '<configure in dashboard>'}",
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
    if notes:
        lines.extend(["", "Operator notes:", notes])
    return "\n".join(lines)
