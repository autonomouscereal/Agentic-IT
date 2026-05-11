#!/usr/bin/env python3
"""Smoke test the platform setup manifest, plan API, setup ticket, and installer dry run."""
import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://localhost:25480"
ROOT = Path(__file__).resolve().parents[1]


def request(method, path, body=None):
    data = None
    headers = {}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{BASE}{path}", data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        print(exc.read().decode("utf-8"), file=sys.stderr)
        raise


def assert_true(value, message):
    if not value:
        raise AssertionError(message)


def main():
    health = request("GET", "/health")
    assert_true(health.get("status") == "ok", "health endpoint failed")

    manifest = request("GET", "/api/setup/manifest")
    module_ids = {module["id"] for module in manifest.get("modules", [])}
    for required in ("soc-dashboard", "local-ticketing", "itop", "wazuh", "mailcow", "gitlab"):
        assert_true(required in module_ids, f"missing module {required}")
    assert_true("comfyui" in {m["id"] for m in manifest.get("excluded_modules", [])}, "comfyui must be excluded")

    plan = request("POST", "/api/setup/plan", {
        "profile": "soc",
        "existing_tools": ["servicenow", "crowdstrike", "splunk", "mail-gateway", "itop"],
        "include": ["gitlab"],
        "exclude": ["mailcow"],
        "deploy_missing": True,
    })
    assert_true(plan["summary"]["total"] > 5, "setup plan too small")
    assert_true(any(step["module_id"] == "itop" and step["status"] == "integrate_existing" for step in plan["steps"]), "existing ITSM integration not reflected")
    assert_true(not any(step["module_id"] == "mailcow" for step in plan["steps"]), "excluded module still present")

    ticket = request("POST", "/api/setup/ticket", {
        "profile": "minimal",
        "existing_tools": ["servicenow"],
        "deploy_missing": False,
        "ai_base_url": "http://127.0.0.1:4001",
        "model": "qwen/qwen3.6-27b",
        "notes": "Smoke test: integrate an existing ITSM provider and do not deploy optional reference modules.",
        "spawn_agent": False,
    })
    assert_true(ticket.get("ticket", {}).get("id"), "setup ticket was not created")

    dry_run = subprocess.run(
        [sys.executable, str(ROOT / "installer" / "bootstrap.py"), "--dry-run", "--no-start", "--profile", "minimal", "--target", str(ROOT / ".tmp-install-smoke")],
        cwd=str(ROOT),
        text=True,
        capture_output=True,
        check=True,
    )
    assert_true('"status": "dry_run"' in dry_run.stdout, "installer dry-run did not report dry_run")

    print(json.dumps({
        "status": "ok",
        "manifest_modules": len(module_ids),
        "plan_steps": plan["summary"]["total"],
        "setup_ticket_id": ticket["ticket"]["id"],
    }, indent=2))


if __name__ == "__main__":
    main()
