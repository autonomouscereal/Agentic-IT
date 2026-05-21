#!/usr/bin/env python3
"""Exercise broad enterprise Ops Chat intake routing without spawning agents.

The goal is breadth: prove that many real-world chat requests become typed,
ticketed, auditable work with a clear agent-selected owner. Use
smoke_ops_chat_scenarios.py for the smaller real-agent handoff set.
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


CASES = [
    ("ceo-lockout", "The CEO is locked out of SSO before a board meeting.", "Executive Support"),
    ("standard-lockout", "I cannot log into my account and MFA is not working.", "Identity & Access"),
    ("password-reset", "I forgot my password and need to regain access.", "Identity & Access"),
    ("gitlab-access", "I need GitLab repository access for project phoenix.", "Identity & Access"),
    ("wazuh-access", "Please grant Wazuh analyst access for an investigation.", "Security Operations"),
    ("mailbox-access", "Add Alice to the finance shared mailbox as a reviewer.", "Email Operations"),
    ("distribution-list", "Add Jeff to the customer-updates distribution list.", "Email Operations"),
    ("mail-forwarding", "Set temporary mail forwarding for a departing employee.", "Email Operations"),
    ("phishing-report", "A user reported a suspicious email with a link from an unknown sender.", "Security Operations"),
    ("edr-alert", "A Wazuh EDR alert fired for suspicious PowerShell on a workstation.", "Security Operations"),
    ("false-positive", "An internal training email was flagged as phishing but may be legitimate.", "Security Operations"),
    ("url-block", "Block this suspicious URL after sandbox review and approval.", "Security Operations"),
    ("endpoint-isolation", "Isolate an endpoint after malware confirmation.", "Security Operations"),
    ("vpn-down", "My VPN stopped connecting after a reboot.", "Network Operations"),
    ("site-blocked", "I cannot access a SaaS website because the proxy blocked it.", "Network Operations"),
    ("dns-change", "Create a DNS CNAME record for app-demo.example.internal.", "Network Operations"),
    ("firewall-change", "Open port 443 from app subnet to the reporting server.", "Network Operations"),
    ("network-segmentation", "Update segmentation so finance systems cannot reach dev systems.", "Network Operations"),
    ("laptop-patch", "Update Chrome and Office on my laptop.", "Endpoint Support"),
    ("software-install", "Install approved screen recording software on my workstation.", "Endpoint Support"),
    ("new-software-license", "Buy a Figma software license for a designer.", "Procurement & Vendor Management"),
    ("adobe-license", "I need an Adobe software license for marketing work.", "Procurement & Vendor Management"),
    ("new-hire", "Onboard a new hire starting Monday with laptop, mailbox, and app accounts.", "Identity & Access"),
    ("offboarding", "Offboard a departing employee and revoke access at 5 PM.", "Identity & Access"),
    ("restore-file", "Restore a deleted finance file from backup.", "Infrastructure Operations"),
    ("server-backup-failed", "The backup failed for a production server overnight.", "Infrastructure Operations"),
    ("tls-renewal", "Renew the TLS certificate for the dashboard before it expires.", "Platform Operations"),
    ("cloud-vm", "Create an Azure VM for a temporary reporting workload.", "Cloud Operations"),
    ("s3-bucket", "Create an S3 bucket for project archive data.", "Cloud Operations"),
    ("cloud-cost", "Investigate a sudden cloud cost increase.", "Cloud Operations"),
    ("database-slow", "Postgres queries are timing out for the customer portal.", "Database Operations"),
    ("database-access", "Grant read-only database access for an analyst.", "Database Operations"),
    ("schema-change", "Apply a database schema change to staging.", "Database Operations"),
    ("ui-bug", "Fix this UI on the dashboard because a button is broken.", "Platform Operations"),
    ("blank-page", "The dashboard web page shows a blank page after login.", "Platform Operations"),
    ("app-error", "A business application throws an invalid JSON popup.", "Business Applications"),
    ("delivery-gate", "The deployment pipeline failed with Semgrep and Trivy findings.", "DevSecOps"),
    ("zap-finding", "OWASP ZAP found a security issue in the release gate.", "DevSecOps"),
    ("nuclei-finding", "Nuclei found an exposed admin panel in CI/CD scanning.", "DevSecOps"),
    ("policy-exception", "Request a temporary policy exception with risk acceptance.", "Compliance & Audit"),
    ("audit-report", "Create an audit report of ticket approvals this month.", "Compliance & Audit"),
    ("sla-report", "Generate an SLA report for executive review.", "Compliance & Audit"),
    ("data-export", "Export a ticket metrics report for the leadership deck.", "Compliance & Audit"),
    ("platform-proxy", "The agentic ops proxy route is broken and needs repair.", "Platform Operations"),
    ("workflow-broken", "The phishing workflow is broken and needs a safe fix.", "Platform Operations"),
    ("setup-module", "The setup module for Mailcow is broken and should be repaired.", "Platform Operations"),
    ("keycloak-client", "Manage a Keycloak OIDC client redirect URI for Ops Chat.", "Identity & Access"),
    ("mailcow-demo", "Mailcow webmail login is not working for a demo user.", "Email Operations"),
    ("gitlab-runner", "GitLab Runner is stuck and the pipeline will not start.", "DevSecOps"),
    ("executive-laptop", "An executive laptop cannot connect to the hotel Wi-Fi before a customer meeting.", "Executive Support"),
]


def request(base, method, path, payload=None, timeout=240):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if TOKEN:
        headers["X-Dashboard-Service-Token"] = TOKEN
    req = urllib.request.Request(base.rstrip("/") + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            raw = res.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed: HTTP {exc.code}: {body}") from exc


def cancel_ticket(base, ticket_id, marker):
    if not ticket_id:
        return {"status": "skipped", "reason": "missing_ticket_id"}
    try:
        return request(base, "POST", f"/api/tickets/{ticket_id}/status", {
            "status": "cancelled",
            "actor": "ops-chat-enterprise-matrix-smoke",
            "reason": f"Cleanup for broad Ops Chat matrix smoke {marker}; ticket was synthetic validation evidence.",
            "close_provider": True,
        }, timeout=60)
    except Exception as exc:
        return {"status": "error", "error": str(exc)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("base", nargs="?", default="http://localhost:25480")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--case", action="append", dest="only_cases",
                        help="Run only the named case slug. Can be supplied more than once.")
    parser.add_argument("--case-timeout", type=int, default=240)
    parser.add_argument("--strict-routing", action="store_true",
                        help="Fail on expected-group mismatch instead of reporting routing quality.")
    parser.add_argument("--require-provider-sync", action="store_true",
                        help="Fail when created tickets do not sync to an external provider.")
    parser.add_argument("--cleanup", action="store_true",
                        help="Cancel synthetic tickets after verification so broad tests do not clutter the demo queue.")
    args = parser.parse_args()
    if not TOKEN:
        raise SystemExit("DASHBOARD_SERVICE_TOKEN is required")
    marker = f"ops-chat-enterprise-matrix-{int(time.time())}"
    cases = CASES[: args.limit] if args.limit else CASES
    if args.only_cases:
        wanted = set(args.only_cases)
        cases = [case for case in cases if case[0] in wanted]
        missing = sorted(wanted - {case[0] for case in cases})
        if missing:
            raise SystemExit(f"Unknown case slug(s): {', '.join(missing)}")
    results = []
    failures = []
    for index, (slug, message, expected_group) in enumerate(cases, start=1):
        print(json.dumps({"progress": "case_start", "index": index, "total": len(cases), "case": slug}), flush=True)
        result = request(args.base, "POST", "/api/ops-chat/message", {
            "message": f"{message} Matrix marker {marker}-{slug}.",
            "requester_name": "Enterprise Matrix Tester",
            "requester_email": "matrix-demo@example.invalid",
            "external_thread_id": f"{marker}-{slug}",
            "force_new_ticket": True,
            "spawn_agent": False,
        }, timeout=args.case_timeout)
        classification = result.get("classification") or {}
        actual_group = classification.get("assignment_group")
        ticketed = bool(result.get("created_ticket"))
        ticket_id = result.get("ticket_id")
        ticket = request(args.base, "GET", f"/api/tickets/{ticket_id}") if ticket_id else {}
        routed = bool(actual_group)
        matches_hint = actual_group == expected_group
        provider_sync_ok = (
            not args.require_provider_sync
            or (
                ticket.get("provider")
                and ticket.get("provider") != "local"
                and ticket.get("provider_ref")
                and ticket.get("provider_sync_status") == "synced"
            )
        )
        ok = ticketed and routed and provider_sync_ok and (matches_hint or not args.strict_routing)
        record = {
            "case": slug,
            "ticket_id": ticket_id,
            "intent": classification.get("intent"),
            "expected_group": expected_group,
            "actual_group": actual_group,
            "matches_expected_hint": matches_hint,
            "provider": ticket.get("provider"),
            "provider_ref": ticket.get("provider_ref"),
            "provider_sync_status": ticket.get("provider_sync_status"),
            "provider_sync_ok": provider_sync_ok,
            "ok": ok,
        }
        results.append(record)
        print(json.dumps({"progress": "case_done", **record}), flush=True)
        if not ok:
            failures.append(record)
    search = request(args.base, "GET", f"/api/search/global?q={urllib.parse.quote(marker)}&limit=10")
    cleanup = []
    if args.cleanup:
        for record in results:
            cleanup.append({
                "case": record["case"],
                "ticket_id": record.get("ticket_id"),
                "result": cancel_ticket(args.base, record.get("ticket_id"), marker),
            })
    output = {
        "status": "passed" if not failures else "failed",
        "marker": marker,
        "case_count": len(cases),
        "failure_count": len(failures),
        "failures": failures,
        "search_total": search.get("total"),
        "cleanup": cleanup,
        "results": results,
    }
    print(json.dumps(output, indent=2))
    return 0 if not failures else 2


if __name__ == "__main__":
    raise SystemExit(main())
