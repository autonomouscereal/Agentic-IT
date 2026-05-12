"""Smoke test the provider-agnostic agentic SOC API.

Uses only Python stdlib HTTP calls. Intended to run against a deployed dashboard:

    python scripts/smoke_agentic_system.py http://localhost:25480
"""
import json
import sys
import time
import urllib.error
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
        with urllib.request.urlopen(req, timeout=20) as response:
            body = response.read().decode("utf-8", errors="replace")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed {exc.code}: {body}") from exc


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    health = request("GET", "/health")
    require(health.get("status") == "ok", "health check failed")

    providers = request("GET", "/api/providers")
    provider_names = {p["name"] for p in providers.get("providers", [])}
    require("local" in provider_names and "itop" in provider_names, "providers missing")

    ticket = request("POST", "/api/tickets", {
        "title": f"Smoke phishing investigation {int(time.time())}",
        "description": "Synthetic phishing email for end-to-end API smoke.",
        "ticket_class": "Incident",
        "status": "new",
        "priority": "2",
        "provider": "local",
        "sync_provider": False,
        "created_by": "smoke-test",
    })
    ticket_id = ticket["id"]
    require(ticket.get("provider") == "local", "ticket provider not local")

    mirrored_local = request("POST", "/api/tickets", {
        "title": f"Smoke local provider mirror {int(time.time())}",
        "description": "Exercises sync_provider through the local provider adapter.",
        "ticket_class": "UserRequest",
        "status": "new",
        "provider": "local",
        "sync_provider": True,
        "created_by": "smoke-test",
    })
    require(mirrored_local.get("provider_sync_status") == "local_only", "local provider create did not settle local_only")
    pushed_local = request("POST", f"/api/tickets/{mirrored_local['id']}/push-provider", {"provider": "local"})
    require(pushed_local.get("status") == "local_only", "local provider push failed")

    note = request("POST", f"/api/tickets/{ticket_id}/notes", {
        "body": "Observed sender, recipients, URL, and remediation plan. No destructive action taken.",
        "author": "smoke-test",
        "source": "smoke-test",
        "visibility": "internal",
    })
    require(note.get("status") == "created", "note create failed")

    attachment = request("POST", f"/api/tickets/{ticket_id}/attachments", {
        "filename": "phishing.eml",
        "content_type": "message/rfc822",
        "storage_ref": "memory://smoke/phishing.eml",
        "sha256": "0" * 64,
        "size_bytes": 128,
        "metadata": {"synthetic": True},
    })
    require(attachment.get("status") == "created", "attachment metadata failed")

    article = request("POST", "/api/knowledge", {
        "title": "Smoke phishing triage article",
        "body": "Extract URLs, inspect headers, scope recipients, and request approval before remediation.",
        "category": "Incident",
        "source": "smoke-test",
        "tags": ["phishing", "smoke"],
    })
    require(article.get("status") == "created", "knowledge create failed")

    skill = request("POST", "/api/skills", {
        "name": f"smoke-skill-{int(time.time())}",
        "description": "Smoke test skill",
        "category": "smoke",
        "prompt_template": "Use dashboard API context before acting.",
    })
    require(skill.get("id"), "skill create failed")

    change = request("POST", "/api/changes/request", {
        "agent_id": None,
        "ticket_id": ticket_id,
        "action": "block_url",
        "target": "https://example.invalid/phish",
        "reason": "Synthetic approval-gate test",
        "command": "no-op",
        "risk_level": "medium",
        "approval_policy": {"requires_human": True},
    })
    change_id = change["change_id"]
    status = request("GET", f"/api/changes/{change_id}/status")
    require(status.get("status") == "pending", "change not pending")
    approved = request("POST", f"/api/changes/{change_id}/approve", {"approved_by": "smoke-test"})
    require(approved.get("status") == "approved", "change approve failed")

    postmortem = request("POST", "/api/postmortems", {
        "ticket_id": ticket_id,
        "status": "ready_for_review",
        "summary": "Smoke postmortem summary",
        "went_well": "Context, notes, attachments, and approval gate all worked.",
        "improvements": "Use a real harness run for model behavior validation.",
        "workflow_proposal": "Create a reusable phishing triage workflow.",
        "skill_proposals": [{"name": "phishing-scope"}],
        "test_cases": [{"name": "approval required before block"}],
        "guardrails": [{"action": "block_url", "approval": "required"}],
        "documentation": "Smoke documentation entry.",
        "created_by": "smoke-test",
    })
    require(postmortem.get("status") == "created", "postmortem create failed")

    workflow = request("POST", "/api/workflows", {
        "name": f"Smoke phishing workflow {ticket_id}",
        "description": "Synthetic phishing workflow",
        "ticket_class": "Incident",
        "trigger_type": "manual",
        "status": "tested",
        "blueprint": "Read context, scope recipients, request approval, document remediation.",
        "test_plan": "Positive: note/context. Negative: blocked action without approval.",
        "test_results": "Smoke API passed.",
        "approval_policy": {"destructive_actions_require_approval": True},
        "skill_ids": [skill["id"]],
        "created_by": "smoke-test",
    })
    require(workflow.get("status") == "saved", "workflow save failed")
    review = request("POST", f"/api/workflows/{workflow['id']}/review", {
        "reviewed_by": "smoke-test",
        "approved": True,
        "review_notes": "Approved by smoke test.",
    })
    require(review.get("status") in ("approved", "active"), "workflow review failed")

    context = request("GET", f"/api/tickets/{ticket_id}/context")
    require(context.get("ticket", {}).get("id") == ticket_id, "context ticket mismatch")
    require(len(context.get("notes", [])) >= 1, "context missing notes")
    require(len(context.get("attachments", [])) >= 1, "context missing attachments")
    require(len(context.get("change_requests", [])) >= 1, "context missing changes")
    require(len(context.get("postmortems", [])) >= 1, "context missing postmortems")
    require(len(context.get("workflows", [])) >= 1, "context missing workflows")
    require(len(context.get("skills", [])) >= 1, "context missing global skills")

    processes = request("GET", "/api/agents/processes")
    require(processes.get("ps_path"), "process diagnostics missing ps")

    print(json.dumps({
        "status": "ok",
        "ticket_id": ticket_id,
        "local_push_ticket_id": mirrored_local["id"],
        "change_id": change_id,
        "postmortem_id": postmortem["id"],
        "workflow_id": workflow["id"],
        "workflow_status": review.get("status"),
        "skill_id": skill["id"],
    }, indent=2))


if __name__ == "__main__":
    main()
