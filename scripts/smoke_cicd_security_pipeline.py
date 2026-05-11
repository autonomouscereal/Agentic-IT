#!/usr/bin/env python3
"""Smoke test the GitLab-default CI/CD security pipeline contract."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import urllib.request


BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:25480").rstrip("/")
ROOT = Path(__file__).resolve().parents[1]


def request(method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if body is not None else {},
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
    require("nuclei_optional" in template.get("template", ""), "GitLab template missing Nuclei job")

    with tempfile.TemporaryDirectory() as tmp:
        repo = Path(tmp)
        (repo / "app.py").write_text("print('safe demo')\n", encoding="utf-8")
        proc = subprocess.run(
            [
                sys.executable,
                str(ROOT / "scripts" / "run_cicd_security_pipeline.py"),
                "--provider", "gitlab",
                "--repo", str(repo),
                "--repo-ref", "gitlab/smoke/security-pipeline",
                "--branch", "main",
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
        "deployment_target": "production",
        "create_ticket": True,
        "require_change": True,
    })
    require(record.get("id"), f"CI/CD run not recorded: {record}")
    require(record.get("ticket_id"), "CI/CD run should create evidence ticket")
    require(record.get("change_id"), "production CI/CD run should create approval gate")

    runs = request("GET", "/api/cicd/runs?limit=10")
    require(any(row.get("id") == record.get("id") for row in runs.get("runs", [])), "recorded run missing from list")
    context = request("GET", f"/api/tickets/{record['ticket_id']}/context")
    require(context.get("change_requests"), "ticket context missing CI/CD change request")
    print(json.dumps({
        "ok": True,
        "run_id": record.get("id"),
        "ticket_id": record.get("ticket_id"),
        "change_id": record.get("change_id"),
        "provider": pipeline.get("provider"),
    }))


if __name__ == "__main__":
    main()
