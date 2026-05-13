#!/usr/bin/env python3
"""Exercise false-positive classification and suppression workflow objects."""

import json
import sys
import time
import urllib.error
import urllib.request


def request(method, base, path, body=None):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base.rstrip("/") + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"{method} {path} failed HTTP {exc.code}: {raw}") from exc


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:25480"
    marker = f"CODEX_FALSE_POSITIVE_SUPPRESSION_{int(time.time())}"
    title = f"{marker}: internal phishing-training URL false positive"
    description = (
        "Wazuh/mail phishing alert flagged https://training.example.internal/login. "
        "Investigation proved the sender, URL, TLS endpoint, and landing page belong to the internal "
        "awareness platform. This must be classified as a false positive and only a precise suppression "
        "proposal may be made."
    )

    ticket = request("POST", base, "/api/tickets", {
        "title": title,
        "description": description,
        "provider": "local",
        "sync_provider": False,
        "priority": "P2",
        "ticket_class": "Incident",
        "created_by": "false-positive-smoke",
        "auto_assign": False,
    })
    ticket_id = ticket["id"]

    request("POST", base, f"/api/tickets/{ticket_id}/notes", {
        "title": "False positive classification",
        "content": (
            "Classification: false positive after investigation.\n"
            "Evidence: source domain training.example.internal is owned by the internal awareness platform; "
            "message headers match internal mail; URL resolves to the approved training service; no credential "
            "exfiltration, suspicious redirect, or external network indicator was observed.\n"
            "Suppression scope: exact rule 100601 plus exact URL/domain phrase only; do not suppress all phishing alerts."
        ),
        "author": "false-positive-smoke",
        "source": "test",
    })

    change = request("POST", base, "/api/changes/request", {
        "agent_id": None,
        "ticket_id": ticket_id,
        "action": "Add precise false-positive suppression proposal",
        "target": "siem-ticket-bridge suppression_rules.json",
        "reason": (
            "Approved internal training portal repeatedly triggers the phishing rule. Proposed match requires "
            "rule_id=100601 and both 'training.example.internal' and 'internal training portal'. Expiry review "
            "date is required; malicious lookalike domains must still alert."
        ),
        "risk_level": "medium",
        "approval_policy": {"auto_complete": False, "requires_test_evidence": True},
    })
    change_id = change["change_id"]

    request("POST", base, f"/api/changes/{change_id}/approve", {
        "approved_by": "smoke-approver",
        "reason": "Lab approval for precise false-positive suppression test.",
    })
    request("POST", base, f"/api/changes/{change_id}/complete", {
        "completed_by": "false-positive-smoke",
        "result": (
            "Tested suppression criteria against a benign internal portal sample and a malicious lookalike sample. "
            "Benign exact match would suppress; lookalike external domain and missing internal-training phrase would still alert. "
            "No blanket rule or source suppression was applied."
        ),
    })

    postmortem = request("POST", base, "/api/postmortems", {
        "ticket_id": ticket_id,
        "status": "ready_for_review",
        "summary": "False-positive phishing alert was correctly classified with evidence and routed to approval-gated rule tuning.",
        "went_well": "The workflow preserved the alert, captured evidence, and used a precise suppression proposal.",
        "improvements": "Bridge suppression rules should remain disabled unless approved_by, reason, exact match terms, and expiry are present.",
        "workflow_proposal": "For repeat false positives, validate ownership and telemetry, write a classification note, propose exact scoped suppression through change approval, test benign and malicious variants, then review expiry.",
        "skill_proposals": [{
            "name": "false-positive-alert-tuning",
            "description": "Investigate repeat false positives and propose narrow, approval-gated SIEM suppression rules with tests."
        }],
        "test_cases": [
            "Benign internal training URL with exact approved terms is suppressed.",
            "External lookalike domain still creates an alert/ticket.",
            "Rule without approved_by/reason/expiry is ignored."
        ],
        "guardrails": [
            "Never blanket suppress phishing or EDR rules.",
            "Require approval gate and rollback before deployment.",
            "Require malicious-variant regression test evidence."
        ],
        "documentation": "Operator demo can show ticket note, change approval, completion evidence, postmortem, promoted workflow, and workflow run.",
        "created_by": "false-positive-smoke",
    })
    postmortem_id = postmortem["id"]
    request("POST", base, f"/api/postmortems/{postmortem_id}/review", {
        "reviewed_by": "smoke-reviewer",
        "approved": True,
        "review_notes": "Deterministic smoke proof accepted.",
    })
    promoted = request("POST", base, f"/api/postmortems/{postmortem_id}/promote", {
        "create_knowledge": True,
        "create_workflow": True,
        "create_skills": True,
        "workflow_status": "tested",
        "created_by": "false-positive-smoke",
    })
    workflow_id = promoted.get("workflow_id")
    if workflow_id:
        request("POST", base, f"/api/workflows/{workflow_id}/review", {
            "reviewed_by": "smoke-reviewer",
            "approved": True,
            "review_notes": "Workflow has deterministic smoke evidence and approval-gate coverage.",
        })
        run = request("POST", base, f"/api/workflows/{workflow_id}/runs", {
            "ticket_id": ticket_id,
            "status": "running",
        })
        request("POST", base, f"/api/workflows/runs/{run['id']}/complete", {
            "status": "completed",
            "result": f"{marker} workflow run completed with false-positive classification and precise suppression guardrails.",
        })

    print(
        "PASS "
        f"marker={marker} ticket_id={ticket_id} change_id={change_id} "
        f"postmortem_id={postmortem_id} workflow_id={workflow_id}"
    )


if __name__ == "__main__":
    main()
