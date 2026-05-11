# CI/CD Security Pipeline

The platform now has a GitLab-default, provider-agnostic CI/CD security gate.
GitLab CE and GitLab Runner are the reference deployment, but the dashboard API
accepts the same canonical run payload from GitHub Actions, Azure DevOps,
Jenkins, or a local agent task.

## Gate Order

1. Unit tests run first in the provider pipeline.
2. Semgrep runs SAST.
3. Trivy scans filesystem/dependencies/containers/IaC.
4. OWASP ZAP runs when a DAST target URL exists.
5. Nuclei runs when a DAST target URL exists.
6. Results are posted to `/api/cicd/runs`.
7. Production deployments create a dashboard change request and wait for human
   approval.

High or critical findings fail the gate. Scanner errors are marked
`needs_review`. Missing optional DAST targets are recorded as skipped.

## Scripts

```bash
python3 scripts/run_cicd_security_pipeline.py \
  --provider gitlab \
  --repo . \
  --repo-ref group/project \
  --branch main \
  --commit-sha "$CI_COMMIT_SHA" \
  --target-url "$DAST_TARGET_URL" \
  --output cicd-security-result.json
```

The script outputs canonical JSON suitable for:

```bash
curl -sS -X POST "$SOC_DASHBOARD_URL/api/cicd/runs" \
  -H "Content-Type: application/json" \
  --data-binary @cicd-security-result.json
```

## API

- `GET /api/cicd/gitlab/template`
- `GET /api/cicd/runs`
- `GET /api/cicd/runs/{run_id}`
- `POST /api/cicd/runs`

Posting a run with `create_ticket=true` creates an evidence ticket. Posting with
`require_change=true` creates a pending change gate before production deploy.

## GitLab Default

The dashboard exposes a starter `.gitlab-ci.yml` at:

```bash
curl -sS http://localhost:25480/api/cicd/gitlab/template
```

Use GitLab CI variables for `SOC_DASHBOARD_URL` and optional
`DAST_TARGET_URL`. Use GitLab protected branches/environments and dashboard
change approvals together for production changes.

## Test

```bash
python3 scripts/smoke_cicd_security_pipeline.py http://localhost:25480
```

Expected: the smoke test confirms the GitLab template, runs the local pipeline
script in safe mode, records the run, creates a dashboard ticket, and creates a
pending deployment approval gate.
