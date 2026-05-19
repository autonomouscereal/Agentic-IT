#!/usr/bin/env python3
"""Complex real-agent proof for a phishing + EDR incident.

This is intentionally not a smoke test. It creates one iTop-synced incident and
drives a real dashboard agent through:

- requester information wait + user-response resume/steering while active
- dashboard note steering while active
- iTop public_log steering through provider sync
- URL safety analysis through sandbox/reputation-style evidence without direct
  suspicious URL retrieval
- denied per-agent Wazuh/SIEM vault lease
- access-request approval and resumed agent completion
- approval-gated lab-safe containment
- final ticket resolution, postmortem creation, and workflow promotion
"""
import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dashboard_auth import dashboard_auth_headers


def request(base, method, path, payload=None, expect=(200,)):
    data = None
    headers = dashboard_auth_headers(provider="complex-phish-edr-proof")
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(base.rstrip("/") + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            status = resp.status
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        status = exc.code
    parsed = json.loads(body) if body else {}
    if status not in expect:
        raise RuntimeError(f"{method} {path} returned HTTP {status}: {parsed}")
    return parsed


def note_bodies(context):
    return "\n".join(row.get("body") or "" for row in context.get("notes") or [])


def latest_task(base, agent_id):
    if not agent_id:
        return {}
    rows = request(base, "GET", f"/api/agents/tasks?agent_id={agent_id}").get("tasks") or []
    return rows[0] if rows else {}


def wait_no_active(base, timeout=180):
    start = time.time()
    while time.time() - start < timeout:
        active = request(base, "GET", "/api/agents/active")
        if active.get("count") == 0:
            return active
        time.sleep(5)
    raise TimeoutError("active agents did not drain")


def wait_for_active_process(base, task_id, timeout=300):
    start = time.time()
    while time.time() - start < timeout:
        snapshot = request(base, "GET", "/api/agents/processes")
        if task_id in (snapshot.get("active_processes") or []):
            return snapshot
        time.sleep(3)
    raise TimeoutError(f"task {task_id} did not appear in active_processes")


def wait_for_note(base, ticket_id, marker, timeout=900, allow_blocked=False):
    start = time.time()
    last = None
    while time.time() - start < timeout:
        context = request(base, "GET", f"/api/tickets/{ticket_id}/context")
        notes = note_bodies(context)
        if marker in notes:
            return context
        ticket = context.get("ticket") or {}
        agent_id = ticket.get("agent_id")
        task = latest_task(base, agent_id)
        if task.get("status") in {"failed", "stopped", "terminated"}:
            raise RuntimeError(f"agent ended before note {marker}: {task}")
        if not allow_blocked and task.get("status") in {"awaiting_access", "pending_approval", "blocked"}:
            raise RuntimeError(f"agent blocked before note {marker}: {task}")
        last = {
            "ticket_status": ticket.get("status"),
            "agent_id": agent_id,
            "task_status": task.get("status"),
            "task_progress": task.get("progress_pct"),
            "note_tail": notes[-600:],
        }
        print(json.dumps({"waiting_for_note": marker, "last": last}), flush=True)
        time.sleep(10)
    raise TimeoutError(f"note not observed: {marker}; last={last}")


def wait_for_url_sandbox_evidence(base, ticket_id, marker, timeout=1800):
    start = time.time()
    last = None
    while time.time() - start < timeout:
        context = request(base, "GET", f"/api/tickets/{ticket_id}/context")
        notes = note_bodies(context)
        attachments = context.get("attachments") or []
        sandbox_attachment = next(
            (
                row for row in attachments
                if marker in str(row.get("metadata") or "")
                or marker in str(row.get("storage_ref") or "")
                or marker in str(row.get("filename") or "")
            ),
            None,
        )
        if f"COMPLEX_URL_SANDBOX_COMPLETE {marker}" in notes and sandbox_attachment:
            metadata = sandbox_attachment.get("metadata") or {}
            if isinstance(metadata, str):
                try:
                    metadata = json.loads(metadata)
                except json.JSONDecodeError:
                    metadata = {}
            if metadata.get("direct_fetch_performed") is False and metadata.get("sandbox_adapter"):
                return context, sandbox_attachment
        ticket = context.get("ticket") or {}
        task = latest_task(base, ticket.get("agent_id"))
        if task.get("status") in {"failed", "stopped", "terminated"}:
            raise RuntimeError(f"agent ended before URL sandbox evidence: {task}")
        last = {
            "ticket_status": ticket.get("status"),
            "task_status": task.get("status"),
            "task_progress": task.get("progress_pct"),
            "attachment_count": len(attachments),
            "note_tail": notes[-500:],
        }
        print(json.dumps({"waiting_for_url_sandbox_evidence": marker, "last": last}), flush=True)
        time.sleep(12)
    raise TimeoutError(f"URL sandbox evidence not observed for {marker}: {last}")


def wait_for_access_request(base, ticket_id, marker, timeout=1800):
    start = time.time()
    last = None
    while time.time() - start < timeout:
        context = request(base, "GET", f"/api/tickets/{ticket_id}/context")
        access = context.get("access_requests") or []
        notes = note_bodies(context)
        ticket = context.get("ticket") or {}
        task = latest_task(base, ticket.get("agent_id"))
        if task.get("status") in {"failed", "stopped", "terminated"}:
            raise RuntimeError(f"agent ended before access request: {task}")
        task_status = task.get("status")
        last = {
            "ticket_status": ticket.get("status"),
            "task_status": task_status,
            "access_count": len(access),
            "note_tail": notes[-500:],
        }
        for row in access:
            if marker in str(row.get("reason") or "") or marker in notes:
                if task_status == "awaiting_access" or ticket.get("status") == "awaiting_access":
                    return context, row
                print(json.dumps({"waiting_for_access_checkpoint": marker, "last": last}), flush=True)
                time.sleep(12)
                break
        else:
            print(json.dumps({"waiting_for_access_request": marker, "last": last}), flush=True)
            time.sleep(12)
    raise TimeoutError(f"access request not observed for {marker}: {last}")


def wait_for_change(base, ticket_id, marker, action_contains, status="pending", timeout=1800):
    start = time.time()
    last = None
    while time.time() - start < timeout:
        changes = request(base, "GET", f"/api/changes?ticket_id={ticket_id}").get("changes") or []
        context = request(base, "GET", f"/api/tickets/{ticket_id}/context")
        ticket = context.get("ticket") or {}
        task = latest_task(base, ticket.get("agent_id"))
        if task.get("status") in {"failed", "stopped", "terminated"}:
            raise RuntimeError(f"agent ended before change {action_contains}: {task}")
        task_status = task.get("status")
        last = {
            "ticket_status": ticket.get("status"),
            "task_status": task_status,
            "changes": [(row.get("id"), row.get("status"), row.get("action")) for row in changes[:5]],
        }
        for row in changes:
            action = f"{row.get('action') or ''} {row.get('target') or ''} {row.get('reason') or ''}"
            if row.get("status") == status and marker in action and action_contains in action:
                if status != "pending" or task_status == "pending_approval" or ticket.get("status") == "pending_approval":
                    return row
                print(json.dumps({"waiting_for_change_checkpoint": action_contains, "last": last}), flush=True)
                time.sleep(12)
                break
        else:
            print(json.dumps({"waiting_for_change": action_contains, "last": last}), flush=True)
            time.sleep(12)
    raise TimeoutError(f"change not observed for {action_contains}: {last}")


def wait_for_completion(base, ticket_id, marker, timeout=3600):
    start = time.time()
    last = None
    while time.time() - start < timeout:
        context = request(base, "GET", f"/api/tickets/{ticket_id}/context")
        ticket = context.get("ticket") or {}
        notes = note_bodies(context)
        tasks = context.get("tasks") or []
        completed_task = any(
            row.get("status") == "completed"
            and int(row.get("progress_pct") or 0) >= 100
            and f"COMPLEX_INCIDENT_COMPLETE {marker}" in str(row.get("checkpoints") or "")
            for row in tasks
        )
        postmortems = request(base, "GET", f"/api/postmortems?ticket_id={ticket_id}").get("postmortems") or []
        workflows = request(base, "GET", "/api/workflows").get("workflows") or []
        workflow_hit = any(str(ticket_id) in str(row.get("approval_policy") or "") for row in workflows)
        if (
            ticket.get("status") == "resolved"
            and f"COMPLEX_INCIDENT_COMPLETE {marker}" in notes
            and completed_task
            and postmortems
            and workflow_hit
        ):
            return context, postmortems[0], workflow_hit
        task = latest_task(base, ticket.get("agent_id"))
        if task.get("status") in {"failed", "stopped", "terminated"}:
            raise RuntimeError(f"agent ended before completion: {task}")
        last = {
            "ticket_status": ticket.get("status"),
            "task_status": task.get("status"),
            "task_progress": task.get("progress_pct"),
            "postmortem_count": len(postmortems),
            "workflow_hit": workflow_hit,
            "note_tail": notes[-500:],
        }
        print(json.dumps({"waiting_for_completion": marker, "last": last}), flush=True)
        time.sleep(15)
    raise TimeoutError(f"complex proof did not complete: {last}")


def add_dashboard_steer(base, ticket_id, marker):
    return request(base, "POST", f"/api/tickets/{ticket_id}/notes", {
        "body": (
            f"DASHBOARD_COMPLEX_STEER {marker}: requester clarified the email was "
            "reported by finance and the EDR process lineage belongs to host FIN-LT-042. "
            "Keep the original objective and include both finance phishing and endpoint evidence."
        ),
        "author": "complex-demo-operator",
        "source": "dashboard",
        "visibility": "internal",
    })


def add_itop_public_log(itop_client, ticket_class, provider_ref, marker):
    payload = {
        "public_log": {
            "items": [
                {
                    "message": (
                        f"ITOP_COMPLEX_STEER {marker}: iTop-side update says finance "
                        "confirmed no credential entry, but one user clicked the URL before reporting."
                    )
                }
            ]
        }
    }
    completed = subprocess.run(
        ["python3", itop_client, "update", ticket_class, str(provider_ref), json.dumps(payload)],
        text=True,
        capture_output=True,
        check=False,
        timeout=120,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"iTop public_log update failed: {completed.stderr or completed.stdout}")
    parsed = json.loads(completed.stdout)
    if parsed.get("code") != 0:
        raise RuntimeError(f"iTop public_log update rejected: {completed.stdout}")
    return parsed


def build_prompt(ticket_id, marker):
    return f"""
You are proving a complex real-world phishing + EDR incident flow for marker {marker}.

Use only the dashboard API at http://localhost:8000 and files in this work directory.
Use `agent_vault.json` to find your agent_id. Use Write to create JSON payload
files and Bash `curl -d @file`; do not put inline JSON directly in Bash.
Use the exact endpoints and payloads listed below. Do not inspect `/openapi.json`,
`/docs`, or `/redoc`, and do not pipe curl output into Python, shell, node, or
any interpreter.
Do not use external credentials. Secret values must never be requested or printed.
Read `agent_steering_inbox.json` before each major action/checkpoint.

Original incident:
- Finance reported a suspicious email with URL `http://training-login.example.invalid/reset`.
- Wazuh/EDR raised Sysmon rule `100230` for host `FIN-LT-042`, user `finance.user`, process `powershell.exe -EncodedCommand <redacted>`.
- The task is lab-safe: investigate, document, request needed access, gate containment, and resolve with postmortem/workflow learning.

First active-agent path:
1. GET /api/tickets/{ticket_id}/context and add a note exactly containing: COMPLEX_TRIAGE_STARTED {marker}.
2. POST /api/tickets/{ticket_id}/request-info asking whether the user clicked the URL and entered credentials. Include marker {marker}, requested_by `agent_<agent_id>`, contact_method `email`, recipient `finance.user@example.local`.
3. Add a note exactly containing: COMPLEX_AWAITING_USER {marker}.
4. Poll `agent_steering_inbox.json` until it contains `USER_COMPLEX_RESPONSE {marker}` from a user-response note.
5. Add a note exactly containing: COMPLEX_USER_RESPONSE_OBSERVED {marker}.
6. Add a note exactly containing: COMPLEX_READY_DASHBOARD_STEER {marker}.
7. Poll `agent_steering_inbox.json` until it contains `DASHBOARD_COMPLEX_STEER {marker}`.
8. Add a note exactly containing: COMPLEX_DASHBOARD_STEER_OBSERVED {marker}.
9. Add a note exactly containing: COMPLEX_READY_ITOP_STEER {marker}.
10. Poll `agent_steering_inbox.json` until it contains `ITOP_COMPLEX_STEER {marker}`.
11. Add a note exactly containing: COMPLEX_ITOP_STEER_OBSERVED {marker}.
12. Perform URL safety analysis without direct target retrieval. Do not curl, wget, browse, screenshot, Python-request, or otherwise fetch `http://training-login.example.invalid/reset`. Treat it as hostile evidence. Use this approved lab sandbox/reputation fixture instead: sandbox_adapter `urlscan-compatible-lab-sandbox`, isolated_network true, direct_fetch_performed false, verdict `suspicious_credential_harvest`, indicators `training-login.example.invalid`, `/reset`, finance-themed credential harvest, recommendation `approval-gated URL watchlist/block plus mailbox quarantine review`.
13. POST /api/tickets/{ticket_id}/attachments with filename `url-sandbox-{marker}.json`, content_type `application/json`, storage_ref `sandbox://urlscan-compatible-lab/{marker}`, sha256 `lab-sandbox-{marker}`, size_bytes 0, and metadata containing marker `{marker}`, sandbox_adapter, direct_fetch_performed false, isolated_network true, original_url, defanged_url, verdict, indicators, and recommendation.
14. Add a note exactly containing: COMPLEX_URL_SANDBOX_COMPLETE {marker}: sandbox_adapter urlscan-compatible-lab-sandbox; direct_fetch_performed false; verdict suspicious_credential_harvest; recommendation approval-gated URL watchlist/block and mailbox quarantine review.
15. POST /api/agents/<agent_id>/vault/lease for {{"system":"wazuh","resource_type":"alert_index","resource_id":"finance-edr-restricted","action":"read"}}. It must return HTTP 403/access_denied because no per-agent lease exists yet.
16. Add a note exactly containing: COMPLEX_PERMISSION_WALL {marker}: Wazuh alert_index finance-edr-restricted read denied by missing_agent_vault_lease; access request required.
17. POST /api/tickets/{ticket_id}/access-request with agent_id, resource `Wazuh alert index finance-edr-restricted`, permission `read`, account_ref `agent-<agent_id>`, assignment_group `Security Operations`, risk_level `medium`, sync_provider true, reason `COMPLEX_PERMISSION_WALL {marker}: Wazuh alert index read required for phishing plus EDR correlation.`, and lease_request {{"system":"wazuh","resource_type":"alert_index","resource_id":"finance-edr-restricted","action":"read","credential_ref":"<vault:wazuh_finance_edr_read_after_approval>"}}.
18. Write checkpoint.json with step `waiting-for-wazuh-access-{marker}`, status `waiting_for_access`, progress_pct 45, output `COMPLEX_PERMISSION_WALL {marker}`, and an ISO timestamp. Reply exactly: waiting for wazuh access {marker}

Resume path after Wazuh access approval:
1. GET /api/tickets/{ticket_id}/context and find the approved/granted access request and change_id.
2. If the access change is approved, POST /api/changes/<change_id>/complete with completed_by `agent_<agent_id>` and result `COMPLEX_ACCESS_GRANTED {marker}: lab-safe Wazuh alert index read lease approved; no secret values exposed.`
3. POST /api/agents/<agent_id>/vault/lease again for Wazuh finance-edr-restricted read. It must now be allowed and return credential_ref `<vault:wazuh_finance_edr_read_after_approval>` with credential_value null.
4. Add a note exactly containing: COMPLEX_ACCESS_GRANTED {marker}.
5. POST /api/changes/request for a containment gate with action `lab-safe phishing and EDR containment {marker}`, target `finance phishing URL and host FIN-LT-042`, reason `COMPLEX_CONTAINMENT_GATE {marker}: URL watchlist, mailbox search/quarantine review, and EDR false-positive/rule-tuning recommendation require approval.`, risk_level `medium`, agent_id, ticket_id, and approval_policy including {{"complex_demo": true, "marker": "{marker}", "lab_safe": true}}.
6. Add a note exactly containing: COMPLEX_CONTAINMENT_GATE_READY {marker}.
7. Write checkpoint.json with step `waiting-for-containment-approval-{marker}`, status `pending_approval`, progress_pct 70, output `COMPLEX_CONTAINMENT_GATE {marker}`, and an ISO timestamp. Reply exactly: waiting for containment approval {marker}

Final resume path after containment approval:
1. GET /api/tickets/{ticket_id}/context and find the approved containment change.
2. POST /api/changes/<containment_change_id>/complete with completed_by `agent_<agent_id>` and result `COMPLEX_CONTAINMENT_COMPLETE {marker}: lab-safe URL watchlist entry, mailbox quarantine review, endpoint evidence review, and no blanket EDR suppression.`
3. Add a note exactly containing: COMPLEX_CONTAINMENT_COMPLETE {marker}: clicked URL was analyzed through sandbox/reputation evidence without direct target retrieval, no credential entry, host FIN-LT-042 reviewed, no blanket suppression, precise future rule tuning requires separate approval.
4. POST /api/postmortems with ticket_id, agent_id, task_id if known, status `ready_for_review`, summary mentioning `COMPLEX_INCIDENT_COMPLETE {marker}`, went_well including user-response, access gate, containment gate, and URL sandbox evidence, improvements, workflow_proposal for a combined phishing+EDR+access+user-response+URL-safety workflow, two skill_proposals, three test_cases, guardrails including no direct suspicious URL retrieval, documentation.
5. POST /api/postmortems/<id>/review with reviewed_by `complex-demo-reviewer`, approved true, review_notes `Approved lab proof {marker}`.
6. POST /api/postmortems/<id>/promote with create_knowledge true, create_workflow true, create_skills true, workflow_status `draft`, created_by `complex-demo-agent`, mark_promoted true.
7. POST /api/tickets/{ticket_id}/status with status `resolved`, actor `agent_<agent_id>`, reason `COMPLEX_INCIDENT_COMPLETE {marker}: phishing plus EDR incident completed with user response, steering, access gate, containment gate, postmortem, and workflow assets.`, close_provider false.
8. Write checkpoint.json with step `complex-incident-complete-{marker}`, status `done`, progress_pct 100, output `COMPLEX_INCIDENT_COMPLETE {marker}`, and an ISO timestamp.
9. Reply exactly: COMPLEX_INCIDENT_COMPLETE {marker}
""".strip()


def main():
    parser = argparse.ArgumentParser(description="Run complex phishing + EDR active-agent proof")
    parser.add_argument("base", nargs="?", default="http://127.0.0.1:25480")
    parser.add_argument("model", nargs="?", default="deepseek/deepseek-v4-flash")
    parser.add_argument("--itop-client", default="/home/cereal/SOC_TESTING/itop-deployment/scripts/itop_client.py")
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--marker", default=f"COMPLEX_PHISH_EDR_{int(time.time())}")
    args = parser.parse_args()

    wait_no_active(args.base)
    marker = args.marker
    ticket = request(args.base, "POST", "/api/tickets", {
        "title": f"Complex phish + EDR incident {marker}",
        "description": (
            "Finance reported a suspicious email while Wazuh/EDR raised a Sysmon alert on FIN-LT-042. "
            "Exercise requester follow-up, note steering, provider note sync, permission gates, containment approval, and learning promotion."
        ),
        "ticket_class": "Incident",
        "priority": "P2",
        "sync_provider": True,
        "created_by": "complex-phish-edr-demo",
        "auto_assign": False,
        "owning_group": "Security Operations",
        "security_classification": "confidential",
    })
    ticket_id = ticket["id"]
    provider_ref = ticket.get("provider_ref") or ticket.get("itop_ref")
    provider_class = ticket.get("provider_class") or ticket.get("itop_class") or "Incident"
    print(json.dumps({"ticket_id": ticket_id, "provider_ref": provider_ref, "provider_class": provider_class, "marker": marker}), flush=True)

    spawn = request(args.base, "POST", f"/api/tickets/{ticket_id}/assign-agent", {
        "model": args.model,
        "prompt": build_prompt(ticket_id, marker),
        "requested_permissions": [
            "tickets:read",
            "tickets:note",
            "tickets:request_info",
            "access:request",
            "changes:request",
            "changes:complete",
            "postmortems:write",
            "workflows:write",
        ],
    })
    if spawn.get("error"):
        raise RuntimeError(spawn)
    agent_id = spawn["agent_id"]
    task_id = spawn["task_id"]
    print(json.dumps({"agent_id": agent_id, "task_id": task_id}), flush=True)
    wait_for_active_process(args.base, task_id, timeout=min(300, args.timeout))

    wait_for_note(args.base, ticket_id, f"COMPLEX_AWAITING_USER {marker}", timeout=args.timeout)
    user = request(args.base, "POST", f"/api/tickets/{ticket_id}/user-response", {
        "response": (
            f"USER_COMPLEX_RESPONSE {marker}: I clicked the link from the finance laptop, "
            "but did not enter credentials. The browser showed a training-branded page and I closed it."
        ),
        "responder_name": "Finance User",
        "responder_email": "finance.user@example.local",
        "resume_agent": True,
    })
    print(json.dumps({"user_response": user}), flush=True)
    wait_for_note(args.base, ticket_id, f"COMPLEX_USER_RESPONSE_OBSERVED {marker}", timeout=args.timeout)

    wait_for_note(args.base, ticket_id, f"COMPLEX_READY_DASHBOARD_STEER {marker}", timeout=args.timeout)
    dashboard_note = add_dashboard_steer(args.base, ticket_id, marker)
    print(json.dumps({"dashboard_note": dashboard_note}), flush=True)
    wait_for_note(args.base, ticket_id, f"COMPLEX_DASHBOARD_STEER_OBSERVED {marker}", timeout=args.timeout)

    wait_for_note(args.base, ticket_id, f"COMPLEX_READY_ITOP_STEER {marker}", timeout=args.timeout)
    itop_update = add_itop_public_log(args.itop_client, provider_class, provider_ref, marker)
    print(json.dumps({"itop_update_code": itop_update.get("code"), "provider_ref": provider_ref}), flush=True)
    sync = request(args.base, "POST", f"/api/tickets/{ticket_id}/sync")
    print(json.dumps({"sync": sync}), flush=True)
    wait_for_note(args.base, ticket_id, f"COMPLEX_ITOP_STEER_OBSERVED {marker}", timeout=args.timeout)
    url_context, url_attachment = wait_for_url_sandbox_evidence(args.base, ticket_id, marker, timeout=args.timeout)
    print(json.dumps({"url_sandbox_attachment": {
        "id": url_attachment.get("id"),
        "filename": url_attachment.get("filename"),
        "storage_ref": url_attachment.get("storage_ref"),
        "metadata": url_attachment.get("metadata"),
    }}), flush=True)

    _access_context, access = wait_for_access_request(args.base, ticket_id, marker, timeout=args.timeout)
    change_id = access.get("change_id")
    if not change_id:
        raise RuntimeError(f"access request has no change_id: {access}")
    approval = request(args.base, "POST", f"/api/changes/{change_id}/approve", {
        "approved_by": "complex-access-approver",
        "reason": f"Approving scoped lab-safe Wazuh read lease for {marker}.",
    })
    print(json.dumps({"access_approval": approval}), flush=True)

    containment = wait_for_change(args.base, ticket_id, marker, "lab-safe phishing and EDR containment", "pending", timeout=args.timeout)
    containment_approval = request(args.base, "POST", f"/api/changes/{containment['id']}/approve", {
        "approved_by": "complex-containment-approver",
        "reason": f"Approving lab-safe containment actions for {marker}; no production isolation or blanket suppression.",
    })
    print(json.dumps({"containment_approval": containment_approval}), flush=True)

    final_context, postmortem, workflow_hit = wait_for_completion(args.base, ticket_id, marker, timeout=args.timeout)
    steering = request(args.base, "GET", f"/api/agents/{agent_id}/steering")
    forced_sync = request(args.base, "POST", f"/api/tickets/{ticket_id}/sync")
    post_sync_context = request(args.base, "GET", f"/api/tickets/{ticket_id}/context")
    active = request(args.base, "GET", "/api/agents/active")
    processes = request(args.base, "GET", "/api/agents/processes")

    result = {
        "status": "passed",
        "marker": marker,
        "ticket_id": ticket_id,
        "provider_ref": provider_ref,
        "provider_class": provider_class,
        "initial_agent_id": agent_id,
        "initial_task_id": task_id,
        "access_request_id": access.get("id"),
        "access_change_id": change_id,
        "containment_change_id": containment.get("id"),
        "postmortem_id": postmortem.get("id"),
        "url_sandbox_attachment_id": url_attachment.get("id"),
        "workflow_promoted": workflow_hit,
        "initial_agent_steering_events": steering.get("total"),
        "ticket_status": (post_sync_context.get("ticket") or {}).get("status"),
        "forced_sync": forced_sync,
        "active_agents": active.get("count"),
        "active_processes": processes.get("active_processes"),
        "note_count": len(final_context.get("notes") or []),
    }
    if result["ticket_status"] != "resolved":
        raise RuntimeError({"error": "ticket did not remain resolved after provider sync", "result": result})
    if result["active_agents"] != 0 or result["active_processes"]:
        raise RuntimeError({"error": "agents still active after proof", "result": result})
    print(json.dumps(result, indent=2), flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}), file=sys.stderr)
        raise
