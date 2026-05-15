#!/usr/bin/env python3
"""Normalize local-only proof tickets and push them to the active provider.

The script intentionally uses dashboard APIs for provider operations and raw
PostgreSQL only for the missing maintenance operation: normalizing historical
ticket class values before provider push.
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request


VALID_CLASSES = {"Incident", "UserRequest", "RoutineChange", "NormalChange", "EmergencyChange"}


def request_json(base, method, path, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        base.rstrip("/") + path,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        return {"error": f"HTTP {exc.code}", "body": body[:1000]}


def normalize_class(value):
    text = str(value or "UserRequest")
    if text == "Change":
        return "RoutineChange"
    if text.startswith("WorkflowReuseSmoke"):
        return "Incident"
    if text == "BrokerLeaseProof":
        return "UserRequest"
    if text in VALID_CLASSES:
        return text
    lowered = text.lower()
    if any(part in lowered for part in ("phish", "incident", "alert", "edr")):
        return "Incident"
    if any(part in lowered for part in ("change", "deploy", "cicd", "setup")):
        return "RoutineChange"
    return "UserRequest"


def normalize_db_classes(repo_dir, apply):
    sql = """
WITH targets AS (
    SELECT id, itop_class, provider_class
    FROM tickets
    WHERE itop_class NOT IN ('Incident','UserRequest','RoutineChange','NormalChange','EmergencyChange')
       OR COALESCE(provider_class, itop_class) NOT IN ('Incident','UserRequest','RoutineChange','NormalChange','EmergencyChange')
),
normalized AS (
    UPDATE tickets t
    SET itop_class = CASE
            WHEN t.itop_class = 'Change' THEN 'RoutineChange'
            WHEN t.itop_class LIKE 'WorkflowReuseSmoke%' THEN 'Incident'
            WHEN t.itop_class = 'BrokerLeaseProof' THEN 'UserRequest'
            WHEN t.itop_class IN ('Incident','UserRequest','RoutineChange','NormalChange','EmergencyChange') THEN t.itop_class
            ELSE 'UserRequest'
        END,
        provider_class = CASE
            WHEN COALESCE(t.provider_class, t.itop_class) = 'Change' THEN 'RoutineChange'
            WHEN COALESCE(t.provider_class, t.itop_class) LIKE 'WorkflowReuseSmoke%' THEN 'Incident'
            WHEN COALESCE(t.provider_class, t.itop_class) = 'BrokerLeaseProof' THEN 'UserRequest'
            WHEN COALESCE(t.provider_class, t.itop_class) IN ('Incident','UserRequest','RoutineChange','NormalChange','EmergencyChange') THEN COALESCE(t.provider_class, t.itop_class)
            ELSE 'UserRequest'
        END,
        updated_at = NOW()
    FROM targets
    WHERE t.id = targets.id
    RETURNING t.id, t.title, t.itop_class, t.provider_class
)
SELECT COALESCE(json_agg(normalized ORDER BY id DESC), '[]'::json) FROM normalized;
"""
    if not apply:
        sql = """
SELECT COALESCE(json_agg(row_to_json(rows) ORDER BY id DESC), '[]'::json)
FROM (
    SELECT id, title, itop_class, provider_class
    FROM tickets
    WHERE itop_class NOT IN ('Incident','UserRequest','RoutineChange','NormalChange','EmergencyChange')
       OR COALESCE(provider_class, itop_class) NOT IN ('Incident','UserRequest','RoutineChange','NormalChange','EmergencyChange')
) rows;
"""
    cmd = [
        "docker", "compose", "exec", "-T", "db", "sh", "-c",
        'psql -t -A -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d soc_dashboard',
    ]
    result = subprocess.run(cmd, input=sql, cwd=repo_dir, text=True, capture_output=True, check=True)
    output = result.stdout.strip() or "[]"
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return {"raw": output}


def select_targets(tickets, since_id=None, include_historical_cicd=False):
    targets = []
    for ticket in tickets:
        title = ticket.get("title") or ""
        localish = ticket.get("provider") == "local" or ticket.get("provider_sync_status") in ("local_only", "unknown")
        recent = since_id is not None and ticket.get("id", 0) >= since_id
        bad_class = ticket.get("itop_class") not in VALID_CLASSES or (
            ticket.get("provider_class") and ticket.get("provider_class") not in VALID_CLASSES
        )
        historical_cicd = include_historical_cicd and (
            title.startswith("CI/CD security gate:") or title.startswith("Agentic CI/CD remediation demo")
        )
        if localish and (bad_class or recent or historical_cicd):
            targets.append(ticket)
    return targets


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://localhost:25480")
    parser.add_argument("--repo-dir", default=os.getcwd())
    parser.add_argument("--provider", default="itop")
    parser.add_argument("--since-id", type=int, default=None)
    parser.add_argument("--include-historical-cicd", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()

    normalized = normalize_db_classes(args.repo_dir, args.apply)
    tickets = request_json(args.base, "GET", "/api/tickets?limit=1000&sort_by=id&sort_dir=desc").get("tickets", [])
    targets = select_targets(tickets, args.since_id, args.include_historical_cicd)
    results = []
    for ticket in targets:
        if ticket.get("itop_class") not in VALID_CLASSES:
            continue
        if not args.apply:
            results.append({"id": ticket["id"], "action": "would_push", "class": ticket.get("itop_class")})
            continue
        push = request_json(args.base, "POST", f"/api/tickets/{ticket['id']}/push-provider", {"provider": args.provider})
        close = {"status": "skipped"}
        if ticket.get("status") in ("resolved", "closed", "closed/resolved", "implemented") and not push.get("error"):
            close = request_json(args.base, "POST", f"/api/tickets/{ticket['id']}/status", {
                "status": "resolved",
                "actor": "provider-sync-backfill",
                "reason": "Backfilled provider sync for previously local-only ticket after class normalization.",
                "close_provider": True,
            })
        results.append({"id": ticket["id"], "push": push, "close": close})
        time.sleep(0.1)

    print(json.dumps({
        "applied": bool(args.apply),
        "normalized": normalized,
        "target_count": len(targets),
        "results": results,
    }, indent=2))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"backfill failed: {exc}", file=sys.stderr)
        raise
