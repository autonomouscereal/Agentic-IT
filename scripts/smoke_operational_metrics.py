"""Smoke test operational metrics and dashboard clarity endpoints.

Validates:
- /api/dashboard/ops-metrics returns agent/SLA/gate/tool sections.
- agent list timing fields are nonnegative and server-derived.
- workflow rows expose review_state and linked run counters.
- tools response excludes ComfyUI and includes setup modules.
- CI/CD run detail groups findings by scanner and normalizes ZAP baseline code 2.
"""

import json
import sys
import time
import urllib.error
import urllib.request


BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:25480").rstrip("/")


def request(method, path, payload=None):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed: HTTP {exc.code}: {body}") from exc


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def nonnegative(value):
    return value is None or float(value) >= 0


def main():
    health = request("GET", "/health")
    require(health.get("status") == "ok", "dashboard health is not ok")

    metrics = request("GET", "/api/dashboard/ops-metrics")
    for key in ("agent_summary", "agent_by_task_type", "sla", "approval_gates", "workflows", "cicd", "tool_health"):
        require(key in metrics, f"ops metrics missing {key}")
    require(isinstance(metrics["agent_by_task_type"], list), "agent task metrics should be a list")

    agents = request("GET", "/api/agents?status=finished").get("agents", [])
    sample_agent = agents[0] if agents else {}
    timing_fields = ("idle_seconds", "running_seconds", "task_working_seconds", "gate_wait_seconds")
    negative_fields = [field for field in timing_fields if not nonnegative(sample_agent.get(field))]
    require(not negative_fields, f"negative agent timing fields: {negative_fields}")

    workflows = request("GET", "/api/workflows?limit=5").get("workflows", [])
    require(workflows, "expected at least one workflow")
    require(all("review_state" in row for row in workflows), "workflow list missing review_state")
    require(all("run_count" in row for row in workflows), "workflow list missing run counters")

    tools = request("GET", "/api/tools")
    tool_names = [str(row.get("name", "")).lower() for row in tools.get("tools", [])]
    module_names = [str(row.get("name", "")).lower() for row in tools.get("setup_modules", [])]
    require("comfyui" not in tool_names, "ComfyUI should not be shown on tools dashboard")
    require(module_names, "setup modules should be reflected on tools dashboard")

    stamp = int(time.time())
    payload = {
        "provider": "gitlab",
        "repo_ref": f"gitlab/smoke/metrics-zap-{stamp}",
        "branch": "main",
        "commit_sha": "demo",
        "target_url": "http://demo.local",
        "findings": [
            {"tool": "zap", "severity": "medium", "title": "Demo baseline warning"},
            {"tool": "semgrep", "severity": "low", "title": "Demo lint finding"},
        ],
        "tool_results": {
            "zap": {"status": "error", "returncode": 2, "artifact_url": "http://gitlab.local/artifacts/zap.html"},
            "semgrep": {"status": "completed", "finding_count": 1},
            "trivy": {"status": "completed", "finding_count": 0},
            "nuclei": {"status": "completed", "finding_count": 0},
        },
        "create_ticket": False,
        "require_change": False,
        "created_by": "codex-operational-metrics-smoke",
    }
    record = request("POST", "/api/cicd/runs", payload)
    run = request("GET", f"/api/cicd/runs/{record['id']}")
    tool_results = run.get("tool_results") or {}
    scanner_summary = run.get("scanner_summary") or {}
    require(tool_results.get("owasp_zap", {}).get("status") == "completed_with_findings",
            "ZAP baseline exit code 2 was not normalized")
    require(set(scanner_summary.keys()) == {"semgrep", "trivy", "owasp_zap", "nuclei"},
            f"scanner summary keys wrong: {sorted(scanner_summary.keys())}")
    require(scanner_summary["owasp_zap"]["finding_count"] == 1, "ZAP finding count should be grouped under OWASP ZAP")

    print(json.dumps({
        "status": "passed",
        "base": BASE,
        "ops_task_types": len(metrics["agent_by_task_type"]),
        "workflow_sample": workflows[0].get("review_state"),
        "cicd_run_id": record["id"],
        "zap_status": tool_results["owasp_zap"]["status"],
        "setup_modules": len(tools.get("setup_modules", [])),
        "agent_timing_sample": {field: sample_agent.get(field) for field in timing_fields},
    }, indent=2))


if __name__ == "__main__":
    main()
