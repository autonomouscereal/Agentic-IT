#!/usr/bin/env python3
"""Run a modular CI/CD security gate locally or inside a provider runner.

The default provider is GitLab because the reference platform ships a deployable
GitLab CE + Runner integration. The runner stays provider agnostic by emitting a
canonical JSON result that can be posted to `/api/cicd/runs` from GitLab, GitHub,
Jenkins, Azure DevOps, or a local agent task.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time


SEVERITY_ORDER = {"critical": 5, "high": 4, "medium": 3, "low": 2, "info": 1}


def run_command(name: str, argv: list[str], cwd: Path | None = None, timeout: int = 900) -> dict:
    started = time.time()
    exe = shutil.which(argv[0])
    if not exe:
        return {"status": "skipped", "reason": f"{argv[0]} not installed", "duration_seconds": 0}
    try:
        proc = subprocess.run(
            [exe, *argv[1:]],
            cwd=str(cwd) if cwd else None,
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        return {
            "status": "completed" if proc.returncode in (0, 1) else "error",
            "returncode": proc.returncode,
            "stdout": proc.stdout[-20000:],
            "stderr": proc.stderr[-20000:],
            "duration_seconds": round(time.time() - started, 2),
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "status": "error",
            "reason": f"{name} timed out after {timeout}s",
            "stdout": (exc.stdout or "")[-20000:] if isinstance(exc.stdout, str) else "",
            "stderr": (exc.stderr or "")[-20000:] if isinstance(exc.stderr, str) else "",
            "duration_seconds": round(time.time() - started, 2),
        }


def load_json_from_stdout(result: dict):
    output = result.get("stdout") or ""
    if not output.strip():
        return None
    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return None


def normalize_semgrep(result: dict) -> list[dict]:
    data = load_json_from_stdout(result) or {}
    findings = []
    for item in data.get("results", []):
        extra = item.get("extra", {})
        metadata = extra.get("metadata", {})
        severity = str(extra.get("severity") or metadata.get("impact") or "unknown").lower()
        findings.append({
            "tool": "semgrep",
            "severity": severity,
            "rule_id": item.get("check_id"),
            "title": extra.get("message") or item.get("check_id"),
            "path": item.get("path"),
            "line": item.get("start", {}).get("line"),
        })
    return findings


def normalize_trivy(result: dict) -> list[dict]:
    data = load_json_from_stdout(result) or {}
    findings = []
    for target in data.get("Results", []):
        for vuln in target.get("Vulnerabilities", []) or []:
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
        for misconfig in target.get("Misconfigurations", []) or []:
            findings.append({
                "tool": "trivy",
                "severity": str(misconfig.get("Severity", "unknown")).lower(),
                "rule_id": misconfig.get("ID"),
                "title": misconfig.get("Title"),
                "path": target.get("Target"),
            })
    return findings


def normalize_nuclei(result: dict) -> list[dict]:
    findings = []
    for line in (result.get("stdout") or "").splitlines():
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


def normalize_zap(result: dict, output_file: Path) -> list[dict]:
    if not output_file.exists():
        return []
    try:
        data = json.loads(output_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    findings = []
    for site in data.get("site", []):
        for alert in site.get("alerts", []):
            risk = str(alert.get("riskdesc", "unknown")).split()[0].lower()
            findings.append({
                "tool": "owasp-zap",
                "severity": {"high": "high", "medium": "medium", "low": "low", "informational": "info"}.get(risk, risk),
                "rule_id": alert.get("pluginid"),
                "title": alert.get("name"),
                "url": (alert.get("instances") or [{}])[0].get("uri"),
            })
    return findings


def severity_counts(findings: list[dict]) -> dict:
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0, "unknown": 0}
    for finding in findings:
        severity = str(finding.get("severity", "unknown")).lower()
        counts[severity if severity in counts else "unknown"] += 1
    return counts


def gate_status(findings: list[dict], tool_results: dict) -> str:
    counts = severity_counts(findings)
    if counts["critical"] or counts["high"]:
        return "failed"
    if any(result.get("status") == "error" for result in tool_results.values() if isinstance(result, dict)):
        return "needs_review"
    return "passed"


def main() -> int:
    parser = argparse.ArgumentParser(description="Run Semgrep, Trivy, OWASP ZAP, and Nuclei as a modular security gate.")
    parser.add_argument("--repo", default=".", help="Repository path to scan.")
    parser.add_argument("--provider", default="gitlab", help="CI/CD provider label. Defaults to gitlab.")
    parser.add_argument("--repo-ref", default=None, help="Provider repository reference.")
    parser.add_argument("--branch", default=os.getenv("CI_COMMIT_REF_NAME") or os.getenv("GIT_BRANCH"))
    parser.add_argument("--commit-sha", default=os.getenv("CI_COMMIT_SHA") or os.getenv("GITHUB_SHA"))
    parser.add_argument("--target-url", default=os.getenv("DAST_TARGET_URL"), help="Optional web app URL for ZAP/Nuclei.")
    parser.add_argument("--output", default=None, help="Write canonical JSON result to this path.")
    parser.add_argument("--safe-demo", action="store_true", help="Do not fail when scanners are missing; useful for dashboard smoke tests.")
    args = parser.parse_args()

    repo = Path(args.repo).resolve()
    if not repo.exists():
        print(json.dumps({"error": f"repo path not found: {repo}"}), file=sys.stderr)
        return 2

    tool_results = {}
    findings: list[dict] = []

    semgrep = run_command("semgrep", ["semgrep", "--config", "auto", "--json", str(repo)])
    tool_results["semgrep"] = {key: semgrep.get(key) for key in ("status", "returncode", "reason", "duration_seconds", "stderr") if semgrep.get(key) is not None}
    findings.extend(normalize_semgrep(semgrep))

    trivy = run_command("trivy", ["trivy", "fs", "--format", "json", "--quiet", str(repo)])
    tool_results["trivy"] = {key: trivy.get(key) for key in ("status", "returncode", "reason", "duration_seconds", "stderr") if trivy.get(key) is not None}
    findings.extend(normalize_trivy(trivy))

    zap_file = repo / ".zap-baseline.json"
    if args.target_url:
        zap = run_command("owasp-zap", ["zap-baseline.py", "-t", args.target_url, "-J", str(zap_file)], cwd=repo, timeout=1200)
    else:
        zap = {"status": "skipped", "reason": "target URL not provided", "duration_seconds": 0}
    tool_results["owasp_zap"] = {key: zap.get(key) for key in ("status", "returncode", "reason", "duration_seconds", "stderr") if zap.get(key) is not None}
    findings.extend(normalize_zap(zap, zap_file))

    if args.target_url:
        nuclei = run_command("nuclei", ["nuclei", "-u", args.target_url, "-jsonl", "-silent"], timeout=1200)
    else:
        nuclei = {"status": "skipped", "reason": "target URL not provided", "duration_seconds": 0}
    tool_results["nuclei"] = {key: nuclei.get(key) for key in ("status", "returncode", "reason", "duration_seconds", "stderr") if nuclei.get(key) is not None}
    findings.extend(normalize_nuclei(nuclei))

    status = gate_status(findings, tool_results)
    result = {
        "provider": args.provider,
        "repo_ref": args.repo_ref or str(repo),
        "branch": args.branch,
        "commit_sha": args.commit_sha,
        "target_url": args.target_url,
        "status": status,
        "summary": f"CI/CD security pipeline {status}: {len(findings)} findings across Semgrep, Trivy, OWASP ZAP, and Nuclei.",
        "findings": findings,
        "severity_counts": severity_counts(findings),
        "tool_results": tool_results,
    }

    payload = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    print(payload)
    if args.safe_demo:
        return 0
    return 1 if status == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
