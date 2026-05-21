#!/usr/bin/env python3
"""Run production-style Ops Chat scenarios across intake, tickets, and agents.

This is intentionally API-level so it can run in CI and on the live server
without a human driving Element. Matrix/Element remains the supported user
client; this smoke exercises the same dashboard endpoint used by the bridge.
"""
import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


TOKEN = os.environ.get("DASHBOARD_SERVICE_TOKEN", "")


def request(base, method, path, payload=None, timeout=240):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if TOKEN:
        headers["X-Dashboard-Service-Token"] = TOKEN
    req = urllib.request.Request(base.rstrip("/") + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            body = res.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed: HTTP {exc.code}: {body}") from exc


def require(condition, message):
    if not condition:
        raise AssertionError(message)


def get_context(base, ticket_id):
    return request(base, "GET", f"/api/tickets/{ticket_id}/context")


def note_bodies(context):
    return [str(note.get("body") or "") for note in context.get("notes") or []]


def has_user_response_note(context):
    for note in context.get("notes") or []:
        source = str(note.get("source") or "")
        body = str(note.get("body") or "")
        if source == "user-response":
            return True
        if "User chat follow-up" in body or "User response received" in body:
            return True
    return False


def progress_note_bodies(context):
    bodies = []
    for note in context.get("notes") or []:
        source = str(note.get("source") or "")
        if source in ("agent-control-plane", "ops-chat"):
            continue
        bodies.append(str(note.get("body") or ""))
    return bodies


def run_general_chat(base, marker):
    print(json.dumps({"progress": "scenario_start", "scenario": "general-chat", "marker": marker}), flush=True)
    result = request(base, "POST", "/api/ops-chat/message", {
        "message": f"What can this operations assistant help with? Marker {marker}.",
        "requester_name": "Demo User",
        "requester_email": "demo@example.invalid",
        "external_thread_id": f"{marker}-general",
        "force_new_ticket": True,
        "spawn_agent": False,
    })
    require(not result.get("created_ticket"), f"general chat should not create a ticket: {result}")
    require(result.get("ticket_id") is None, f"general chat returned a ticket: {result}")
    web = request(base, "POST", "/api/ops-chat/message", {
        "message": f"What is a current rough median home price in Reno Nevada? Use private web search if needed. Marker {marker}.",
        "requester_name": "Demo User",
        "requester_email": "demo@example.invalid",
        "external_thread_id": f"{marker}-web-search",
        "force_new_ticket": True,
        "spawn_agent": False,
    })
    require(not web.get("created_ticket"), f"benign web question should not create a ticket: {web}")
    require(len(str(web.get("reply") or "")) > 20, f"benign web question returned weak reply: {web}")
    cat = request(base, "POST", "/api/ops-chat/message", {
        "message": f"Send me a short text picture of a cat. Marker {marker}.",
        "requester_name": "Demo User",
        "requester_email": "demo@example.invalid",
        "external_thread_id": f"{marker}-cat-memory",
        "force_new_ticket": True,
        "spawn_agent": False,
    })
    require(not cat.get("created_ticket"), f"cat chat should not create a ticket: {cat}")
    cat_follow = request(base, "POST", "/api/ops-chat/message", {
        "session_id": cat.get("session_id"),
        "message": "Make that cat look sleepier, please.",
        "requester_name": "Demo User",
        "requester_email": "demo@example.invalid",
        "spawn_agent": False,
    })
    require(not cat_follow.get("created_ticket"), f"cat follow-up should stay general chat: {cat_follow}")
    require(cat_follow.get("ticket_id") is None, f"cat follow-up unexpectedly attached to ticket: {cat_follow}")
    return {
        "scenario": "general-chat",
        "reply": result.get("reply", "")[:180],
        "web_search_reply": web.get("reply", "")[:220],
        "cat_followup_reply": cat_follow.get("reply", "")[:180],
    }


def run_ticket_scenario(base, marker, name, message, expected_group, expected_intent=None,
                        require_no_intake_gate=False):
    print(json.dumps({"progress": "scenario_start", "scenario": name, "marker": marker}), flush=True)
    result = request(base, "POST", "/api/ops-chat/message", {
        "message": f"{message} Marker {marker}-{name}.",
        "requester_name": "Demo User",
        "requester_email": "demo@example.invalid",
        "external_thread_id": f"{marker}-{name}",
        "force_new_ticket": True,
        "spawn_agent": False,
    })
    require(result.get("created_ticket"), f"{name} did not create a ticket: {result}")
    ticket_id = result.get("ticket_id")
    classification = result.get("classification") or {}
    require(classification.get("assignment_group") == expected_group,
            f"{name} routed to {classification.get('assignment_group')} instead of {expected_group}: {result}")
    if expected_intent:
        require(classification.get("intent"), f"{name} missing agent-selected intent: {result}")
    if require_no_intake_gate:
        require(not result.get("change_id"),
                f"{name} opened an intake-time approval gate; gates must come from execution barriers: {result}")
    context = get_context(base, ticket_id)
    bodies = note_bodies(context)
    require(any("Ops Chat agent-created ticket" in body for body in bodies),
            f"{name} ticket missing Ops Chat agent-created ticket note")

    follow = request(base, "POST", "/api/ops-chat/message", {
        "session_id": result.get("session_id"),
        "message": f"Follow-up for {marker}-{name}: the requester confirms this is urgent but no production change is approved yet.",
        "requester_name": "Demo User",
        "requester_email": "demo@example.invalid",
        "spawn_agent": False,
    })
    require(follow.get("continued_ticket"), f"{name} follow-up did not continue ticket: {follow}")
    context = get_context(base, ticket_id)
    require(has_user_response_note(context),
            f"{name} ticket missing user-response follow-up note")
    return {
        "scenario": name,
        "ticket_id": ticket_id,
        "intent": classification.get("intent"),
        "expected_intent_hint": expected_intent,
        "assignment_group": classification.get("assignment_group"),
        "intake_change_id": result.get("change_id"),
        "reply": result.get("reply", "")[:180],
    }


def wait_for_agent_progress(base, agent_id, ticket_id, timeout_seconds):
    deadline = time.time() + timeout_seconds
    last = None
    while time.time() < deadline:
        agent = request(base, "GET", f"/api/agents/{agent_id}", timeout=30)
        context = get_context(base, ticket_id)
        bodies = note_bodies(context)
        progress_bodies = progress_note_bodies(context)
        task = agent.get("task") or agent.get("current_task") or {}
        agent_row = agent.get("agent") or agent
        last = {
            "agent_status": agent_row.get("status"),
            "task_status": task.get("status"),
            "note_count": len(bodies),
            "latest_notes": bodies[-5:],
        }
        terminal = {agent_row.get("status"), task.get("status")} & {
            "completed", "finished", "terminated", "failed", "stopped", "cancelled"
        }
        if terminal:
            return {"status": "terminal", **last}
        progress_markers = (
            "Awaiting user response",
            "Agent waiting",
            "Agent checkpoint:",
            "resolution",
            "clarification",
            "requester input",
            "approval gate",
            "access request",
        )
        if any(any(marker.lower() in body.lower() for marker in progress_markers)
               for body in progress_bodies):
            return {"status": "progress", **last}
        time.sleep(10)
    return {"status": "timeout", **(last or {})}


REAL_AGENT_CASES = {
    "account-lockout": (
        "I cannot log into my account before a customer call. "
        "Please create the ticket, check context, write a concise user-facing next step, "
        "and avoid any credential change unless an approval gate is opened."
    ),
    "software-request": (
        "I need approved screen recording software installed on my workstation for a training session. "
        "Please collect the minimum details, route the request, and explain the next approval or support step."
    ),
    "vpn-outage": (
        "My VPN stopped connecting after a laptop reboot and I need access to the finance file share. "
        "Please triage the request, ask for one useful clarification if needed, and do not make network changes without approval."
    ),
    "phishing-edr": (
        "A user reported a suspicious email and the endpoint also has a Wazuh-style EDR alert. "
        "Create the ticket, avoid directly browsing or curling the suspicious URL, request access or approvals if needed, "
        "and write a clear evidence-focused next step."
    ),
    "delivery-gate": (
        "A release is blocked by Semgrep and Trivy findings in CI/CD. "
        "Create the ticket, review the delivery-gate context, ask for repository access if needed, "
        "and do not approve deployment without a policy gate."
    ),
}


def run_agent_handoff(base, marker, timeout_seconds, case_name="account-lockout", message=None):
    print(json.dumps({"progress": "real_agent_start", "case": case_name, "marker": marker}), flush=True)
    message = message or REAL_AGENT_CASES[case_name]
    result = request(base, "POST", "/api/ops-chat/message", {
        "message": f"{message} Marker {marker}-agent-{case_name}.",
        "requester_name": "Demo User",
        "requester_email": "demo@example.invalid",
        "external_thread_id": f"{marker}-agent-{case_name}",
        "force_new_ticket": True,
        "spawn_agent": True,
    })
    require(result.get("created_ticket"), f"agent handoff did not create ticket: {result}")
    agent = result.get("agent") or {}
    agent_id = agent.get("agent_id")
    require(agent_id, f"agent handoff did not spawn a real agent: {result}")
    ticket_id = result.get("ticket_id")
    progress = wait_for_agent_progress(base, agent_id, ticket_id, timeout_seconds)
    if progress.get("status") == "timeout":
        request(base, "POST", f"/api/agents/{agent_id}/stop", {
            "reason": f"ops-chat scenario smoke timeout for {marker}/{case_name}; stopping only spawned test agent"
        }, timeout=30)
        raise AssertionError(f"agent {agent_id} timed out without visible progress: {progress}")
    return {
        "scenario": f"real-agent-{case_name}",
        "ticket_id": ticket_id,
        "agent_id": agent_id,
        "task_id": agent.get("task_id"),
        "progress": progress,
    }


def cleanup_result(base, result, marker):
    ticket_id = result.get("ticket_id")
    agent_id = result.get("agent_id")
    cleanup = {"scenario": result.get("scenario"), "ticket_id": ticket_id, "agent_id": agent_id}
    if agent_id:
        try:
            cleanup["agent_stop"] = request(base, "POST", f"/api/agents/{agent_id}/stop", {
                "reason": f"Ops Chat scenario cleanup for synthetic marker {marker}; stopping only this test-owned agent."
            }, timeout=60)
        except Exception as exc:
            cleanup["agent_stop"] = {"status": "error", "error": str(exc)}
    if ticket_id:
        try:
            cleanup["ticket_status"] = request(base, "POST", f"/api/tickets/{ticket_id}/status", {
                "status": "cancelled",
                "actor": "ops-chat-scenario-smoke",
                "reason": f"Cleanup for synthetic Ops Chat scenario marker {marker}.",
                "close_provider": True,
            }, timeout=90)
        except Exception as exc:
            cleanup["ticket_status"] = {"status": "error", "error": str(exc)}
    return cleanup


def main():
    parser = argparse.ArgumentParser(description="Run Ops Chat scenario smoke tests")
    parser.add_argument("base", nargs="?", default="http://localhost:25480")
    parser.add_argument("--spawn-agent", action="store_true",
                        help="Also spawn one real dashboard agent and wait for visible progress")
    parser.add_argument("--agent-case", action="append", choices=sorted(REAL_AGENT_CASES.keys()),
                        help="Real-agent case to run. Can be supplied more than once. Defaults to account-lockout when --spawn-agent is used.")
    parser.add_argument("--all-agent-cases", action="store_true",
                        help="Run every real-agent case sequentially. Use only on live/demo systems with enough provider capacity.")
    parser.add_argument("--agent-timeout", type=int, default=360)
    parser.add_argument("--agent-only", action="store_true",
                        help="Skip the broad preflight scenarios and run only requested real-agent handoff cases.")
    parser.add_argument("--cleanup", action="store_true",
                        help="Cancel synthetic tickets and stop test-owned agents after validation.")
    args = parser.parse_args()

    if not TOKEN:
        raise SystemExit("DASHBOARD_SERVICE_TOKEN is required")
    base = args.base.rstrip("/")
    stamp = int(time.time())
    marker = f"ops-chat-scenarios-{stamp}"

    health = request(base, "GET", "/api/ops-chat/matrix/health")
    require(health.get("client") == "Matrix Synapse + Element", f"unexpected chat health: {health}")

    results = []
    if not args.agent_only:
        results = [run_general_chat(base, marker)]
        results.append(run_ticket_scenario(
            base,
            marker,
            "account-lockout",
            "I cannot log into my account and I have a customer call in 20 minutes. I can receive SMS MFA codes.",
            "Identity & Access",
            "identity-help",
            False,
        ))
        results.append(run_ticket_scenario(
            base,
            marker,
            "software-request",
            "I need approved screen recording software installed on my workstation for a training session.",
            "Endpoint Support",
            "endpoint-support",
            False,
        ))
        results.append(run_ticket_scenario(
            base,
            marker,
            "vpn-connectivity",
            "My VPN stopped connecting after a reboot and I cannot reach the finance file share that worked yesterday.",
            "Network Operations",
            "vpn-connectivity",
            False,
        ))
        results.append(run_ticket_scenario(
            base,
            marker,
            "phishing-report",
            "A user reported a suspicious email with a bad link from an unknown sender. Nobody should directly browse the URL.",
            "Security Operations",
            "phishing",
            True,
        ))
        results.append(run_ticket_scenario(
            base,
            marker,
            "deployment-gate",
            "The deployment pipeline failed after Semgrep and Trivy findings and I need a delivery gate review.",
            "DevSecOps",
            "devsecops",
            True,
        ))
    if args.spawn_agent:
        if args.all_agent_cases:
            agent_cases = sorted(REAL_AGENT_CASES.keys())
        else:
            agent_cases = args.agent_case or ["account-lockout"]
        for case_name in agent_cases:
            results.append(run_agent_handoff(base, marker, args.agent_timeout, case_name=case_name))

    query = urllib.parse.quote(marker)
    search = request(base, "GET", f"/api/search/global?q={query}&limit=20")
    min_search_results = 1 if args.agent_only else 4
    require(search.get("total", 0) >= min_search_results, f"global search did not find scenario tickets: {search}")
    cleanup = [cleanup_result(base, result, marker) for result in results if args.cleanup]

    print(json.dumps({
        "status": "passed",
        "base": base,
        "marker": marker,
        "health": health,
        "results": results,
        "search_total": search.get("total"),
        "cleanup": cleanup,
    }, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}), file=sys.stderr)
        raise
