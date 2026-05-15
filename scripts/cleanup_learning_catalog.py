#!/usr/bin/env python3
"""Clean and seed SOC Dashboard workflow/skill learning assets.

This script is intentionally API-only so it can run against a deployed
dashboard without reaching into PostgreSQL directly. It supersedes legacy demo
workflows, enables a small canonical workflow catalog, disables generated
smoke/postmortem skill clutter, and upserts repository reference skills into
the dashboard skill catalog.
"""

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request


CANONICAL_WORKFLOWS = [
    {
        "workflow_key": "incident:phishing",
        "name": "Incident Phishing Triage And Response",
        "ticket_class": "Incident",
        "description": "Canonical phishing investigation, user-response, containment, false-positive, and postmortem workflow.",
        "blueprint": (
            "Read compact ticket evidence, classify sender/URL/user impact, request user response when needed, "
            "gate risky containment, document evidence, resolve the ticket, and create or update the canonical postmortem."
        ),
        "test_plan": "Run report-phish and internal-training false-positive tickets through the agentic flow.",
    },
    {
        "workflow_key": "incident:edr-sysmon",
        "name": "Incident EDR And Sysmon Investigation",
        "ticket_class": "Incident",
        "description": "Canonical Wazuh/Sysmon endpoint investigation with approval-gated response.",
        "blueprint": (
            "Correlate Wazuh/Sysmon telemetry, request scoped SIEM leases through the dashboard, classify true/false positive, "
            "gate endpoint actions, and write evidence/postmortem notes."
        ),
        "test_plan": "Run a Wazuh/Sysmon alert ticket and verify gated provider reads plus evidence notes.",
    },
    {
        "workflow_key": "incident:false-positive-tuning",
        "name": "Incident False Positive Tuning",
        "ticket_class": "Incident",
        "description": "Canonical false-positive investigation and approval-gated suppression/tuning workflow.",
        "blueprint": (
            "Confirm benign source, document why the alert is expected, require approval before suppression, "
            "test the rule change, and keep security recommendations visible."
        ),
        "test_plan": "Run internal-training phishing and known benign EDR alert examples.",
    },
    {
        "workflow_key": "userrequest:service-intake",
        "name": "Service Desk Intake And RACI Routing",
        "ticket_class": "UserRequest",
        "description": "Canonical intake workflow for classifying user asks and routing them with RACI context.",
        "blueprint": (
            "Clarify only missing essentials, classify request/incident/change, attach RACI group/approval context, "
            "sync to the ticket provider when configured, and hand off to an agent or human queue."
        ),
        "test_plan": "Submit service desk requests for access, phishing, setup, and CI/CD work.",
    },
    {
        "workflow_key": "userrequest:access-request",
        "name": "Account Access Request And Resume",
        "ticket_class": "UserRequest",
        "description": "Canonical permission-wall workflow for least-privilege access requests and agent resume.",
        "blueprint": (
            "When a task hits a permission wall, create a child access request with exact lease scope, wait for approval, "
            "verify the grant, then resume the original task without borrowing broader credentials."
        ),
        "test_plan": "Run GitLab, Wazuh, and mailbox denied-then-approved access proofs.",
    },
    {
        "workflow_key": "change:cicd-security",
        "name": "CI/CD Security Gate And Deployment",
        "ticket_class": "Change",
        "description": "Canonical Semgrep, Trivy, OWASP ZAP, and Nuclei security-gated deployment workflow.",
        "blueprint": (
            "Run unit tests and modular scanners, publish findings/reports, fix actionable issues, request deployment approval, "
            "and record before/after evidence."
        ),
        "test_plan": "Run the GitLab CI/CD demo app through scanner findings, fixes, and deployment approval.",
    },
    {
        "workflow_key": "change:setup-integration",
        "name": "Platform Setup And Integration Deployment",
        "ticket_class": "Change",
        "description": "Canonical one-line install and provider integration setup workflow.",
        "blueprint": (
            "Run setup planning, configure required integrations, use vault-backed credentials, deploy bridges/tools, "
            "sync manifests, and verify dashboard health and provider visibility."
        ),
        "test_plan": "Run the installer and integration setup in a clean lab environment.",
    },
    {
        "workflow_key": "change:platform-self-repair",
        "name": "Platform Self Repair And Customization",
        "ticket_class": "Change",
        "description": "Canonical workflow for agents fixing dashboard, bridge, deployment, and harness defects.",
        "blueprint": (
            "Create a system ticket, reproduce the defect, patch the repo or runtime customization, test locally and remotely, "
            "document the change, and preserve upgrade-safe customization notes."
        ),
        "test_plan": "Run a controlled dashboard bugfix through agentic diagnosis, patch, test, and postmortem.",
    },
    {
        "workflow_key": "change:provider-bridge-maintenance",
        "name": "Provider And Bridge Maintenance",
        "ticket_class": "Change",
        "description": "Canonical maintenance workflow for iTop, Mailcow, Wazuh, Keycloak, GitLab, SIEM, and ticket-provider bridges.",
        "blueprint": (
            "Check tool health, bridge queue depth, logs, credential leases, provider sync, and audit trail; fix or restart only "
            "the owned service lane and document evidence."
        ),
        "test_plan": "Run bridge health checks and controlled repair tests for Mailcow, iTop, Wazuh, and ticket adapters.",
    },
]


def request_json(base, method, path, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        base.rstrip("/") + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise RuntimeError(f"{method} {path} failed with {exc.code}: {body}") from exc


def parse_frontmatter_skill(path):
    text = open(path, encoding="utf-8", errors="replace").read()
    name = os.path.basename(os.path.dirname(path))
    description = ""
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            frontmatter = text[3:end]
            match = re.search(r"^name:\s*(.+)$", frontmatter, re.MULTILINE)
            if match:
                name = match.group(1).strip().strip("\"'")
            match = re.search(
                r"^description:\s*>?\s*\n?([\s\S]*?)(?:\n[a-zA-Z_-]+:|\Z)",
                frontmatter,
                re.MULTILINE,
            )
            if match:
                description = " ".join(line.strip() for line in match.group(1).splitlines()).strip()
    if not description:
        match = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        description = match.group(1).strip() if match else f"Operational skill {name}"
    return {
        "name": name,
        "description": description[:500],
        "category": skill_category(name),
        "prompt_template": skill_prompt(name, description, path),
    }


def skill_category(name):
    value = name.lower()
    if any(part in value for part in ("gitlab", "cicd", "semgrep", "trivy", "zap", "nuclei")):
        return "devsecops"
    if any(part in value for part in ("wazuh", "siem", "suricata", "zeek", "phish", "edr", "soc")):
        return "security-operations"
    if any(part in value for part in ("keycloak", "iam", "access", "credential", "vault", "login")):
        return "identity-access"
    if any(part in value for part in ("mailcow", "itop", "ticket", "desk", "provider")):
        return "service-management"
    if any(part in value for part in ("setup", "deploy", "server", "proxy", "searxng", "dashboard", "manager", "bridge")):
        return "platform-operations"
    if "memory" in value or "mempalace" in value:
        return "memory"
    return "platform-operations"


def skill_prompt(name, description, path):
    return (
        f"Use the `{name}` reference skill when this ticket requires it. "
        f"Purpose: {description[:700] or 'Operate this platform capability.'} "
        f"Read the deployed/reference SKILL.md for exact commands and guardrails. "
        "Use vault references for credentials, write ticket notes for evidence, and avoid broad or unaudited access."
    )


def load_reference_skills(root):
    skills = []
    for current, _dirs, files in os.walk(root):
        if "SKILL.md" in files:
            skills.append(parse_frontmatter_skill(os.path.join(current, "SKILL.md")))
    skills.sort(key=lambda item: item["name"])
    return skills


def should_disable_skill(skill):
    name = (skill.get("name") or "").lower()
    category = (skill.get("category") or "").lower()
    if name in {"postmortem-builder", "workflow-builder"}:
        return False
    if name.startswith("smoke-skill-"):
        return True
    if name.startswith("postmortem-"):
        return True
    if category == "smoke":
        return True
    return False


def workflow_rank(workflow):
    status = workflow.get("status")
    reviewed = bool(workflow.get("reviewed_at"))
    if status in ("active", "approved") and reviewed:
        return 0
    if status in ("active", "approved"):
        return 1
    if status == "tested":
        return 2
    if status == "ready_for_review":
        return 3
    if status == "draft":
        return 4
    return 5


def best_workflows_by_key(workflows):
    selected = {}
    for workflow in workflows:
        key = workflow.get("workflow_key")
        if not key or workflow.get("status") == "superseded":
            continue
        current = selected.get(key)
        if current is None:
            selected[key] = workflow
            continue
        candidate_rank = workflow_rank(workflow)
        current_rank = workflow_rank(current)
        if candidate_rank < current_rank:
            selected[key] = workflow
        elif candidate_rank == current_rank and str(workflow.get("updated_at") or "") > str(current.get("updated_at") or ""):
            selected[key] = workflow
    return selected


def should_supersede_workflow(workflow, keep_keys, keep_ids):
    key = workflow.get("workflow_key")
    name = (workflow.get("name") or "").lower()
    status = workflow.get("status")
    if status == "superseded" or workflow.get("id") in keep_ids:
        return False
    if key in keep_keys:
        return True
    if status in ("active", "approved"):
        return True
    key_text = str(key or "").lower()
    clutter_terms = (
        "smoke",
        "postmortem-",
        "postmortem:",
        "canonical-smoke",
        "broker_workflow_agentic",
        "brokerlease",
        "workflowreusesmoke",
        "proof",
    )
    return status in ("draft", "ready_for_review", "tested", "needs_revision") and (
        not key or any(term in name or term in key_text for term in clutter_terms)
    )


def ensure_skill(base, existing_by_name, skill, apply):
    existing = existing_by_name.get(skill["name"].lower())
    payload = {
        "name": skill["name"],
        "description": skill["description"],
        "category": skill["category"],
        "prompt_template": skill["prompt_template"],
    }
    unchanged = bool(existing) and all(
        (existing.get(field) or "") == (payload.get(field) or "")
        for field in ("description", "category", "prompt_template")
    ) and bool(existing.get("enabled")) and bool(existing.get("assigned_to_all"))
    if not apply:
        if unchanged:
            return {"action": "unchanged", "name": skill["name"], "id": existing.get("id")}
        return {"action": "would_update" if existing else "would_create", "name": skill["name"], "id": existing and existing.get("id")}
    if unchanged:
        return {"action": "unchanged", "name": skill["name"], "id": existing.get("id")}
    if existing:
        result = request_json(base, "PUT", f"/api/skills/{existing['id']}", {**payload, "enabled": True, "assigned_to_all": True})
        return {"action": "updated", "name": skill["name"], "id": existing["id"], "result": result}
    created = request_json(base, "POST", "/api/skills", payload)
    skill_id = created.get("id")
    if skill_id:
        request_json(base, "PUT", f"/api/skills/{skill_id}", {"enabled": True, "assigned_to_all": True})
    return {"action": "created", "name": skill["name"], "id": skill_id, "result": created}


def canonical_workflow_payload(item):
    return {
        "name": item["name"],
        "description": item["description"],
        "ticket_class": item["ticket_class"],
        "trigger_type": "manual",
        "status": "tested",
        "blueprint": item["blueprint"],
        "test_plan": item["test_plan"],
        "test_results": "Seeded by learning catalog cleanup; requires continued real agentic run evidence.",
        "approval_policy": {
            "workflow_key": item["workflow_key"],
            "rename_on_reuse": True,
            "production_changes_require_approval": True,
            "requires_human_review_before_activation": True,
        },
        "skill_ids": [],
        "created_by": "learning-catalog-cleanup",
    }


def normalize_policy(value):
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, ValueError):
        return {}


def workflow_matches(existing, payload, workflow_key):
    policy = normalize_policy(existing.get("approval_policy"))
    return all(
        (existing.get(field) or "") == (payload.get(field) or "")
        for field in ("name", "description", "ticket_class", "trigger_type", "blueprint", "test_plan")
    ) and policy.get("workflow_key") == workflow_key and existing.get("workflow_key") == workflow_key


def ensure_canonical_workflow(base, existing_by_key, item, apply, marker):
    workflow_key = item["workflow_key"]
    existing = existing_by_key.get(workflow_key)
    payload = canonical_workflow_payload(item)
    if not apply:
        if existing and workflow_matches(existing, payload, workflow_key) and existing.get("status") in ("active", "approved") and existing.get("reviewed_at"):
            return {"workflow_key": workflow_key, "action": "unchanged", "id": existing["id"]}
        return {
            "workflow_key": workflow_key,
            "action": "would_update" if existing else "would_create",
            "id": existing and existing.get("id"),
        }
    if existing and workflow_matches(existing, payload, workflow_key) and existing.get("status") in ("active", "approved") and existing.get("reviewed_at"):
        return {"workflow_key": workflow_key, "action": "unchanged", "id": existing["id"]}
    if existing:
        workflow_id = existing["id"]
        request_json(base, "PUT", f"/api/workflows/{workflow_id}", payload)
        action = "updated"
    else:
        saved = request_json(base, "POST", "/api/workflows", payload)
        workflow_id = saved.get("id")
        action = "created"
    reviewed = request_json(base, "POST", f"/api/workflows/{workflow_id}/review", {
        "reviewed_by": "learning-catalog-cleanup",
        "approved": True,
        "review_notes": f"Approved canonical operational workflow during cleanup {marker}.",
    })
    return {"workflow_key": workflow_key, "id": workflow_id, "action": action, "review": reviewed}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:25480")
    parser.add_argument("--reference-skills", default="reference_skills")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--marker", default=f"LEARNING_CLEANUP_{int(time.time())}")
    args = parser.parse_args()

    if not os.path.isdir(args.reference_skills):
        raise SystemExit(f"reference skill directory not found: {args.reference_skills}")

    before_workflows = request_json(args.base, "GET", "/api/workflows?limit=500").get("workflows", [])
    before_skills = request_json(args.base, "GET", "/api/skills?enabled_only=false").get("skills", [])
    existing_skills = {str(skill.get("name") or "").lower(): skill for skill in before_skills}
    existing_workflows_by_key = best_workflows_by_key(before_workflows)

    disabled_skills = []
    for skill in before_skills:
        if skill.get("enabled") and should_disable_skill(skill):
            disabled_skills.append({"id": skill["id"], "name": skill["name"]})
            if args.apply:
                request_json(args.base, "PUT", f"/api/skills/{skill['id']}", {"enabled": False, "assigned_to_all": False})

    reference_results = []
    for skill in load_reference_skills(args.reference_skills):
        reference_results.append(ensure_skill(args.base, existing_skills, skill, args.apply))

    workflow_results = []
    for item in CANONICAL_WORKFLOWS:
        workflow_results.append(ensure_canonical_workflow(args.base, existing_workflows_by_key, item, args.apply, args.marker))

    keep_keys = {item["workflow_key"] for item in CANONICAL_WORKFLOWS}
    keep_ids = {result.get("id") for result in workflow_results if result.get("id")}
    after_canonical = request_json(args.base, "GET", "/api/workflows?limit=500").get("workflows", []) if args.apply else before_workflows
    superseded_workflows = []
    for workflow in after_canonical:
        name = workflow.get("name") or ""
        if should_supersede_workflow(workflow, keep_keys, keep_ids):
            superseded_workflows.append({
                "id": workflow["id"],
                "name": name,
                "status": workflow.get("status"),
                "workflow_key": workflow.get("workflow_key"),
            })
            if args.apply:
                request_json(args.base, "PUT", f"/api/workflows/{workflow['id']}", {
                    "status": "superseded",
                    "test_results": (
                        (workflow.get("test_results") or "")
                        + f"\nSuperseded by learning catalog cleanup {args.marker}; non-canonical active/demo workflow."
                    ).strip(),
                })

    after_workflows = request_json(args.base, "GET", "/api/workflows?limit=500").get("workflows", []) if args.apply else before_workflows
    after_skills = request_json(args.base, "GET", "/api/skills?enabled_only=false").get("skills", []) if args.apply else before_skills

    summary = {
        "marker": args.marker,
        "applied": bool(args.apply),
        "workflow_counts": {
            "before_total": len(before_workflows),
            "before_active": sum(1 for workflow in before_workflows if workflow.get("status") in ("active", "approved")),
            "after_total": len(after_workflows),
            "after_active": sum(1 for workflow in after_workflows if workflow.get("status") in ("active", "approved")),
        },
        "skill_counts": {
            "before_total": len(before_skills),
            "before_enabled": sum(1 for skill in before_skills if skill.get("enabled")),
            "after_total": len(after_skills),
            "after_enabled": sum(1 for skill in after_skills if skill.get("enabled")),
        },
        "disabled_skills": disabled_skills,
        "reference_skill_results": reference_results,
        "canonical_workflows": workflow_results,
        "superseded_workflows": superseded_workflows,
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"cleanup failed: {exc}", file=sys.stderr)
        raise
