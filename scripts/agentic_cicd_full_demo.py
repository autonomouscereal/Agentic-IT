#!/usr/bin/env python3
"""Run a full agentic CI/CD remediation demo against the dashboard.

The flow is intentionally end-to-end:
1. Create a vulnerable demo application.
2. Run the real Semgrep, Trivy, OWASP ZAP, and Nuclei security gate.
3. Record the failed gate on a dashboard ticket.
4. Spawn a local-model agent to request approval and remediate the app.
5. Auto-approve the lab change gate.
6. Rerun the security gate, record the fixed result, and create a local MR
   artifact from the agent's changes.

No secrets are required. If GitLab token material is available in the lab, this
script can be extended to push the generated branch; the default artifact is a
local git branch/patch so the demo remains portable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import shlex
import socket
import subprocess
import sys
import textwrap
import time
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_BASE = os.getenv("SOC_DASHBOARD_URL", "http://localhost:25480").rstrip("/")
DEFAULT_MODEL = os.getenv("AGENT_MODEL", "qwen/qwen3.6-27b")


def request(method: str, base: str, path: str, payload=None, timeout: int = 60):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed {exc.code}: {body}") from exc


def run(argv: list[str], cwd: Path | None = None, timeout: int = 1800, check: bool = False):
    proc = subprocess.run(
        argv,
        cwd=str(cwd) if cwd else None,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    if check and proc.returncode != 0:
        raise RuntimeError(
            f"Command failed {proc.returncode}: {' '.join(argv)}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc


def find_free_port(start: int = 28180, end: int = 28280) -> int:
    for port in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind(("0.0.0.0", port))
            except OSError:
                continue
            return port
    raise RuntimeError("No free demo port found")


def write_demo_app(repo: Path):
    repo.mkdir(parents=True, exist_ok=True)
    (repo / ".semgrep.yml").write_text(textwrap.dedent(
        """
        rules:
          - id: demo-subprocess-shell-true
            message: "Demo command injection: subprocess with shell=True must be removed."
            severity: ERROR
            languages: [python]
            pattern: subprocess.$FUNC(..., shell=True, ...)
          - id: demo-hardcoded-password
            message: "Demo hardcoded credential: move this value to environment or vault."
            severity: ERROR
            languages: [python]
            pattern: DEMO_PASSWORD = "..."
        """
    ).strip() + "\n", encoding="utf-8")
    (repo / "app.py").write_text(textwrap.dedent(
        """
        from http.server import BaseHTTPRequestHandler, HTTPServer
        from urllib.parse import parse_qs, urlparse
        import os
        import subprocess

        DEMO_PASSWORD = "demo-password"


        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                parsed = urlparse(self.path)
                qs = parse_qs(parsed.query)
                name = qs.get("name", ["world"])[0]
                if parsed.path == "/ping":
                    host = qs.get("host", ["127.0.0.1"])[0]
                    output = subprocess.check_output("echo " + host, shell=True, text=True)
                    body = f"<html><body><pre>{output}</pre></body></html>"
                else:
                    body = f"<html><body><h1>Hello {name}</h1></body></html>"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(body.encode("utf-8"))


        if __name__ == "__main__":
            port = int(os.environ.get("PORT", "28180"))
            HTTPServer(("0.0.0.0", port), Handler).serve_forever()
        """
    ).lstrip(), encoding="utf-8")
    (repo / "requirements.txt").write_text("requests==2.19.1\n", encoding="utf-8")
    (repo / "Dockerfile").write_text(textwrap.dedent(
        """
        FROM python:3.12-slim
        WORKDIR /app
        COPY . .
        EXPOSE 28180
        CMD ["python", "app.py"]
        """
    ).lstrip(), encoding="utf-8")
    (repo / "README.md").write_text(
        "# Agentic CI/CD Demo App\n\nIntentionally vulnerable app for scanner and agent remediation testing.\n",
        encoding="utf-8",
    )


def start_app(repo: Path, port: int):
    env = os.environ.copy()
    env["PORT"] = str(port)
    proc = subprocess.Popen(
        [sys.executable, "app.py"],
        cwd=str(repo),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.time() + 20
    url = f"http://127.0.0.1:{port}/?name=demo"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return proc
        except Exception:
            time.sleep(0.5)
    proc.terminate()
    raise RuntimeError(f"Demo app did not start on port {port}")


def stop_app(proc):
    if not proc:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def scan_repo(repo: Path, target_url: str, output_dir: Path, label: str) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    result_path = output_dir / "security-gate-result.json"
    proc = run([
        sys.executable,
        str(ROOT / "scripts" / "run_cicd_security_pipeline.py"),
        "--execution", "docker",
        "--provider", "gitlab",
        "--repo", str(repo),
        "--repo-ref", "gitlab/demo/agentic-cicd-app",
        "--branch", label,
        "--target-url", target_url,
        "--docker-network", os.getenv("CICD_DOCKER_NETWORK", "host"),
        "--output", str(result_path),
        "--safe-demo",
    ], timeout=3600)
    if not result_path.exists():
        raise RuntimeError(f"Scanner did not write {result_path}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}")
    return json.loads(result_path.read_text(encoding="utf-8"))


def post_scan(base: str, result: dict, ticket_id: int, deployment_target: str = "test") -> dict:
    payload = dict(result)
    payload.update({
        "ticket_id": ticket_id,
        "create_ticket": False,
        "require_change": deployment_target == "production",
        "deployment_target": deployment_target,
        "created_by": "agentic-cicd-full-demo",
    })
    return request("POST", base, "/api/cicd/runs", payload)


def add_note(base: str, ticket_id: int, body: str, author: str = "agentic-cicd-full-demo"):
    return request("POST", base, f"/api/tickets/{ticket_id}/notes", {
        "body": body,
        "author": author,
        "source": "demo",
        "visibility": "internal",
    })


def add_attachment(base: str, ticket_id: int, path: Path, metadata: dict):
    sha256 = hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None
    return request("POST", base, f"/api/tickets/{ticket_id}/attachments", {
        "filename": path.name,
        "content_type": "application/json",
        "storage_ref": str(path),
        "sha256": sha256,
        "size_bytes": path.stat().st_size if path.exists() else 0,
        "metadata": metadata,
    })


def complete_lab_deployment_change(base: str, final_record: dict, final_result: dict, compile_returncode: int, mr_artifact: dict) -> dict:
    change_id = final_record.get("change_id")
    if not change_id:
        return {"status": "not_applicable", "reason": "final run did not create a change"}

    request("POST", base, f"/api/changes/{change_id}/approve", {
        "approved_by": "agentic-cicd-demo-auto-approver",
    })
    evidence = textwrap.dedent(f"""
    Lab deployment approval completed after final CI/CD verification.
    Final gate status: {final_result.get('status')}
    Final severity counts: {final_result.get('severity_counts')}
    Compile return code: {compile_returncode}
    MR artifact: {mr_artifact}
    """).strip()
    return request("POST", base, f"/api/changes/{change_id}/complete", {
        "completed_by": "agentic-cicd-full-demo",
        "result": evidence,
    })


def init_git(repo: Path):
    run(["git", "init"], cwd=repo, check=True)
    run(["git", "config", "user.email", "agentic-demo@example.invalid"], cwd=repo, check=True)
    run(["git", "config", "user.name", "Agentic CI/CD Demo"], cwd=repo, check=True)
    run(["git", "add", "."], cwd=repo, check=True)
    run(["git", "commit", "-m", "initial vulnerable demo app"], cwd=repo, check=True)
    run(["git", "checkout", "-b", "agent/remediate-security-gate"], cwd=repo, check=True)


def make_agent_prompt(ticket_id: int, initial_result: dict) -> str:
    compact_findings = json.dumps(initial_result.get("findings", [])[:20], indent=2)
    safe_app = r'''from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse
from html import escape
import os


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        qs = parse_qs(parsed.query)
        name = escape(qs.get("name", ["world"])[0])
        if parsed.path == "/ping":
            host = qs.get("host", ["127.0.0.1"])[0]
            allowed = "".join(ch for ch in host if ch.isalnum() or ch in ".:-")
            body = f"<html><body><pre>{escape(allowed)}</pre></body></html>"
        else:
            body = f"<html><body><h1>Hello {name}</h1></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; object-src 'none'")
        self.end_headers()
        self.wfile.write(body.encode("utf-8"))


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "28180"))
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()
'''
    return f"""You are running a real CI/CD security remediation demo for ticket {ticket_id}.

Work only inside the `demo-app` directory in your current workspace. The initial scanner result is in
`initial-security-gate-result.json`; the important findings are:

{compact_findings}

Dashboard API base is http://localhost:8000.

Approval gate:
1. Read checkpoint.json directly.
2. Fetch ticket context with curl from /api/tickets/{ticket_id}/context.
3. Determine your current agent_id from the latest task in that context.
4. Check /api/changes?ticket_id={ticket_id}. If there is not already an approved change for "Remediate CI/CD security findings in test branch", request one with POST /api/changes/request. Include your agent_id, ticket_id {ticket_id}, risk_level "medium", target "demo-app", and action "Remediate CI/CD security findings in test branch".
5. If the change is not approved yet, add a ticket note saying you are waiting on the approval gate, update checkpoint.json with step "waiting-for-cicd-remediation-approval", status "done", progress_pct 45, and stop.

After an approved change exists:
1. Replace `demo-app/app.py` exactly with this safer implementation:

```python
{safe_app}
```

2. Replace `demo-app/requirements.txt` with:

```text
requests>=2.32.4
```

3. Replace `demo-app/Dockerfile` with:

```Dockerfile
FROM python:3.12-slim
RUN useradd --create-home appuser
WORKDIR /app
COPY . .
USER appuser
EXPOSE 28180
CMD ["python", "app.py"]
```

4. Run `python3 -m py_compile demo-app/app.py`.
5. Add a ticket note saying the local model remediated Semgrep command injection, hardcoded password, stale dependency, and container user issues.
6. Update checkpoint.json with step "agentic-cicd-remediation", status "done", progress_pct 100, output "agentic ci/cd remediation complete", and an ISO timestamp.
7. Reply exactly: agentic ci/cd remediation complete
"""


def wait_for_workdir(agent_id: int, timeout: int = 60) -> Path:
    host_workdir = ROOT / "agent_work" / str(agent_id)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if host_workdir.exists():
            make_agent_workdir_writable(agent_id, host_workdir)
            return host_workdir
        time.sleep(0.5)
    raise RuntimeError(f"Agent workdir did not appear: {host_workdir}")


def can_write_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except OSError:
        return False


def make_agent_workdir_writable(agent_id: int, host_workdir: Path | None = None):
    """Repair root-owned bind-mounted agent workdirs created by the API container.

    Fresh one-line installs usually run under a custom Docker Compose project
    name, so this must use the local compose file/service instead of a fixed
    container name.
    """
    host_workdir = host_workdir or ROOT / "agent_work" / str(agent_id)
    if can_write_dir(host_workdir):
        return

    uid = getattr(os, "getuid", lambda: 1000)()
    gid = getattr(os, "getgid", lambda: 1000)()
    container_path = f"/app/agent_work/{agent_id}"
    quoted_path = shlex.quote(container_path)
    repair_cmd = f"chown -R {uid}:{gid} {quoted_path} || chmod -R a+rwX {quoted_path}"
    proc = run([
        "docker", "compose", "exec", "-T", "api",
        "sh", "-lc", repair_cmd,
    ], cwd=ROOT, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(
            f"Unable to repair agent workdir permissions for {host_workdir}\n"
            f"STDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    if not can_write_dir(host_workdir):
        raise RuntimeError(f"Agent workdir is still not writable after repair: {host_workdir}")


def latest_tasks(base: str, ticket_id: int):
    return request("GET", base, f"/api/agents/tasks?ticket_id={ticket_id}").get("tasks", [])


def ensure_agent_workspace(agent_id: int, seed_repo: Path, initial_result_path: Path):
    host_workdir = ROOT / "agent_work" / str(agent_id)
    if not host_workdir.exists():
        return None
    make_agent_workdir_writable(agent_id, host_workdir)
    demo_app = host_workdir / "demo-app"
    if not demo_app.exists():
        shutil.copytree(seed_repo, demo_app, dirs_exist_ok=True)
        shutil.copy2(initial_result_path, host_workdir / "initial-security-gate-result.json")
        init_git(demo_app)
    return host_workdir


def approve_pending_changes(base: str, ticket_id: int) -> list[int]:
    changes = request("GET", base, f"/api/changes?ticket_id={ticket_id}").get("changes", [])
    approved = []
    for change in changes:
        if change.get("status") == "pending":
            result = request("POST", base, f"/api/changes/{change['id']}/approve", {
                "approved_by": "agentic-cicd-demo-auto-approver",
            }, timeout=120)
            approved.append(change["id"])
            replacement = (result.get("resume") or {}).get("agent_id")
            if replacement:
                print(json.dumps({"change_approved": change["id"], "replacement_agent_id": replacement}))
    return approved


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
                logs = request("GET", base, f"/api/agents/tasks/{task['id']}/logs?lines=120", timeout=120)
                content = logs.get("content", "")
                if "agentic ci/cd remediation complete" in content or task.get("progress_pct") == 100:
                    return task
        time.sleep(10)
    raise RuntimeError("Timed out waiting for agentic CI/CD remediation agent")


def wait_for_postmortem(base: str, ticket_id: int, agent_id: int, task_id: int, timeout: int = 900) -> dict:
    """Wait for a postmortem row, using the supervisor fallback if the model exits without one."""
    deadline = time.time() + timeout
    last_status = ""
    while time.time() < deadline:
        context = request("GET", base, f"/api/tickets/{ticket_id}/context", timeout=120)
        postmortems = context.get("postmortems", [])
        if postmortems:
            return {"status": "ready", "postmortem": postmortems[0]}

        tasks = context.get("tasks", [])
        task = next((item for item in tasks if item.get("id") == task_id), {})
        status = task.get("status", "missing")
        progress = task.get("progress_pct")
        rendered = f"{status}:{progress}"
        if rendered != last_status:
            print(json.dumps({"postmortem_task": task_id, "status": status, "progress_pct": progress}))
            last_status = rendered

        if status in ("completed", "failed", "stopped", "missing"):
            request("POST", base, "/api/agents/audits/run", {}, timeout=120)
            context = request("GET", base, f"/api/tickets/{ticket_id}/context", timeout=120)
            postmortems = context.get("postmortems", [])
            if postmortems:
                return {"status": "auditor_synthesized", "postmortem": postmortems[0]}
            synthesized = request("POST", base, f"/api/postmortems/synthesize/{ticket_id}", {
                "agent_id": agent_id,
                "task_id": task_id,
                "created_by": "agentic-cicd-full-demo",
                "reason": f"postmortem task {status} without artifact",
            }, timeout=120)
            if status not in ("completed", "failed", "stopped") and agent_id:
                request("POST", base, f"/api/agents/{agent_id}/stop", {
                    "reason": "postmortem artifact synthesized by supervisor",
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
        "created_by": "agentic-cicd-full-demo",
        "reason": "postmortem task timed out",
    }, timeout=120)
    if agent_id:
        request("POST", base, f"/api/agents/{agent_id}/stop", {
            "reason": "postmortem artifact synthesized after timeout",
        }, timeout=120)
    context = request("GET", base, f"/api/tickets/{ticket_id}/context", timeout=120)
    postmortems = context.get("postmortems", [])
    return {
        "status": synthesized.get("status", "timeout_synthesized"),
        "synthesis": synthesized,
        "postmortem": postmortems[0] if postmortems else None,
    }


def commit_agent_changes(repo: Path, ticket_id: int) -> dict:
    status = run(["git", "status", "--short"], cwd=repo, check=True).stdout
    if not status.strip():
        return {"status": "no_changes", "patch": ""}
    run(["git", "add", "."], cwd=repo, check=True)
    run(["git", "commit", "-m", f"remediate CI/CD security gate for ticket {ticket_id}"], cwd=repo, check=True)
    patch = run(["git", "format-patch", "-1", "--stdout"], cwd=repo, check=True).stdout
    patch_path = repo.parent / "agent-remediation.patch"
    patch_path.write_text(patch, encoding="utf-8")
    return {
        "status": "local_branch_ready",
        "branch": "agent/remediate-security-gate",
        "patch": str(patch_path),
        "summary": run(["git", "log", "--oneline", "--decorate", "-3"], cwd=repo, check=True).stdout,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Full agentic CI/CD remediation demo")
    parser.add_argument("--base", default=DEFAULT_BASE, help="Dashboard base URL")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Agent model ID")
    parser.add_argument("--host-ip", default=os.getenv("DEMO_HOST_IP", "127.0.0.1"), help="Host IP reachable from scanner containers")
    parser.add_argument("--workspace", default=str(ROOT / "demo_runs"), help="Directory for demo runs")
    parser.add_argument("--timeout", type=int, default=1800, help="Agent wait timeout seconds")
    args = parser.parse_args()

    run_id = int(time.time())
    work_root = Path(args.workspace).resolve() / f"agentic-cicd-{run_id}"
    seed_repo = work_root / "seed-app"
    work_root.mkdir(parents=True, exist_ok=True)
    write_demo_app(seed_repo)

    ticket = request("POST", args.base, "/api/tickets", {
        "title": f"Agentic CI/CD remediation demo {run_id}",
        "description": "Run scanner gate, spawn local-model remediation agent, approve change, rerun gate, and create MR artifact.",
        "ticket_class": "Change",
        "status": "new",
        "priority": "P2",
        "provider": "local",
        "sync_provider": False,
        "created_by": "agentic-cicd-full-demo",
    })
    ticket_id = ticket["id"]
    print(json.dumps({"ticket_id": ticket_id, "workspace": str(work_root)}))

    initial_port = find_free_port()
    initial_proc = None
    try:
        initial_proc = start_app(seed_repo, initial_port)
        initial_target = f"http://{args.host_ip}:{initial_port}"
        initial = scan_repo(seed_repo, initial_target, work_root / "initial-scan", "initial")
        initial_record = post_scan(args.base, initial, ticket_id)
        initial_result_path = work_root / "initial-scan" / "security-gate-result.json"
        add_attachment(args.base, ticket_id, initial_result_path, {"phase": "initial"})
        add_note(args.base, ticket_id, f"Initial scanner gate recorded as run {initial_record.get('id')} with status {initial.get('status')} and counts {initial.get('severity_counts')}.")
    finally:
        stop_app(initial_proc)

    prompt = make_agent_prompt(ticket_id, initial)
    spawn = request("POST", args.base, f"/api/tickets/{ticket_id}/assign-agent", {
        "model": args.model,
        "prompt": prompt,
    }, timeout=120)
    agent_id = spawn["agent_id"]
    task_id = spawn["task_id"]
    agent_workdir = wait_for_workdir(agent_id)
    agent_repo = agent_workdir / "demo-app"
    shutil.copytree(seed_repo, agent_repo, dirs_exist_ok=True)
    shutil.copy2(work_root / "initial-scan" / "security-gate-result.json", agent_workdir / "initial-security-gate-result.json")
    init_git(agent_repo)
    print(json.dumps({"agent_id": agent_id, "task_id": task_id, "agent_repo": str(agent_repo)}))

    completed_task = wait_for_agent(
        args.base,
        ticket_id,
        seed_repo,
        work_root / "initial-scan" / "security-gate-result.json",
        timeout=args.timeout,
    )
    final_agent_id = completed_task.get("agent_id")
    final_workdir = ROOT / "agent_work" / str(final_agent_id)
    final_repo = final_workdir / "demo-app"
    if not final_repo.exists():
        final_repo = agent_repo

    compile_check = run([sys.executable, "-m", "py_compile", str(final_repo / "app.py")], timeout=120)
    if compile_check.returncode != 0:
        raise RuntimeError(f"Agent app does not compile:\n{compile_check.stderr}")

    fixed_port = find_free_port(initial_port + 1)
    fixed_proc = None
    try:
        fixed_proc = start_app(final_repo, fixed_port)
        fixed_target = f"http://{args.host_ip}:{fixed_port}"
        final = scan_repo(final_repo, fixed_target, work_root / "final-scan", "agent-remediation")
        final_record = post_scan(args.base, final, ticket_id, deployment_target="production")
        final_path = work_root / "final-scan" / "security-gate-result.json"
        add_attachment(args.base, ticket_id, final_path, {"phase": "final"})
    finally:
        stop_app(fixed_proc)

    mr_artifact = commit_agent_changes(final_repo, ticket_id)
    if mr_artifact.get("patch"):
        add_attachment(args.base, ticket_id, Path(mr_artifact["patch"]), {"phase": "mr-artifact", "branch": mr_artifact.get("branch")})
    deployment_change = complete_lab_deployment_change(
        args.base,
        final_record,
        final,
        compile_check.returncode,
        mr_artifact,
    )

    add_note(args.base, ticket_id, textwrap.dedent(f"""
    Agentic CI/CD demo complete.
    Initial gate: {initial.get('status')} {initial.get('severity_counts')}
    Final gate: {final.get('status')} {final.get('severity_counts')}
    Completed task: {completed_task.get('id')} / agent {completed_task.get('agent_id')}
    MR artifact: {mr_artifact}
    Deployment change: {deployment_change}
    """).strip())

    postmortem = request("POST", args.base, f"/api/tickets/{ticket_id}/postmortem", {
        "model": args.model,
        "context": "Postmortem the CI/CD remediation demo. Focus on scanner findings, approval gate behavior, agent edits, final verification, and reusable workflow improvements.",
    }, timeout=120)
    postmortem_result = wait_for_postmortem(
        args.base,
        ticket_id,
        postmortem.get("agent_id"),
        postmortem.get("task_id"),
    )

    summary = {
        "ok": final.get("severity_counts", {}).get("high", 0) == 0 and final.get("severity_counts", {}).get("critical", 0) == 0,
        "ticket_id": ticket_id,
        "initial_run": initial_record,
        "final_run": final_record,
        "initial_status": initial.get("status"),
        "final_status": final.get("status"),
        "initial_counts": initial.get("severity_counts"),
        "final_counts": final.get("severity_counts"),
        "agent_id": final_agent_id,
        "task_id": completed_task.get("id"),
        "mr_artifact": mr_artifact,
        "deployment_change": deployment_change,
        "postmortem_spawn": postmortem,
        "postmortem_result": postmortem_result,
        "workspace": str(work_root),
    }
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
