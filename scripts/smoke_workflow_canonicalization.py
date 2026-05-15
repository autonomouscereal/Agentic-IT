"""Smoke canonical workflow key behavior.

Runs against a deployed dashboard:

    python scripts/smoke_workflow_canonicalization.py http://localhost:25480
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


def create_ticket(title, description, stamp):
    ticket = request("POST", "/api/tickets", {
        "title": title,
        "description": description,
        "ticket_class": "Incident",
        "status": "resolved",
        "priority": "3",
        "auto_assign": False,
        "created_by": "workflow-canonicalization-smoke",
    })
    request("POST", f"/api/tickets/{ticket['id']}/notes", {
        "body": f"Workflow canonicalization evidence {stamp}: resolved with reusable steps.",
        "author": "workflow-canonicalization-smoke",
        "source": "smoke-test",
        "visibility": "internal",
    })
    return ticket["id"]


def promote_postmortem(ticket_id, stamp, suffix):
    postmortem = request("POST", "/api/postmortems", {
        "ticket_id": ticket_id,
        "status": "approved",
        "summary": f"Phishing flow resolved and reusable workflow should be refined, not duplicated. {suffix}",
        "went_well": "The ticket used existing phishing triage context and approval-gated remediation.",
        "improvements": "Add internal training false-positive handling to the canonical phishing workflow.",
        "workflow_proposal": (
            "1. Confirm the sender, URL, and user impact.\n"
            "2. Compare against approved internal training and known false-positive sources.\n"
            "3. Gate containment changes behind approval.\n"
            "4. Resolve with notes and update the canonical workflow."
        ),
        "test_cases": [
            {"name": "canonical phishing reuse", "expected": "promotion updates one draft workflow for incident:phishing"},
        ],
        "guardrails": [
            {"action": "email containment", "approval": "required"},
        ],
        "documentation": "Do not create a second phishing article for internal training false positives.",
        "created_by": "workflow-canonicalization-smoke",
    })
    promotion = request("POST", f"/api/postmortems/{postmortem['id']}/promote", {
        "create_knowledge": True,
        "create_workflow": True,
        "create_skills": False,
        "workflow_status": "draft",
        "created_by": "workflow-canonicalization-smoke",
        "mark_promoted": True,
    })
    return postmortem["id"], promotion


def main():
    stamp = int(time.time())
    active_key = f"incident:canonical-smoke-{stamp}"
    health = request("GET", "/health")
    require(health.get("status") == "ok", "health check failed")

    first_workflow = request("POST", "/api/workflows", {
        "name": f"Canonical smoke workflow A {stamp}",
        "description": "First reviewed workflow for canonical one-active enforcement.",
        "ticket_class": "Incident",
        "trigger_type": "manual",
        "status": "active",
        "approval_policy": {"workflow_key": active_key},
        "blueprint": "Initial reviewed workflow.",
        "test_plan": "Create a second workflow with the same key.",
        "test_results": "Synthetic enforcement setup.",
        "created_by": "workflow-canonicalization-smoke",
    })
    first_created = request("GET", f"/api/workflows/{first_workflow['id']}")
    require(first_created.get("status") == "ready_for_review",
            "create path did not gate active request behind review")
    review_first = request("POST", f"/api/workflows/{first_workflow['id']}/review", {
        "reviewed_by": "workflow-canonicalization-smoke",
        "approved": True,
        "review_notes": "Initial activation for one-active enforcement.",
    })
    require(review_first.get("status") == "active", "first review did not activate workflow")
    second_workflow = request("POST", "/api/workflows", {
        "name": f"Canonical smoke workflow B {stamp}",
        "description": "Second reviewed workflow should supersede the first after approval.",
        "ticket_class": "Incident",
        "trigger_type": "manual",
        "status": "active",
        "approval_policy": {"workflow_key": f"incident:canonical-smoke-replacement-{stamp}"},
        "blueprint": "Replacement reviewed workflow.",
        "test_plan": "Verify the first workflow is no longer active.",
        "test_results": "Synthetic enforcement replacement.",
        "created_by": "workflow-canonicalization-smoke",
    })
    require(second_workflow["id"] != first_workflow["id"],
            "smoke setup should create a sibling workflow before review")
    request("PUT", f"/api/workflows/{second_workflow['id']}", {
        "approval_policy": {"workflow_key": active_key},
        "status": "ready_for_review",
    })
    review_second = request("POST", f"/api/workflows/{second_workflow['id']}/review", {
        "reviewed_by": "workflow-canonicalization-smoke",
        "approved": True,
        "review_notes": "Activating replacement workflow should demote active siblings.",
    })
    require(first_workflow["id"] in review_second.get("superseded_workflow_ids", []),
            "second review did not report superseding the first workflow")
    first_detail = request("GET", f"/api/workflows/{first_workflow['id']}")
    second_detail = request("GET", f"/api/workflows/{second_workflow['id']}")
    require(first_detail.get("status") == "superseded", "first same-key active workflow was not superseded")
    require(second_detail.get("status") == "active", "second same-key workflow is not active")

    review = request("POST", f"/api/workflows/{first_workflow['id']}/review", {
        "reviewed_by": "workflow-canonicalization-smoke",
        "approved": True,
        "review_notes": "Re-activating first workflow should demote the second workflow for the same key.",
    })
    require(review.get("status") == "active", "review did not activate workflow")
    first_detail = request("GET", f"/api/workflows/{first_workflow['id']}")
    second_detail = request("GET", f"/api/workflows/{second_workflow['id']}")
    require(first_detail.get("status") == "active", "reviewed first workflow is not active")
    require(second_detail.get("status") == "superseded", "review did not supersede sibling workflow")

    ticket_a = create_ticket(
        f"Phishing report internal training URL canonical A {stamp}",
        "Reported phishing message is likely an internal training false positive.",
        stamp,
    )
    ticket_b = create_ticket(
        f"Phishing report internal training URL canonical B {stamp}",
        "Second phishing postmortem should refine the same canonical workflow and article.",
        stamp,
    )
    postmortem_a, promotion_a = promote_postmortem(ticket_a, stamp, "first")
    postmortem_b, promotion_b = promote_postmortem(ticket_b, stamp, "second")
    require(promotion_a.get("workflow_key") == "incident:phishing", "first promotion did not use phishing key")
    require(promotion_b.get("workflow_key") == "incident:phishing", "second promotion did not use phishing key")
    require(promotion_a.get("workflow_id") == promotion_b.get("workflow_id"),
            "phishing postmortems created duplicate workflow drafts")
    require(promotion_a.get("knowledge_article_id") == promotion_b.get("knowledge_article_id"),
            "phishing postmortems created duplicate knowledge articles")

    context = request("GET", f"/api/tickets/{ticket_b}/context")
    matching = [w for w in context.get("workflows", []) if w.get("workflow_key") == "incident:phishing"]
    require(len(matching) == 1, "ticket context returned multiple phishing workflows")
    require(matching[0].get("status") == "active", "ticket context did not prefer the active phishing workflow")

    workflow_q = urllib.parse.quote("incident:phishing")
    audit = request("GET", f"/api/dashboard/audit?q={workflow_q}")
    audit_items = audit.get("items") or audit.get("events") or audit.get("audit") or []
    require(any(item.get("action") in ("postmortem_promoted", "workflow_siblings_superseded") for item in audit_items),
            "canonical workflow audit evidence missing")

    print(json.dumps({
        "status": "ok",
        "active_enforcement": {
            "reactivated_workflow_id": first_workflow["id"],
            "superseded_workflow_id": second_workflow["id"],
        },
        "phishing_refinement": {
            "ticket_ids": [ticket_a, ticket_b],
            "postmortem_ids": [postmortem_a, postmortem_b],
            "workflow_id": promotion_a["workflow_id"],
            "knowledge_article_id": promotion_a["knowledge_article_id"],
            "workflow_key": promotion_a["workflow_key"],
            "context_workflow_id": matching[0]["id"],
        },
    }, indent=2))


if __name__ == "__main__":
    main()
