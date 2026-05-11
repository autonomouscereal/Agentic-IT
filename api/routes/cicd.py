from fastapi import APIRouter, Body, Query

from database import fetchall, fetchrow, fetchval, execute, json_dumps
from services import ticket_service
from services.event_logger import log_event

router = APIRouter(prefix="/api/cicd", tags=["cicd"])


def _finding_count(findings):
    return len(findings) if isinstance(findings, list) else 0


def _severity_counts(findings):
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0, "unknown": 0}
    for finding in findings if isinstance(findings, list) else []:
        sev = str(finding.get("severity", "unknown")).lower()
        counts[sev if sev in counts else "unknown"] += 1
    return counts


def _gate_status(findings, tool_results):
    counts = _severity_counts(findings)
    tool_errors = [
        name for name, result in (tool_results or {}).items()
        if isinstance(result, dict) and result.get("status") == "error"
    ]
    if counts["critical"] or counts["high"]:
        return "failed"
    if tool_errors:
        return "needs_review"
    return "passed"


@router.get("/runs")
async def list_runs(limit: int = Query(50, ge=1, le=200)):
    rows = await fetchall("""
        SELECT r.*, t.title AS ticket_title, cr.status AS change_status
        FROM cicd_security_runs r
        LEFT JOIN tickets t ON t.id = r.ticket_id
        LEFT JOIN change_requests cr ON cr.id = r.change_id
        ORDER BY r.created_at DESC
        LIMIT $1
    """, limit)
    return {"runs": rows, "total": len(rows)}


@router.get("/runs/{run_id}")
async def get_run(run_id: int):
    row = await fetchrow("""
        SELECT r.*, t.title AS ticket_title, cr.status AS change_status
        FROM cicd_security_runs r
        LEFT JOIN tickets t ON t.id = r.ticket_id
        LEFT JOIN change_requests cr ON cr.id = r.change_id
        WHERE r.id = $1
    """, run_id)
    if not row:
        return {"error": "CI/CD security run not found"}
    return row


@router.post("/runs")
async def record_run(body: dict = Body({})):
    body = body or {}
    findings = body.get("findings") or []
    tool_results = body.get("tool_results") or {}
    status = body.get("status") or _gate_status(findings, tool_results)
    provider = body.get("provider") or "gitlab"
    repo_ref = body.get("repo_ref") or body.get("repo") or "unknown"
    target_url = body.get("target_url")
    summary = body.get("summary") or (
        f"CI/CD security pipeline {status}: {_finding_count(findings)} findings for {repo_ref}"
    )
    create_ticket = bool(body.get("create_ticket", False))
    require_change = bool(body.get("require_change", False))
    deployment_target = body.get("deployment_target") or "test"
    ticket_id = body.get("ticket_id")

    if create_ticket and not ticket_id:
        counts = _severity_counts(findings)
        description = "\n".join([
            "CI/CD security pipeline result",
            "",
            f"Provider: {provider}",
            f"Repository: {repo_ref}",
            f"Branch: {body.get('branch') or '-'}",
            f"Commit: {body.get('commit_sha') or '-'}",
            f"Target URL: {target_url or '-'}",
            f"Gate status: {status}",
            f"Severity counts: {counts}",
            "",
            summary,
        ])
        ticket = await ticket_service.create_ticket(
            title=f"CI/CD security gate: {repo_ref}",
            description=description,
            ticket_class="Change" if deployment_target == "production" else "UserRequest",
            status="new",
            priority="P1" if counts["critical"] else ("P2" if counts["high"] else "P3"),
            provider="local",
            sync_provider=False,
            created_by="cicd-security-pipeline",
        )
        ticket_id = ticket["id"]
        await ticket_service.add_note(
            ticket_id,
            f"Security pipeline recorded {len(findings)} findings. Gate status: {status}.",
            author="cicd-security-pipeline",
            source="cicd",
            visibility="internal",
        )

    change_id = body.get("change_id")
    if require_change and ticket_id and not change_id:
        change_id = await fetchval("""
            INSERT INTO change_requests (
                ticket_id, action, target, reason, risk_level, approval_policy,
                status, requested_by, requested_at, expires_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, 'pending', 'cicd-security-pipeline',
                    NOW(), NOW() + INTERVAL '7 days')
            RETURNING id
        """, ticket_id,
            "Approve production deployment after CI/CD security gate",
            repo_ref,
            summary,
            "high" if deployment_target == "production" else "medium",
            json_dumps({
                "provider": provider,
                "deployment_target": deployment_target,
                "gate_status": status,
                "requires_clean_high_critical": True,
            }))

    run_id = await fetchval("""
        INSERT INTO cicd_security_runs (
            provider, repo_ref, branch, commit_sha, target_url, status, summary,
            findings, tool_results, ticket_id, change_id, created_by, completed_at
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, NOW())
        RETURNING id
    """, provider, repo_ref, body.get("branch"), body.get("commit_sha"), target_url,
        status, summary, json_dumps(findings), json_dumps(tool_results), ticket_id,
        change_id, body.get("created_by") or "cicd-security-pipeline")

    await execute("""
        INSERT INTO audit_log (actor, action, target, details)
        VALUES ($1, $2, $3, $4)
    """, "cicd-security-pipeline", "cicd_security_run_recorded", f"cicd_run_{run_id}",
        json_dumps({
            "provider": provider,
            "repo_ref": repo_ref,
            "status": status,
            "ticket_id": ticket_id,
            "change_id": change_id,
            "findings": len(findings),
        }))
    await log_event("cicd", "info", "cicd-security-pipeline", "cicd_security_run_recorded",
                    f"cicd_run_{run_id}", {
                        "provider": provider,
                        "status": status,
                        "ticket_id": ticket_id,
                        "change_id": change_id,
                    })
    return {"id": run_id, "status": status, "ticket_id": ticket_id, "change_id": change_id}


@router.get("/gitlab/template")
async def gitlab_template():
    template = """stages:
  - test
  - security

variables:
  PIP_CACHE_DIR: "$CI_PROJECT_DIR/.cache/pip"

unit_tests:
  stage: test
  image: python:3.12-slim
  script:
    - python --version
    - test -f requirements.txt && pip install -r requirements.txt || true
    - test -d tests && python -m pytest tests || echo "no tests directory"

semgrep_sast:
  stage: security
  image: semgrep/semgrep:latest
  script:
    - semgrep --config auto --json --output semgrep.json .
  artifacts:
    when: always
    paths: [semgrep.json]
  allow_failure: true

trivy_fs:
  stage: security
  image: aquasec/trivy:latest
  script:
    - trivy fs --format json --output trivy.json .
  artifacts:
    when: always
    paths: [trivy.json]
  allow_failure: true

zap_baseline_optional:
  stage: security
  image: ghcr.io/zaproxy/zaproxy:stable
  script:
    - test -n "$DAST_TARGET_URL" && zap-baseline.py -t "$DAST_TARGET_URL" -J zap.json || echo "DAST_TARGET_URL not set"
  artifacts:
    when: always
    paths: [zap.json]
  allow_failure: true

nuclei_optional:
  stage: security
  image: projectdiscovery/nuclei:latest
  script:
    - test -n "$DAST_TARGET_URL" && nuclei -u "$DAST_TARGET_URL" -jsonl -o nuclei.jsonl || echo "DAST_TARGET_URL not set"
  artifacts:
    when: always
    paths: [nuclei.jsonl]
  allow_failure: true
"""
    return {
        "provider": "gitlab",
        "filename": ".gitlab-ci.yml",
        "template": template,
        "notes": [
            "GitLab is the default deployable CI/CD provider in the reference platform.",
            "OWASP ZAP is usually run with zap-baseline.py or a ZAP service image against DAST_TARGET_URL.",
            "Production deploy jobs should depend on this security stage and a dashboard change approval.",
        ],
    }
