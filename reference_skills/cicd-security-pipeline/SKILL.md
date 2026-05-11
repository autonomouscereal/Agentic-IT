---
name: cicd-security-pipeline
description: >
  Modular CI/CD security gate for the agentic IT/SOC platform. Uses GitLab CE
  and GitLab Runner by default in the reference deployment, while keeping the
  result contract portable to GitHub Actions, Azure DevOps, Jenkins, or any
  provider that can run CLI scanners and POST JSON to the dashboard.
---

# CI/CD Security Pipeline

Use this skill when an agent needs to validate code, merge requests, release
candidates, or deployment changes before they move beyond a test environment.

The reference provider is GitLab because the platform already ships a deployable
GitLab CE + Runner integration. Other providers must map to the same canonical
dashboard objects:

- canonical ticket for evidence and remediation
- CI/CD security run record
- change request for production-impacting deployment
- audit and event log entries

## Canonical Gate

Run these tools after unit tests and before production deploy approval:

1. Semgrep CLI for SAST.
2. Trivy CLI for dependency, filesystem, container, and IaC scanning.
3. OWASP ZAP baseline scan for DAST when a target URL exists.
4. Nuclei for exposure/template-driven checks when a target URL exists.

The gate fails when high or critical findings exist. Tool errors produce
`needs_review`. Missing optional DAST targets skip ZAP/Nuclei but still record
that decision.

## Deploy Scanner Tools

Portable Docker Compose bundle:

```bash
bash scripts/cicd_security_tools.sh pull
bash scripts/cicd_security_tools.sh gate --repo /path/to/repo --output ./scan-output
bash scripts/cicd_security_tools.sh gate --repo /path/to/repo --target-url http://app-under-test.local --output ./scan-output
```

Images:

- `semgrep/semgrep:latest`
- `aquasec/trivy:latest`
- `ghcr.io/zaproxy/zaproxy:stable`
- `projectdiscovery/nuclei:latest`

The Python normalizer supports `--execution auto`, `local`, `docker`, and
`artifacts`. GitLab jobs can either run scanner images directly or run the
wrapper and publish `security-gate-result.json`.

## Dashboard API

Record results with:

```bash
python scripts/run_cicd_security_pipeline.py \
  --execution auto \
  --provider gitlab \
  --repo "$CI_PROJECT_DIR" \
  --repo-ref "$CI_PROJECT_PATH" \
  --branch "$CI_COMMIT_REF_NAME" \
  --commit-sha "$CI_COMMIT_SHA" \
  --target-url "$DAST_TARGET_URL" \
  --output cicd-security-result.json

curl -sS -X POST "$SOC_DASHBOARD_URL/api/cicd/runs" \
  -H "Content-Type: application/json" \
  --data-binary @cicd-security-result.json
```

If the job represents production deployment, include:

```json
{
  "deployment_target": "production",
  "create_ticket": true,
  "require_change": true
}
```

Do not store tokens or passwords in the repository. Use GitLab CI variables,
the platform credential vault, or the deployment owner's approved secret store.

## GitLab Default

Fetch the dashboard-provided template:

```bash
curl -sS "$SOC_DASHBOARD_URL/api/cicd/gitlab/template"
```

The template includes unit tests, Semgrep, Trivy, OWASP ZAP, and Nuclei. ZAP
and Nuclei are optional when no reachable `DAST_TARGET_URL` exists, but their
skip/result state must still be recorded in the dashboard gate evidence.

Production deploy jobs should depend on the security stage and a dashboard
change approval. A deployment agent must not push production changes until the
linked dashboard change request is approved.

## Provider Agnostic Mapping

| Concept | GitLab | GitHub | Jenkins/Azure DevOps |
|---|---|---|---|
| repo ref | `CI_PROJECT_PATH` | `GITHUB_REPOSITORY` | job/repo variable |
| branch | `CI_COMMIT_REF_NAME` | `GITHUB_REF_NAME` | branch variable |
| commit | `CI_COMMIT_SHA` | `GITHUB_SHA` | commit variable |
| artifact | job artifacts | workflow artifacts | archived artifacts |
| approval | protected env/MR + dashboard change | environment approval + dashboard change | stage approval + dashboard change |

The dashboard stays the system of record for agent-visible evidence, approvals,
and audit logs.

## Test

Local safe smoke:

```bash
python scripts/smoke_cicd_security_pipeline.py http://localhost:25480
```

GitLab environment test:

1. Create a test project in GitLab.
2. Add the generated `.gitlab-ci.yml`.
3. Add CI variables for `SOC_DASHBOARD_URL` and optional `DAST_TARGET_URL`.
4. Push a branch and verify jobs run.
5. Confirm `/api/cicd/runs`, the evidence ticket, and the change request exist.
