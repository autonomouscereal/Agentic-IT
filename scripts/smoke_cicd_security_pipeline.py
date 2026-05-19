#!/usr/bin/env python3
"""Smoke test the GitLab-default CI/CD security pipeline contract."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.request


BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:25480").rstrip("/")
ROOT = Path(__file__).resolve().parents[1]
SERVICE_TOKEN = os.environ.get("DASHBOARD_SERVICE_TOKEN", "")


def request(method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={
            **({"Content-Type": "application/json"} if body is not None else {}),
            **({"X-Dashboard-Service-Token": SERVICE_TOKEN} if SERVICE_TOKEN else {}),
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def main():
    template = request("GET", "/api/cicd/gitlab/template")
    require(template.get("provider") == "gitlab", "GitLab should be default CI/CD provider")
    require("semgrep_sast" in template.get("template", ""), "GitLab template missing Semgrep job")
    require("trivy_fs" in template.get("template", ""), "GitLab template missing Trivy job")
    require("zap_baseline_optional" in template.get("template", ""), "GitLab template missing ZAP job")
    require("nuclei_optional" in template.get("template", ""), "GitLab template missing Nuclei job")

    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        (repo / "app.py").write_text("print('safe demo')\n", encoding="utf-8")
        artifacts = repo / "scan-output"
        artifacts.mkdir()
        (artifacts / "semgrep.json").write_text(json.dumps({"results": []}), encoding="utf-8")
        (artifacts / "trivy.json").write_text(json.dumps({"Results": []}), encoding="utf-8")
        (artifacts / "nuclei.jsonl").write_text("", encoding="utf-8")
        (artifacts / "zap.json").write_text(json.dumps({"site": []}), encoding="utf-8")
        proc = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "run_cicd_security_pipeline.py"),
                "--provider", "gitlab",
                "--repo", str(repo),
                "--repo-ref", "gitlab/smoke/security-pipeline",
                "--branch", "main",
                "--execution", "artifacts",
                "--artifact-dir", str(artifacts),
                "--safe-demo",
            ],
            text=True,
            capture_output=True,
            check=False,
        )
        require(proc.returncode == 0, proc.stderr or proc.stdout)
        pipeline = json.loads(proc.stdout)

    record = request("POST", "/api/cicd/runs", {
        **pipeline,
        "findings": [
            {
                "tool": "semgrep",
                "severity": "high",
                "rule_id": "python.lang.security.audit.demo-hardcoded-secret",
                "title": "Demo hardcoded secret",
                "message": "Credential-like value must be moved to the approved vault.",
                "path": "app.py",
                "start_line": 1,
            },
            *pipeline.get("findings", []),
        ],
        "tool_results": {
            **pipeline.get("tool_results", {}),
            "semgrep": {
                **(pipeline.get("tool_results", {}).get("semgrep") or {}),
                "status": "completed_with_findings",
                "artifact_url": "https://gitlab.example.invalid/group/project/-/jobs/1/artifacts/file/semgrep.json",
            },
        },
        "deployment_target": "production",
        "create_ticket": True,
        "require_change": True,
    })
    require(record.get("id"), f"CI/CD run not recorded: {record}")
    require(record.get("ticket_id"), "CI/CD run should create evidence ticket")
    require(record.get("change_id"), "production CI/CD run should create approval gate")

    runs = request("GET", "/api/cicd/runs?limit=10")
    require(any(row.get("id") == record.get("id") for row in runs.get("runs", [])), "recorded run missing from list")
    run = request("GET", f"/api/cicd/runs/{record['id']}")
    report_links = run.get("report_links") or []
    require(any(link.get("internal") and link.get("tool") == "semgrep" for link in report_links),
            "run detail missing dashboard Semgrep report link")
    require(any(link.get("requires_external_auth") and link.get("tool") == "semgrep" for link in report_links),
            "run detail should mark external Semgrep artifact as provider-authenticated")
    semgrep_report = request("GET", f"/api/cicd/runs/{record['id']}/reports/semgrep")
    require(semgrep_report.get("tool") == "semgrep", "Semgrep dashboard report returned wrong tool")
    require(semgrep_report.get("finding_count", 0) >= 1, "Semgrep dashboard report missing stored finding")
    require(semgrep_report.get("external_links"), "Semgrep dashboard report missing external artifact reference")
    context = request("GET", f"/api/tickets/{record['ticket_id']}/context")
    require(context.get("change_requests"), "ticket context missing CI/CD change request")
    print(json.dumps({
        "ok": True,
        "run_id": record.get("id"),
        "ticket_id": record.get("ticket_id"),
        "change_id": record.get("change_id"),
        "provider": pipeline.get("provider"),
        "semgrep_dashboard_report": semgrep_report.get("finding_count"),
    }))


if __name__ == "__main__":
    main()
