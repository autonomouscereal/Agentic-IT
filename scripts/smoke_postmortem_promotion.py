"""Smoke test postmortem promotion into reusable learning assets.

Runs against a deployed dashboard:

    python scripts/smoke_postmortem_promotion.py http://localhost:25480
"""
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://localhost:25480"


def request(method, path, payload=None):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            body = response.read().decode("utf-8", errors="replace")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed {exc.code}: {body}") from exc


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def as_json(value, default):
    if isinstance(value, (dict, list)):
        return value
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def main():
    stamp = int(time.time())
    health = request("GET", "/health")
    require(health.get("status") == "ok", "health check failed")

    ticket = request("POST", "/api/tickets", {
        "title": f"Postmortem promotion smoke {stamp}",
        "description": "Synthetic completed task with lessons learned ready for reuse.",
        "ticket_class": "Incident",
        "status": "resolved",
        "priority": "3",
        "provider": "local",
        "sync_provider": False,
        "auto_assign": False,
        "created_by": "postmortem-promotion-smoke",
    })
    ticket_id = ticket["id"]

    request("POST", f"/api/tickets/{ticket_id}/notes", {
        "body": "Task completed. Evidence is sufficient to promote reusable knowledge, skills, and a draft workflow.",
        "author": "postmortem-promotion-smoke",
        "source": "smoke-test",
        "visibility": "internal",
    })

    postmortem = request("POST", "/api/postmortems", {
        "ticket_id": ticket_id,
        "status": "approved",
        "summary": "The task was resolved using ticket context, notes, approval-aware remediation, and final verification.",
        "went_well": "The agent had enough context and wrote status notes before each important transition.",
        "improvements": "Package the repeatable steps as a draft workflow and a scoped skill for future incident tickets.",
        "workflow_proposal": (
            "1. Fetch ticket context and related KB.\n"
            "2. Classify indicators and scope impact.\n"
            "3. Request approval for any remediation.\n"
            "4. Execute approved action, verify, and write completion evidence.\n"
            "5. Run postmortem and update reusable assets."
        ),
        "skill_proposals": [
            {
                "name": f"promotion-smoke-context-review-{stamp}",
                "description": "Review ticket context and evidence before proposing remediation.",
                "purpose": "Make repeated incident triage faster while preserving audit notes.",
                "prompt_template": "Fetch ticket context, summarize evidence, write a ticket note, and identify approval-gated actions.",
            },
            {
                "name": f"promotion-smoke-verification-{stamp}",
                "description": "Verify completed remediation and collect proof for closure.",
                "purpose": "Ensure approved remediation has measurable completion evidence.",
            },
        ],
        "test_cases": [
            {"name": "creates reusable assets", "expected": "KB article, draft workflow, and skills exist"},
            {"name": "keeps production gated", "expected": "workflow remains draft until human review"},
        ],
        "guardrails": [
            {"action": "production_change", "approval": "required"},
            {"action": "workflow_activation", "approval": "required"},
        ],
        "documentation": "Promoted assets must keep ticket notes, approval evidence, and test results linked.",
        "created_by": "postmortem-promotion-smoke",
    })
    postmortem_id = postmortem["id"]

    promotion = request("POST", f"/api/postmortems/{postmortem_id}/promote", {
        "create_knowledge": True,
        "create_workflow": True,
        "create_skills": True,
        "workflow_status": "draft",
        "created_by": "postmortem-promotion-smoke",
        "mark_promoted": True,
    })
    require(promotion.get("status") == "promoted", "promotion failed")
    require(promotion.get("knowledge_article_id"), "knowledge article not created")
    require(promotion.get("workflow_id"), "workflow not created")
    require(len(promotion.get("skill_ids") or []) == 2, "skills not created")
    require(promotion.get("knowledge_action") == "created", "first promotion should create knowledge")

    second_promotion = request("POST", f"/api/postmortems/{postmortem_id}/promote", {
        "create_knowledge": True,
        "create_workflow": True,
        "create_skills": True,
        "workflow_status": "draft",
        "created_by": "postmortem-promotion-smoke",
        "mark_promoted": True,
    })
    require(second_promotion.get("knowledge_article_id") == promotion.get("knowledge_article_id"),
            "second promotion duplicated knowledge article")
    require(second_promotion.get("workflow_id") == promotion.get("workflow_id"),
            "second promotion duplicated workflow")
    require(second_promotion.get("skill_ids") == promotion.get("skill_ids"),
            "second promotion duplicated skills")
    require(second_promotion.get("knowledge_action") == "updated", "second promotion should update knowledge")
    require(second_promotion.get("workflow_action") == "updated", "second promotion should update workflow")

    article = request("GET", f"/api/knowledge/{promotion['knowledge_article_id']}")
    require("Postmortem Knowledge" in article.get("body", ""), "article missing postmortem body")

    workflow = request("GET", f"/api/workflows/{promotion['workflow_id']}")
    require(workflow.get("status") == "draft", "workflow should remain draft")
    approval_policy = as_json(workflow.get("approval_policy"), {})
    require(approval_policy.get("requires_human_review_before_activation") is True,
            "workflow missing activation approval policy")

    for skill_id in promotion["skill_ids"]:
        skill = request("GET", f"/api/skills/{skill_id}")
        require(skill.get("category") == "postmortem", f"skill {skill_id} category mismatch")
        require("ticket context" in skill.get("prompt_template", "").lower(), f"skill {skill_id} prompt too thin")

    promoted = request("GET", f"/api/postmortems/{postmortem_id}")
    require(promoted.get("status") == "promoted", "postmortem status not promoted")
    assets = promoted.get("promotion_assets") or {}
    require(any(a.get("id") == promotion["knowledge_article_id"] for a in assets.get("knowledge_articles", [])),
            "postmortem detail missing promoted article asset")
    require((assets.get("workflow") or {}).get("id") == promotion["workflow_id"],
            "postmortem detail missing promoted workflow asset")
    require({s.get("id") for s in assets.get("skills", [])} == set(promotion["skill_ids"]),
            "postmortem detail missing promoted skill assets")

    context = request("GET", f"/api/tickets/{ticket_id}/context")
    require(any(str(postmortem_id) in n.get("body", "") for n in context.get("notes", [])),
            "promotion note missing from ticket context")
    require(not any(
        w.get("id") == promotion["workflow_id"] and w.get("status") == "draft"
        for w in context.get("workflows", [])
    ), "draft workflow should not be presented as operational ticket guidance")

    audit_q = urllib.parse.quote(f"postmortem_{postmortem_id}")
    audit = request("GET", f"/api/dashboard/audit?q={audit_q}")
    audit_items = audit.get("items") or audit.get("events") or audit.get("audit") or []
    require(any(item.get("action") == "postmortem_promoted" for item in audit_items),
            "promotion audit event missing")

    print(json.dumps({
        "status": "ok",
        "ticket_id": ticket_id,
        "postmortem_id": postmortem_id,
        "knowledge_article_id": promotion["knowledge_article_id"],
        "workflow_id": promotion["workflow_id"],
        "skill_ids": promotion["skill_ids"],
        "second_promotion_actions": {
            "knowledge": second_promotion.get("knowledge_action"),
            "workflow": second_promotion.get("workflow_action"),
            "skills": [a.get("action") for a in second_promotion.get("skill_actions", [])],
        },
    }, indent=2))


if __name__ == "__main__":
    main()
