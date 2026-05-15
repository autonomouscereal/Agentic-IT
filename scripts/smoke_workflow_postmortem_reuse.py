"""Smoke test workflow reuse through two similar postmortem promotions.

Runs against a deployed dashboard:

    python scripts/smoke_workflow_postmortem_reuse.py http://localhost:25480
"""
import json
import sys
import time
import urllib.request
import urllib.error


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


def create_resolved_ticket(stamp, suffix, ticket_class):
    ticket = request("POST", "/api/tickets", {
        "title": f"Workflow reuse phishing proof {stamp} {suffix}",
        "description": "Reported phishing email with credential harvest URL and approval-gated URL block.",
        "ticket_class": ticket_class,
        "status": "resolved",
        "priority": "3",
        "provider": "local",
        "sync_provider": False,
        "created_by": "workflow-postmortem-reuse-smoke",
    })
    request("POST", f"/api/tickets/{ticket['id']}/notes", {
        "body": "Agent triaged headers, verified credential harvest indicators, requested approval for URL block, and closed with evidence.",
        "author": "workflow-postmortem-reuse-smoke",
        "source": "smoke-test",
        "visibility": "internal",
    })
    return ticket["id"]


def create_approved_postmortem(ticket_id, marker):
    postmortem = request("POST", "/api/postmortems", {
        "ticket_id": ticket_id,
        "status": "approved",
        "summary": f"{marker}: credential phishing was handled with ticket context, URL reputation checks, approval-gated block, and closure evidence.",
        "went_well": "The ticket notes and approval evidence were enough to prove the operational sequence.",
        "improvements": "Reuse the phishing response workflow instead of creating incident-title-specific procedures.",
        "workflow_proposal": (
            "Review reported phishing email context, inspect headers and URL reputation, "
            "request approval before blocking URLs or changing mail controls, verify the approved action, "
            "write final ticket evidence, and run a postmortem."
        ),
        "skill_proposals": [],
        "test_cases": [
            {"name": "similar phishing ticket reuses workflow", "expected": "second promotion updates same workflow id"},
            {"name": "activation remains gated", "expected": "workflow status remains draft or ready_for_review until review"},
        ],
        "guardrails": [
            {"action": "url_block", "approval": "required"},
            {"action": "mailbox_quarantine", "approval": "required"},
        ],
        "documentation": "Workflow reuse is keyed by operational purpose, not postmortem id or ticket title.",
        "created_by": "workflow-postmortem-reuse-smoke",
    })
    return postmortem["id"]


def main():
    stamp = int(time.time())
    ticket_class = f"WorkflowReuseSmoke{stamp}"
    health = request("GET", "/health")
    require(health.get("status") == "ok", "health check failed")

    ticket_a = create_resolved_ticket(stamp, "A", ticket_class)
    pm_a = create_approved_postmortem(ticket_a, "first lesson")
    promote_a = request("POST", f"/api/postmortems/{pm_a}/promote", {
        "create_knowledge": True,
        "create_workflow": True,
        "create_skills": False,
        "workflow_status": "draft",
        "created_by": "workflow-postmortem-reuse-smoke",
        "mark_promoted": True,
    })
    require(promote_a.get("workflow_action") == "created", "first similar postmortem should create workflow")
    require(promote_a.get("workflow_key"), "first promotion missing workflow_key")

    ticket_b = create_resolved_ticket(stamp, "B", ticket_class)
    pm_b = create_approved_postmortem(ticket_b, "second lesson")
    promote_b = request("POST", f"/api/postmortems/{pm_b}/promote", {
        "create_knowledge": True,
        "create_workflow": True,
        "create_skills": False,
        "workflow_status": "draft",
        "created_by": "workflow-postmortem-reuse-smoke",
        "mark_promoted": True,
    })
    require(promote_b.get("workflow_action") == "updated", "second similar postmortem should update workflow")
    require(promote_b.get("workflow_id") == promote_a.get("workflow_id"), "similar postmortems produced different workflow ids")
    require(promote_b.get("workflow_key") == promote_a.get("workflow_key"), "similar postmortems produced different workflow keys")

    workflow = request("GET", f"/api/workflows/{promote_a['workflow_id']}")
    require(workflow.get("workflow_key") == promote_a["workflow_key"], "workflow detail missing canonical key")
    require((workflow.get("version") or 1) >= 2, "workflow version did not increment after reuse update")
    require("second lesson" in (workflow.get("description") or ""), "workflow description missing second postmortem lesson")

    detail_b = request("GET", f"/api/postmortems/{pm_b}")
    assets = detail_b.get("promotion_assets") or {}
    require(assets.get("workflow_key") == promote_b["workflow_key"], "postmortem detail missing workflow key")
    require((assets.get("workflow") or {}).get("id") == promote_a["workflow_id"], "postmortem detail did not resolve workflow by key")

    context_b = request("GET", f"/api/tickets/{ticket_b}/context")
    require(any(w.get("id") == promote_a["workflow_id"] for w in context_b.get("workflows", [])),
            "ticket context did not return updated reusable workflow")

    print(json.dumps({
        "status": "ok",
        "ticket_a": ticket_a,
        "ticket_b": ticket_b,
        "postmortem_a": pm_a,
        "postmortem_b": pm_b,
        "workflow_id": promote_a["workflow_id"],
        "workflow_key": promote_a["workflow_key"],
        "workflow_version": workflow.get("version"),
        "second_action": promote_b.get("workflow_action"),
    }, indent=2))


if __name__ == "__main__":
    main()
