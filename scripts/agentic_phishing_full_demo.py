#!/usr/bin/env python3
"""Run a full local-model report-phish incident workflow.

This is intentionally heavier than a smoke test. It creates a realistic
report-phish ticket, attaches parsed email evidence, spawns the local model,
auto-approves lab remediation gates so the approval chain is visible, verifies
that the agent completed the gates, and starts a postmortem/promotion pass.

All destructive-looking actions are lab no-ops recorded as approval-gated
evidence: URL block, message quarantine, training follow-up, password reset,
and endpoint scan.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import textwrap
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dashboard_auth import dashboard_auth_headers


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE = os.getenv("SOC_DASHBOARD_URL", "http://localhost:25480").rstrip("/")
DEFAULT_MODEL = os.getenv("AGENT_MODEL", "deepseek/deepseek-v4-flash")


def request(method: str, base: str, path: str, payload=None, timeout: int = 60):
    data = None
    headers = dashboard_auth_headers(
        provider="phishing-full-proof",
        content_type=payload is not None,
    )
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed {exc.code}: {body}") from exc


def add_note(base: str, ticket_id: int, body: str, author: str = "report-phish-demo", source: str = "report-phish"):
    return request("POST", base, f"/api/tickets/{ticket_id}/notes", {
        "body": body,
        "author": author,
        "source": source,
        "visibility": "internal",
    })


def add_attachment(base: str, ticket_id: int, filename: str, content: str, metadata: dict):
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return request("POST", base, f"/api/tickets/{ticket_id}/attachments", {
        "filename": filename,
        "content_type": "message/rfc822" if filename.endswith(".eml") else "application/json",
        "storage_ref": f"demo://report-phish/{digest}/{filename}",
        "sha256": digest,
        "size_bytes": len(content.encode("utf-8")),
        "metadata": metadata,
    })


def phishing_fixture(run_id: int) -> dict:
    malicious_url = "https://login-update.example.invalid/session?id=RPT-4421"
    tracking_url = "http://cdn-example.invalid/invoice/view"
    recipients = [
        {"email": "alice.analyst@example.invalid", "clicked": True, "entered_credentials": True, "host": "WIN-ALICE-01"},
        {"email": "bob.builder@example.invalid", "clicked": True, "entered_credentials": False, "host": "WIN-BOB-02"},
        {"email": "carol.controller@example.invalid", "clicked": False, "entered_credentials": False, "host": "WIN-CAROL-03"},
        {"email": "dan.desk@example.invalid", "clicked": False, "entered_credentials": False, "host": "WIN-DAN-04"},
    ]
    message_id = f"<codex-report-phish-{run_id}@example.invalid>"
    headers = textwrap.dedent(f"""
    Return-Path: <billing-support@evil-example.invalid>
    Received: from badhost.evil-example.invalid (badhost.evil-example.invalid [198.51.100.77])
        by mail.example.invalid with ESMTPS id CODX{run_id}
        for <security-team@example.invalid>;
        Tue, 12 May 2026 15:40:00 +0000
    Authentication-Results: example.invalid;
        dkim=neutral (no signature) header.d=evil-example.invalid;
        spf=fail smtp.mailfrom=evil-example.invalid;
        dmarc=fail header.from=evil-example.invalid
    From: "Payroll Support" <billing-support@evil-example.invalid>
    To: alice.analyst@example.invalid, bob.builder@example.invalid, carol.controller@example.invalid, dan.desk@example.invalid
    Subject: Immediate payroll portal verification required
    Date: Tue, 12 May 2026 15:40:00 +0000
    Message-ID: {message_id}
    """).strip()
    body = textwrap.dedent(f"""
    Payroll portal verification is required before close of business.

    Verify your account here: {malicious_url}
    Secondary invoice portal: {tracking_url}
    """).strip()
    eml = headers + "\n\n" + body + "\n"
    return {
        "run_id": run_id,
        "message_id": message_id,
        "headers": headers,
        "body": body,
        "eml": eml,
        "sender": "billing-support@evil-example.invalid",
        "source_ip": "198.51.100.77",
        "urls": [malicious_url, tracking_url],
        "recipients": recipients,
        "clicked": [r["email"] for r in recipients if r["clicked"]],
        "credentialed": [r["email"] for r in recipients if r["entered_credentials"]],
        "hosts": [r["host"] for r in recipients if r["clicked"] or r["entered_credentials"]],
    }


def create_ticket(base: str, fixture: dict) -> int:
    recipients = ", ".join(item["email"] for item in fixture["recipients"])
    description = textwrap.dedent(f"""
    Report-phish workflow intake.

    Source: Mailcow report-phish internal email backend
    Message-ID: {fixture['message_id']}
    Sender: {fixture['sender']}
    Source IP: {fixture['source_ip']}
    Authentication: SPF fail, DKIM neutral, DMARC fail
    URLs: {", ".join(fixture['urls'])}
    Recipients: {recipients}

    Lab telemetry for full-flow validation:
    - Clicked links: {", ".join(fixture['clicked'])}
    - Entered credentials: {", ".join(fixture['credentialed'])}
    - Candidate endpoint scans: {", ".join(fixture['hosts'])}

    Work this ticket end to end. Scope recipients and URLs, request approval
    gates before remediation, then complete approved lab actions with evidence.
    """).strip()
    ticket = request("POST", base, "/api/tickets", {
        "title": f"Report phish full-flow demo {fixture['run_id']}",
        "description": description,
        "ticket_class": "Incident",
        "status": "new",
        "priority": "P1",
        "provider": "local",
        "sync_provider": False,
        "created_by": "report-phish-demo",
    })
    ticket_id = ticket["id"]
    add_note(base, ticket_id, textwrap.dedent(f"""
    Report-phish intake received the suspicious email and created this incident.
    Sender `{fixture['sender']}` failed SPF/DMARC checks from `{fixture['source_ip']}`.
    The reported message targeted {len(fixture['recipients'])} users and included {len(fixture['urls'])} URLs.
    """).strip())
    add_attachment(base, ticket_id, "reported-message.eml", fixture["eml"], {
        "source": "report-phish",
        "message_id": fixture["message_id"],
        "sender": fixture["sender"],
        "source_ip": fixture["source_ip"],
        "urls": fixture["urls"],
        "recipients": fixture["recipients"],
    })
    add_attachment(base, ticket_id, "mail-gateway-recipient-scope.json", json.dumps(fixture, indent=2), {
        "source": "mailcow-demo-scope",
        "purpose": "recipient URL/click/credential/host evidence for local-model phishing workflow",
    })
    return ticket_id


def agent_prompt(ticket_id: int, fixture: dict) -> str:
    expected = json.dumps({
        "urls": fixture["urls"],
        "recipients": [r["email"] for r in fixture["recipients"]],
        "clicked": fixture["clicked"],
        "credentialed": fixture["credentialed"],
        "hosts": fixture["hosts"],
    }, indent=2)
    return f"""You are working a report-phish incident in the SOC dashboard.

Use only the dashboard API and your local checkpoint file. This is a lab demo,
but you must behave like production: write frequent ticket notes, open approval
gates before remediation, wait for approval, then complete approved gates with
clear evidence. Do not perform real network, identity, or endpoint changes.

Dashboard API base URL inside this runner: http://localhost:8000
Ticket id: {ticket_id}

Ground truth evidence that must be verified against the ticket context:
```json
{expected}
```

Important API schema:
- Ticket notes must send `body`, `author`, `source`, and `visibility`.
- Do not use `note` as the note body field.
- Use compact evidence, not the full context endpoint, so this stays fast on local models.
- Do not use shell `for` loops, `$variables`, command substitution, or `$(...)`
  in Bash tool calls. The Claude Code harness can reject those as shell
  expansion. Use static `curl` calls or a short Python/urllib script instead.

Required exact workflow:
1. Read checkpoint.json.
2. GET http://localhost:8000/api/postmortems/evidence/{ticket_id}?task_log_lines=0 and inspect the compact ticket evidence, notes, change requests, and attachment metadata. Do not call /api/tickets/{ticket_id}/context during this ticket-resolution task.
3. GET http://localhost:8000/api/tickets/{ticket_id}. Use `agent_instance_id` from that response as your `agent_id`.
4. POST a ticket note with JSON exactly shaped like {{"body":"Agent phishing triage started\\n\\n...", "author":"agent_<agent_id>", "source":"agent", "visibility":"internal"}}. The body must list recipients, URLs, clicked users, credential-exposed users, and endpoint hosts.
5. Create these five change requests with POST /api/changes/request. Include the real agent_id, ticket_id {ticket_id}, risk_level, reason, command, and approval_policy {{"demo_auto_approval": true, "lab_noop": true, "auto_complete": true}}:
   - action `block_url`, target `{fixture['urls'][0]}`.
   - action `quarantine_messages`, target `{fixture['message_id']}`.
   - action `send_training_followup`, target `{", ".join(fixture['clicked'])}`.
   - action `force_password_reset`, target `{", ".join(fixture['credentialed'])}`.
   - action `endpoint_scan`, target `{", ".join(fixture['hosts'])}`.
6. POST a ticket note with body starting "Agent waiting at approval gates" and listing all change ids.
7. Poll GET /api/changes/{{change_id}}/status until all five are approved. Use five
   static calls, not a shell loop.
8. Complete every approved change with POST /api/changes/{{change_id}}/complete and `completed_by` set to `agent_{{agent_id}}`. Evidence must say:
   - URL block was applied to the lab blocklist.
   - Mailcow quarantine was simulated for the message id and recipients.
   - Training/follow-up emails were queued for clicked users.
   - Password reset was required for credential-exposed users.
   - Wazuh/Sysmon endpoint scan was simulated for the listed hosts with no malware found in this lab run.
9. POST a final ticket note with body starting "Agent phishing remediation complete" and include scope, actions, evidence, residual risk, and recommended postmortem/workflow improvements.
10. Write checkpoint.json with step `report-phish-full-flow`, status `done`, progress_pct 100, output `report phish full flow complete`, and an ISO timestamp.
11. Reply exactly: report phish full flow complete
"""


def approve_pending_changes(base: str, ticket_id: int) -> list[int]:
    changes = request("GET", base, f"/api/changes?ticket_id={ticket_id}", timeout=120).get("changes", [])
    approved = []
    for change in changes:
        if change.get("status") != "pending":
            continue
        result = request("POST", base, f"/api/changes/{change['id']}/approve", {
            "approved_by": "report-phish-demo-auto-approver",
            "approval_reason": "Lab demo auto-approval: show approval chain while allowing local agent to continue.",
        }, timeout=120)
        approved.append(change["id"])
        replacement = (result.get("resume") or {}).get("agent_id")
        print(json.dumps({"auto_approved_change": change["id"], "replacement_agent_id": replacement}))
    return approved


def latest_tasks(base: str, ticket_id: int):
    return request("GET", base, f"/api/agents/tasks?ticket_id={ticket_id}", timeout=120).get("tasks", [])


def wait_for_agent(base: str, ticket_id: int, timeout: int) -> dict:
    deadline = time.time() + timeout
    last_rendered = ""
    seen_terminal = set()
    while time.time() < deadline:
        approve_pending_changes(base, ticket_id)
        tasks = latest_tasks(base, ticket_id)
        summary = [(t.get("id"), t.get("agent_id"), t.get("status"), t.get("progress_pct")) for t in tasks[:8]]
        rendered = json.dumps(summary)
        if rendered != last_rendered:
            print(json.dumps({"agent_tasks": summary}))
            last_rendered = rendered
        for task in tasks:
            if task.get("status") in ("completed", "failed", "stopped") and task.get("id") not in seen_terminal:
                seen_terminal.add(task.get("id"))
                logs = request("GET", base, f"/api/agents/tasks/{task['id']}/logs?lines=180", timeout=120)
                content = logs.get("content", "") or ""
                if "report phish full flow complete" in content or task.get("progress_pct") == 100:
                    return task
                if task.get("status") == "failed":
                    print(json.dumps({"failed_task": task.get("id"), "tail": content[-2000:]}))
        time.sleep(10)
    tasks = latest_tasks(base, ticket_id)
    for task in tasks:
        if task.get("agent_id") and task.get("status") in ("queued", "running"):
            request("POST", base, f"/api/agents/{task['agent_id']}/stop", {
                "reason": "report phish full demo timed out",
            }, timeout=120)
    raise RuntimeError(f"Timed out waiting for report-phish agent on ticket {ticket_id}")


def wait_for_postmortem(base: str, ticket_id: int, agent_id: int | None, task_id: int | None, timeout: int = 900) -> dict:
    deadline = time.time() + timeout
    last_status = ""
    while time.time() < deadline:
        context = request("GET", base, f"/api/tickets/{ticket_id}/context", timeout=120)
        postmortems = context.get("postmortems", [])
        if postmortems:
            return {"status": "ready", "postmortem": postmortems[0]}
        task = next((item for item in context.get("tasks", []) if item.get("id") == task_id), {})
        status = task.get("status", "missing")
        rendered = f"{status}:{task.get('progress_pct')}"
        if rendered != last_status:
            print(json.dumps({"postmortem_task": task_id, "status": status, "progress_pct": task.get("progress_pct")}))
            last_status = rendered
        if status in ("completed", "failed", "stopped", "missing"):
            synthesized = request("POST", base, f"/api/postmortems/synthesize/{ticket_id}", {
                "agent_id": agent_id,
                "task_id": task_id,
                "created_by": "report-phish-demo",
                "reason": f"postmortem task {status} without artifact",
            }, timeout=120)
            context = request("GET", base, f"/api/tickets/{ticket_id}/context", timeout=120)
            postmortems = context.get("postmortems", [])
            return {
                "status": synthesized.get("status", "synthesized"),
                "synthesis": synthesized,
                "postmortem": postmortems[0] if postmortems else None,
            }
        time.sleep(20)
    synthesized = request("POST", base, f"/api/postmortems/synthesize/{ticket_id}", {
        "agent_id": agent_id,
        "task_id": task_id,
        "created_by": "report-phish-demo",
        "reason": "postmortem task timed out",
    }, timeout=120)
    return {"status": synthesized.get("status", "timeout_synthesized"), "synthesis": synthesized}


def promote_postmortem(base: str, postmortem: dict | None) -> dict:
    if not postmortem or not postmortem.get("id"):
        return {"status": "skipped", "reason": "no postmortem"}
    return request("POST", base, f"/api/postmortems/{postmortem['id']}/promote", {
        "promote_knowledge": True,
        "promote_workflow": True,
        "promote_skills": True,
        "created_by": "report-phish-demo",
    }, timeout=120)


def validate(base: str, ticket_id: int, fixture: dict) -> dict:
    context = request("GET", base, f"/api/tickets/{ticket_id}/context", timeout=120)
    notes = context.get("notes", [])
    note_text = "\n\n".join(n.get("body", "") for n in notes)
    changes = context.get("changes") or context.get("change_requests") or []
    completed_actions = {
        (c.get("action") or "").lower()
        for c in changes
        if c.get("status") == "completed"
    }
    completed_action_text = "\n".join(sorted(completed_actions))
    note_text_lower = note_text.lower()
    required_action_families = {
        "url_block": ("block" in completed_action_text and ("url" in completed_action_text or "phishing" in completed_action_text)),
        "mailbox_quarantine": ("quarantine" in completed_action_text or "mailbox" in completed_action_text or "email" in completed_action_text),
        "account_review": ("password" in completed_action_text or "session" in completed_action_text or "account" in completed_action_text),
        "endpoint_scan": ("endpoint" in completed_action_text and "scan" in completed_action_text),
    }
    checks = {
        "agent_triage_note": (
            "triage" in note_text_lower
            and "sender" in note_text_lower
            and "recipient" in note_text_lower
            and "url" in note_text_lower
        ),
        "agent_final_note": (
            "phishing remediation complete" in note_text_lower
            or "final evidence" in note_text_lower
            or "ticket resolved" in note_text_lower
        ),
        "approval_notes_visible": "approval gate" in note_text_lower and ("approved" in note_text_lower or "completed" in note_text_lower),
        "all_expected_changes_completed": all(required_action_families.values()),
        "url_evidence": all(url in note_text for url in fixture["urls"]),
        "recipient_evidence": all(item["email"] in note_text for item in fixture["recipients"]),
        "training_evidence": (
            "training" in note_text_lower
            or "user follow-up" in note_text_lower
            or "recipient follow-up" in note_text_lower
            or "credential" in note_text_lower
        ),
        "password_reset_evidence": "password" in note_text.lower() and all(user in note_text for user in fixture["credentialed"]),
        "endpoint_scan_evidence": "endpoint" in note_text.lower() and all(host in note_text for host in fixture["hosts"]),
    }
    failures = [name for name, ok in checks.items() if not ok]
    return {
        "ok": not failures,
        "failures": failures,
        "checks": checks,
        "notes": len(notes),
        "changes": [{"id": c.get("id"), "action": c.get("action"), "status": c.get("status")} for c in changes],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Full local-model report-phish workflow demo")
    parser.add_argument("--base", default=DEFAULT_BASE, help="Dashboard base URL")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Agent model ID")
    parser.add_argument("--timeout", type=int, default=2400, help="Agent wait timeout seconds")
    parser.add_argument("--skip-postmortem", action="store_true", help="Skip postmortem/promotion pass")
    args = parser.parse_args()

    fixture = phishing_fixture(int(time.time()))
    ticket_id = create_ticket(args.base, fixture)
    print(json.dumps({"ticket_id": ticket_id, "model": args.model, "urls": fixture["urls"]}))

    spawn = request("POST", args.base, f"/api/tickets/{ticket_id}/assign-agent", {
        "model": args.model,
        "prompt": agent_prompt(ticket_id, fixture),
    }, timeout=120)
    print(json.dumps({"agent_spawn": spawn}))

    completed_task = wait_for_agent(args.base, ticket_id, args.timeout)
    validation = validate(args.base, ticket_id, fixture)

    postmortem_spawn = None
    postmortem_result = None
    promotion = None
    if not args.skip_postmortem:
        postmortem_spawn = request("POST", args.base, f"/api/tickets/{ticket_id}/postmortem", {
            "model": args.model,
            "context": (
                "Postmortem this phishing incident. Create reusable knowledge, workflow, and skill proposals for "
                "report-phish triage, URL blocking, message quarantine, clicked-user follow-up, password reset, "
                "and Wazuh/Sysmon endpoint scans. Use the compact evidence API first."
            ),
        }, timeout=120)
        postmortem_result = wait_for_postmortem(
            args.base,
            ticket_id,
            postmortem_spawn.get("agent_id"),
            postmortem_spawn.get("task_id"),
        )
        promotion = promote_postmortem(args.base, (postmortem_result or {}).get("postmortem"))

    summary = {
        "ok": validation["ok"],
        "ticket_id": ticket_id,
        "agent_task": completed_task,
        "validation": validation,
        "postmortem_spawn": postmortem_spawn,
        "postmortem_result": postmortem_result,
        "promotion": promotion,
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if validation["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
