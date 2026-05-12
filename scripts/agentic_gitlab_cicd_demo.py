#!/usr/bin/env python3
"""Run the GitLab-backed agentic CI/CD remediation proof.

This is the live-provider companion to ``agentic_cicd_full_demo.py``. It proves
that GitLab Runner can execute Semgrep, Trivy, OWASP ZAP, and Nuclei jobs,
post the canonical gate result to the dashboard, let a local-model agent
remediate the failed gate behind an approval, and publish the agent's fix as a
GitLab branch and merge request.

GitLab credentials stay in the controller process. The agent receives scanner
evidence and source files, but not the GitLab PAT.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import textwrap
import time
import urllib.error
import urllib.parse
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from agentic_cicd_full_demo import (  # noqa: E402
    add_attachment,
    add_note,
    approve_pending_changes,
    ensure_agent_workspace,
    init_git,
    latest_tasks,
    make_agent_prompt,
    request as dashboard_request,
    run,
    wait_for_workdir,
    write_demo_app,
)


DEFAULT_DASHBOARD = os.getenv("SOC_DASHBOARD_URL", "http://localhost:25480").rstrip("/")
DEFAULT_RUNNER_DASHBOARD = os.getenv("SOC_RUNNER_DASHBOARD_URL", "http://192.168.50.222:25480").rstrip("/")
DEFAULT_GITLAB = os.getenv("GITLAB_URL", "http://localhost").rstrip("/")
DEFAULT_MODEL = os.getenv("AGENT_MODEL", "qwen/qwen3.6-27b")
DEFAULT_TOKEN_FILE = os.getenv("GITLAB_PAT_FILE", "/home/cereal/gitlab/.gitlab-token")


def load_gitlab_token(token_file: str) -> str:
    env_token = os.getenv("GITLAB_PAT", "").strip()
    if env_token:
        return env_token

    if token_file and Path(token_file).exists():
        token = Path(token_file).read_text(encoding="utf-8").strip()
        if token:
            return token

    vault_key = os.getenv("GITLAB_PAT_VAULT_KEY", "gitlab_manager_pat")
    candidates = [
        os.getenv("CREDMAN_PATH", ""),
        "/home/cereal/.claude/skills/server-manager/credman.py",
        "/home/cereal/.agents/skills/server-manager/credman.py",
        "C:/Users/cereal/.claude/skills/server-manager/credman.py",
        "C:/Users/cereal/.agents/skills/server-manager/credman.py",
    ]
    for credman in [path for path in candidates if path]:
        if not Path(credman).exists():
            continue
        result = subprocess.run(
            [sys.executable, credman, "get", vault_key],
            capture_output=True,
            text=True,
            check=False,
        )
        token = result.stdout.strip()
        if result.returncode == 0 and token:
            return token

    return ""


def gitlab_request(method: str, base: str, token: str, path: str, payload=None, timeout: int = 120):
    data = None
    headers = {"PRIVATE-TOKEN": token}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base + "/api/v4" + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"GitLab {method} {path} failed {exc.code}: {body}") from exc


def project_path(project_id: int) -> str:
    return urllib.parse.quote_plus(str(project_id))


def branch_path(branch: str) -> str:
    return urllib.parse.quote(branch, safe="")


def write_gitlab_ci(repo: Path):
    (repo / "ci").mkdir(parents=True, exist_ok=True)
    (repo / ".gitlab-ci.yml").write_text(textwrap.dedent(
        """
        stages:
          - test
          - security
          - record

        variables:
          SOC_DASHBOARD_URL: "http://192.168.50.222:25480"
          NUCLEI_TARGET_URL: "http://gitlab"

        unit_tests:
          stage: test
          image: python:3.12-slim
          script:
            - python -m py_compile app.py

        semgrep_sast:
          stage: security
          image:
            name: semgrep/semgrep:latest
            entrypoint: [""]
          script:
            - semgrep --config .semgrep.yml --json --output semgrep.json . || true
            - test -f semgrep.json || printf '{"results":[]}' > semgrep.json
          artifacts:
            when: always
            paths: [semgrep.json]

        trivy_fs:
          stage: security
          image:
            name: aquasec/trivy:latest
            entrypoint: [""]
          script:
            - trivy fs --format json --output trivy.json . || true
            - test -f trivy.json || printf '{"Results":[]}' > trivy.json
          artifacts:
            when: always
            paths: [trivy.json]

        zap_dast:
          stage: security
          image:
            name: ghcr.io/zaproxy/zaproxy:stable
            entrypoint: [""]
          script:
            - mkdir -p /zap/wrk
            - PORT=8080 python3 app.py &
            - sleep 5
            - zap-baseline.py -t http://127.0.0.1:8080 -J /zap/wrk/zap.json -I || true
            - cp /zap/wrk/zap.json zap.json || printf '{"site":[]}' > zap.json
          artifacts:
            when: always
            paths: [zap.json]

        nuclei_exposure:
          stage: security
          image:
            name: projectdiscovery/nuclei:latest
            entrypoint: [""]
          script:
            - nuclei -u "$NUCLEI_TARGET_URL" -severity critical,high,medium -jsonl -o nuclei.jsonl -retries 0 -timeout 5 -silent || true
            - test -f nuclei.jsonl || touch nuclei.jsonl
          artifacts:
            when: always
            paths: [nuclei.jsonl]

        dashboard_record:
          stage: record
          image: python:3.12-slim
          needs:
            - job: semgrep_sast
              artifacts: true
            - job: trivy_fs
              artifacts: true
            - job: zap_dast
              artifacts: true
            - job: nuclei_exposure
              artifacts: true
          script:
            - python ci/normalize_and_post.py
          artifacts:
            when: always
            paths: [cicd-security-result.json]
        """
    ).lstrip(), encoding="utf-8")
    (repo / "ci" / "normalize_and_post.py").write_text(NORMALIZER, encoding="utf-8")


NORMALIZER = r'''#!/usr/bin/env python3
import json
import os
import urllib.request


def read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except Exception:
        return {}


def semgrep_findings():
    findings = []
    for item in read_json("semgrep.json").get("results", []):
        extra = item.get("extra", {})
        sev = str(extra.get("severity") or "unknown").lower()
        sev = {"error": "high", "warning": "medium", "info": "info"}.get(sev, sev)
        findings.append({
            "tool": "semgrep",
            "severity": sev,
            "rule_id": item.get("check_id"),
            "title": extra.get("message") or item.get("check_id"),
            "path": item.get("path"),
            "line": (item.get("start") or {}).get("line"),
        })
    return findings


def trivy_findings():
    findings = []
    for target in read_json("trivy.json").get("Results", []):
        for vuln in target.get("Vulnerabilities") or []:
            findings.append({
                "tool": "trivy",
                "severity": str(vuln.get("Severity", "unknown")).lower(),
                "rule_id": vuln.get("VulnerabilityID"),
                "title": vuln.get("Title") or vuln.get("PkgName"),
                "path": target.get("Target"),
                "package": vuln.get("PkgName"),
                "installed_version": vuln.get("InstalledVersion"),
                "fixed_version": vuln.get("FixedVersion"),
            })
        for misconfig in target.get("Misconfigurations") or []:
            findings.append({
                "tool": "trivy",
                "severity": str(misconfig.get("Severity", "unknown")).lower(),
                "rule_id": misconfig.get("ID"),
                "title": misconfig.get("Title"),
                "path": target.get("Target"),
            })
    return findings


def zap_findings():
    findings = []
    for site in read_json("zap.json").get("site", []):
        for alert in site.get("alerts", []):
            risk = str(alert.get("riskdesc", "unknown")).split()[0].lower()
            findings.append({
                "tool": "owasp-zap",
                "severity": {"informational": "info"}.get(risk, risk),
                "rule_id": alert.get("pluginid"),
                "title": alert.get("name"),
                "url": ((alert.get("instances") or [{}])[0]).get("uri"),
            })
    return findings


def nuclei_findings():
    findings = []
    try:
        lines = open("nuclei.jsonl", "r", encoding="utf-8", errors="replace").read().splitlines()
    except OSError:
        return findings
    for line in lines:
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        info = item.get("info", {})
        findings.append({
            "tool": "nuclei",
            "severity": str(info.get("severity", "unknown")).lower(),
            "rule_id": item.get("template-id"),
            "title": info.get("name") or item.get("template-id"),
            "url": item.get("matched-at") or item.get("host"),
        })
    return findings


def counts(findings):
    out = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0, "unknown": 0}
    for finding in findings:
        sev = str(finding.get("severity", "unknown")).lower()
        out[sev if sev in out else "unknown"] += 1
    return out


findings = semgrep_findings() + trivy_findings() + zap_findings() + nuclei_findings()
severity_counts = counts(findings)
status = "failed" if severity_counts["critical"] or severity_counts["high"] else "passed"
deployment_target = "production" if os.getenv("CI_COMMIT_REF_NAME", "").startswith("agent/remediate") else "test"
payload = {
    "provider": "gitlab",
    "repo_ref": os.getenv("CI_PROJECT_PATH"),
    "branch": os.getenv("CI_COMMIT_REF_NAME"),
    "commit_sha": os.getenv("CI_COMMIT_SHA"),
    "target_url": "job-local-app-and-" + os.getenv("NUCLEI_TARGET_URL", ""),
    "execution": "gitlab-runner",
    "status": status,
    "summary": f"GitLab Runner security gate {status}: {len(findings)} findings across Semgrep, Trivy, OWASP ZAP, and Nuclei.",
    "findings": findings,
    "severity_counts": severity_counts,
    "tool_results": {
        "semgrep": {"status": "completed" if os.path.exists("semgrep.json") else "error"},
        "trivy": {"status": "completed" if os.path.exists("trivy.json") else "error"},
        "owasp_zap": {"status": "completed" if os.path.exists("zap.json") else "error"},
        "nuclei": {"status": "completed" if os.path.exists("nuclei.jsonl") else "error"},
    },
    "create_ticket": not bool(os.getenv("DASHBOARD_TICKET_ID")),
    "ticket_id": int(os.getenv("DASHBOARD_TICKET_ID")) if os.getenv("DASHBOARD_TICKET_ID") else None,
    "require_change": deployment_target == "production",
    "deployment_target": deployment_target,
    "created_by": "gitlab-runner-security-gate",
}
with open("cicd-security-result.json", "w", encoding="utf-8") as handle:
    json.dump(payload, handle, indent=2, sort_keys=True)

req = urllib.request.Request(
    os.environ["SOC_DASHBOARD_URL"].rstrip("/") + "/api/cicd/runs",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req, timeout=60) as response:
    print(response.read().decode("utf-8", errors="replace"))
raise SystemExit(1 if status == "failed" else 0)
'''


def create_gitlab_project(base: str, token: str, name: str, path: str) -> dict:
    return gitlab_request("POST", base, token, "/projects", {
        "name": name,
        "path": path,
        "visibility": "internal",
        "initialize_with_readme": True,
    })


def commit_files(base: str, token: str, project_id: int, branch: str, message: str, files: dict[str, str], start_branch: str | None = None):
    actions = []
    for file_path, content in files.items():
        actions.append({"action": "update", "file_path": file_path, "content": content})
    payload = {"branch": branch, "commit_message": message, "actions": actions}
    if start_branch:
        payload["start_branch"] = start_branch
    try:
        return gitlab_request("POST", base, token, f"/projects/{project_path(project_id)}/repository/commits", payload)
    except RuntimeError as exc:
        if "A file with this name doesn't exist" not in str(exc):
            raise
    for action in actions:
        action["action"] = "create"
    return gitlab_request("POST", base, token, f"/projects/{project_path(project_id)}/repository/commits", payload)


def create_or_update_variable(base: str, token: str, project_id: int, key: str, value: str):
    path = f"/projects/{project_path(project_id)}/variables/{urllib.parse.quote(key, safe='')}"
    try:
        return gitlab_request("PUT", base, token, path, {"value": value, "masked": False, "protected": False})
    except RuntimeError:
        return gitlab_request("POST", base, token, f"/projects/{project_path(project_id)}/variables", {
            "key": key,
            "value": value,
            "masked": False,
            "protected": False,
        })


def attach_first_runner(base: str, token: str, project_id: int):
    """Attach the reference project runner to a newly-created demo project.

    The lab GitLab runner is registered as a project runner rather than an
    instance runner, so new throwaway projects will sit pending until explicitly
    assigned.
    """
    runners = gitlab_request("GET", base, token, "/runners/all")
    if not runners:
        raise RuntimeError("No GitLab runners are registered")
    runner_id = runners[0]["id"]
    try:
        return gitlab_request("POST", base, token, f"/projects/{project_path(project_id)}/runners", {
            "runner_id": runner_id,
        })
    except RuntimeError as exc:
        if "already exists" not in str(exc).lower() and "already" not in str(exc).lower():
            raise
        return {"id": runner_id, "status": "already_attached"}


def wait_pipeline(base: str, token: str, project_id: int, ref: str, timeout: int = 2400) -> dict:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        pipelines = gitlab_request(
            "GET", base, token,
            f"/projects/{project_path(project_id)}/pipelines?ref={urllib.parse.quote(ref, safe='')}&per_page=1"
        )
        if pipelines:
            pipeline = pipelines[0]
            status = pipeline.get("status")
            if status != last:
                print(json.dumps({"pipeline": pipeline.get("id"), "ref": ref, "status": status}))
                last = status
            if status in ("success", "failed", "canceled", "skipped"):
                jobs = gitlab_request("GET", base, token, f"/projects/{project_path(project_id)}/pipelines/{pipeline['id']}/jobs?per_page=100")
                pipeline["jobs"] = [{"name": j.get("name"), "status": j.get("status"), "id": j.get("id")} for j in jobs]
                return pipeline
        time.sleep(10)
    raise RuntimeError(f"Timed out waiting for GitLab pipeline on {ref}")


def latest_dashboard_run(base: str, repo_ref: str, branch: str, timeout: int = 180) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        runs = dashboard_request("GET", base, "/api/cicd/runs?limit=200").get("runs", [])
        for run_row in runs:
            if run_row.get("repo_ref") == repo_ref and run_row.get("branch") == branch:
                findings = run_row.get("findings")
                tool_results = run_row.get("tool_results")
                if isinstance(findings, str):
                    run_row["findings"] = json.loads(findings)
                if isinstance(tool_results, str):
                    run_row["tool_results"] = json.loads(tool_results)
                return run_row
        time.sleep(5)
    raise RuntimeError(f"Dashboard run not found for {repo_ref}@{branch}")


def wait_for_agent(base: str, ticket_id: int, seed_repo: Path, initial_result_path: Path, timeout: int = 1800):
    deadline = time.time() + timeout
    seen = set()
    last_status = ""
    while time.time() < deadline:
        approve_pending_changes(base, ticket_id)
        tasks = latest_tasks(base, ticket_id)
        for task in tasks:
            if task.get("agent_id"):
                ensure_agent_workspace(int(task["agent_id"]), seed_repo, initial_result_path)
        summary = [(t.get("id"), t.get("agent_id"), t.get("status"), t.get("progress_pct")) for t in tasks[:5]]
        rendered = json.dumps(summary)
        if rendered != last_status:
            print(json.dumps({"agent_tasks": summary}))
            last_status = rendered
        for task in tasks:
            if task.get("status") in ("completed", "failed", "stopped") and task.get("id") not in seen:
                seen.add(task.get("id"))
                logs = dashboard_request("GET", base, f"/api/agents/tasks/{task['id']}/logs?lines=160", timeout=120)
                content = logs.get("content", "")
                if "agentic ci/cd remediation complete" in content or task.get("progress_pct") == 100:
                    return task
        time.sleep(10)
    raise RuntimeError("Timed out waiting for GitLab CI/CD remediation agent")


def files_for_commit(repo: Path) -> dict[str, str]:
    return {
        "app.py": (repo / "app.py").read_text(encoding="utf-8"),
        "requirements.txt": (repo / "requirements.txt").read_text(encoding="utf-8"),
        "Dockerfile": (repo / "Dockerfile").read_text(encoding="utf-8"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="GitLab Runner + dashboard + local-model CI/CD remediation demo")
    parser.add_argument("--dashboard", default=DEFAULT_DASHBOARD)
    parser.add_argument("--runner-dashboard", default=DEFAULT_RUNNER_DASHBOARD,
                        help="Dashboard URL reachable from GitLab job containers")
    parser.add_argument("--gitlab", default=DEFAULT_GITLAB)
    parser.add_argument("--gitlab-token-file", default=DEFAULT_TOKEN_FILE)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--workspace", default=str(ROOT / "demo_runs"))
    parser.add_argument("--timeout", type=int, default=2400)
    args = parser.parse_args()

    token = load_gitlab_token(args.gitlab_token_file)
    if not token:
        raise RuntimeError("No GitLab PAT found. Set GITLAB_PAT, GITLAB_PAT_FILE, or CREDMAN_PATH/GITLAB_PAT_VAULT_KEY.")

    run_id = int(time.time())
    work_root = Path(args.workspace).resolve() / f"gitlab-agentic-cicd-{run_id}"
    seed_repo = work_root / "seed-app"
    work_root.mkdir(parents=True, exist_ok=True)
    write_demo_app(seed_repo)
    write_gitlab_ci(seed_repo)

    project = create_gitlab_project(args.gitlab, token, f"Agentic CI CD Demo {run_id}", f"agentic-cicd-demo-{run_id}")
    project_id = project["id"]
    repo_ref = project["path_with_namespace"]
    print(json.dumps({"project_id": project_id, "repo_ref": repo_ref, "web_url": project.get("web_url")}))

    attach_first_runner(args.gitlab, token, project_id)
    create_or_update_variable(args.gitlab, token, project_id, "SOC_DASHBOARD_URL", args.runner_dashboard)
    create_or_update_variable(args.gitlab, token, project_id, "NUCLEI_TARGET_URL", "http://gitlab")

    initial_files = {str(path.relative_to(seed_repo)).replace("\\", "/"): path.read_text(encoding="utf-8")
                     for path in seed_repo.rglob("*")
                     if path.is_file() and str(path.relative_to(seed_repo)).replace("\\", "/") != "README.md"}
    commit_files(args.gitlab, token, project_id, "main", "add vulnerable app and security gate", initial_files)
    initial_pipeline = wait_pipeline(args.gitlab, token, project_id, "main", args.timeout)
    initial_run = latest_dashboard_run(args.dashboard, repo_ref, "main")
    ticket_id = initial_run.get("ticket_id")
    if not ticket_id:
        raise RuntimeError(f"Initial dashboard run did not create a ticket: {initial_run}")

    create_or_update_variable(args.gitlab, token, project_id, "DASHBOARD_TICKET_ID", str(ticket_id))
    initial_result_path = work_root / "initial-gitlab-security-gate-result.json"
    initial_result_path.write_text(json.dumps(initial_run, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    add_attachment(args.dashboard, ticket_id, initial_result_path, {"phase": "gitlab-initial", "project": repo_ref})
    add_note(args.dashboard, ticket_id, f"GitLab initial pipeline {initial_pipeline.get('id')} finished {initial_pipeline.get('status')} with dashboard run {initial_run.get('id')}. Jobs: {initial_pipeline.get('jobs')}.")

    prompt = make_agent_prompt(ticket_id, initial_run)
    spawn = dashboard_request("POST", args.dashboard, f"/api/tickets/{ticket_id}/assign-agent", {
        "model": args.model,
        "prompt": prompt,
    }, timeout=120)
    agent_id = spawn["agent_id"]
    wait_for_workdir(agent_id)
    agent_workdir = ROOT / "agent_work" / str(agent_id)
    agent_repo = agent_workdir / "demo-app"
    shutil.copytree(seed_repo, agent_repo, dirs_exist_ok=True)
    shutil.copy2(initial_result_path, agent_workdir / "initial-security-gate-result.json")
    init_git(agent_repo)
    print(json.dumps({"agent_id": agent_id, "task_id": spawn["task_id"], "agent_repo": str(agent_repo)}))

    completed_task = wait_for_agent(args.dashboard, ticket_id, seed_repo, initial_result_path, timeout=args.timeout)
    final_agent_id = completed_task.get("agent_id")
    final_repo = ROOT / "agent_work" / str(final_agent_id) / "demo-app"
    if not final_repo.exists():
        final_repo = agent_repo
    compile_check = run([sys.executable, "-m", "py_compile", str(final_repo / "app.py")], timeout=120)
    if compile_check.returncode != 0:
        raise RuntimeError(f"Agent app does not compile:\n{compile_check.stderr}")

    branch = "agent/remediate-security-gate"
    commit = commit_files(
        args.gitlab,
        token,
        project_id,
        branch,
        f"remediate CI/CD security gate for dashboard ticket {ticket_id}",
        files_for_commit(final_repo),
        start_branch="main",
    )
    merge_request = gitlab_request("POST", args.gitlab, token, f"/projects/{project_path(project_id)}/merge_requests", {
        "source_branch": branch,
        "target_branch": "main",
        "title": f"Remediate security gate for dashboard ticket {ticket_id}",
        "description": f"Local-model agent remediated scanner findings for dashboard ticket {ticket_id}. Controller created this MR without exposing the GitLab PAT to the agent.",
        "remove_source_branch": False,
        "squash": False,
    })
    add_note(args.dashboard, ticket_id, f"Created GitLab remediation branch `{branch}` at commit {commit.get('id')} and MR !{merge_request.get('iid')} ({merge_request.get('web_url')}).")

    final_pipeline = wait_pipeline(args.gitlab, token, project_id, branch, args.timeout)
    final_run = latest_dashboard_run(args.dashboard, repo_ref, branch)
    final_path = work_root / "final-gitlab-security-gate-result.json"
    final_path.write_text(json.dumps(final_run, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    add_attachment(args.dashboard, ticket_id, final_path, {"phase": "gitlab-final", "project": repo_ref, "mr": merge_request.get("web_url")})

    if final_run.get("change_id"):
        approval = dashboard_request("POST", args.dashboard, f"/api/changes/{final_run['change_id']}/approve", {
            "approved_by": "gitlab-cicd-demo-auto-approver",
        }, timeout=120)
        dashboard_request("POST", args.dashboard, f"/api/changes/{final_run['change_id']}/complete", {
            "result": f"GitLab MR !{merge_request.get('iid')} passed the security gate; deployment approval simulated for lab demo. Approval response: {approval}",
        }, timeout=120)

    postmortem = dashboard_request("POST", args.dashboard, f"/api/tickets/{ticket_id}/postmortem", {
        "model": args.model,
        "context": "Postmortem the GitLab-backed CI/CD remediation demo. Include runner behavior, scanner artifacts, approval gates, MR creation, and final security gate outcome.",
    }, timeout=120)

    high = (final_run.get("findings") or [])
    final_counts = final_run.get("severity_counts") or {}
    summary = {
        "ok": final_counts.get("critical", 0) == 0 and final_counts.get("high", 0) == 0,
        "ticket_id": ticket_id,
        "project_id": project_id,
        "repo_ref": repo_ref,
        "project_url": project.get("web_url"),
        "merge_request": merge_request.get("web_url"),
        "initial_pipeline": initial_pipeline,
        "final_pipeline": final_pipeline,
        "initial_run_id": initial_run.get("id"),
        "final_run_id": final_run.get("id"),
        "initial_status": initial_run.get("status"),
        "final_status": final_run.get("status"),
        "final_finding_count": len(high),
        "final_counts": final_counts,
        "agent_id": final_agent_id,
        "task_id": completed_task.get("id"),
        "postmortem_spawn": postmortem,
        "workspace": str(work_root),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
