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
  --execution auto \
  --provider gitlab \
  --repo . \
  --repo-ref group/project \
  --branch main \
  --commit-sha "$CI_COMMIT_SHA" \
  --target-url "$DAST_TARGET_URL" \
  --docker-network "$CICD_DOCKER_NETWORK" \
  --output cicd-security-result.json
```

Execution modes:

- `auto`: use local CLIs when present, otherwise Docker if available.
- `local`: require locally installed scanner CLIs.
- `docker`: run reference scanner images directly.
- `artifacts`: normalize existing `semgrep.json`, `trivy.json`, `zap.json`, and `nuclei.jsonl`.

When Docker scanner containers need to reach a local lab app, set
`CICD_DOCKER_NETWORK=host` or pass `--docker-network host`. For normal CI
runners, leave it unset and scan the provider-reachable DAST URL.

## Deployable Scanner Bundle

Portable Docker Compose deployment lives in `deploy/cicd-security-tools`.

```bash
bash scripts/cicd_security_tools.sh pull
bash scripts/cicd_security_tools.sh gate --repo /path/to/repo --output ./scan-output
bash scripts/cicd_security_tools.sh gate --repo /path/to/repo --target-url http://app-under-test.local --output ./scan-output
```

The bundle uses scanner images instead of host installs:

- `semgrep/semgrep:latest`
- `aquasec/trivy:latest`
- `ghcr.io/zaproxy/zaproxy:stable`
- `projectdiscovery/nuclei:latest`

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
script in artifact mode, records the run, creates a dashboard ticket, and
creates a pending deployment approval gate.

## Full Agentic Remediation Demo

The full local-model proof is:

```bash
cd /opt/agentic-it/SOC_TESTING/soc-dashboard
python3 scripts/agentic_cicd_full_demo.py \
  --base http://localhost:25480 \
  --model qwen/qwen3.6-27b \
  --workspace /opt/agentic-it/SOC_TESTING/soc-dashboard/demo_runs
```

This is intentionally more than a smoke test. It creates a deliberately
vulnerable app, runs real Semgrep/Trivy/ZAP/Nuclei scans, posts the evidence to
the dashboard, spawns a Claude Code/local-model remediation agent, waits for an
approval-gated change, lets the agent patch the app, reruns the scanners, creates
a local branch and patch artifact, records a deployment approval gate, and then
starts a postmortem. This path is the local-only fallback proof; use the GitLab
Runner proof below when the demo needs a real GitLab project, MR, and pipeline.

Latest verified run on 2026-05-11:

- Ticket `82`: `Agentic CI/CD remediation demo 1778534655`
- Initial run `8`: `needs_review`
- Remediation agent `48`, task `46`
- Agent change `34`: approved before source edits
- Final run `10`: `passed`
- Deployment change `36`: approved and completed
- Superseded failed gate `35`: rejected
- Patch artifact: `/opt/agentic-it/SOC_TESTING/soc-dashboard/agent_work/48/agent-remediation.patch`

The local model fixed the deterministic Semgrep findings by removing
`subprocess(..., shell=True)` and the hardcoded password, updated
`requests>=2.32.4`, added a non-root container user, and added basic response
security headers. Semgrep reported zero findings on the final run. Trivy,
OWASP ZAP, and Nuclei completed; ZAP medium/low header warnings remained below
the high/critical deployment block threshold.

Two scanner-contract fixes came out of the full run:

- The Docker Trivy image already has a `trivy` entrypoint, so wrapper commands
  must pass `fs ...`, not `trivy fs ...`.
- ZAP baseline exit code `2` means warnings were found, not tool failure. The
  normalizer treats it as completed-with-findings and lets the severity gate
  decide pass/fail.

For deterministic demos, place a repo-local `.semgrep.yml` in the demo app. The
wrapper prefers that file over broad default rules so the local model gets a
small, explainable finding set.

## GitLab Runner Agentic Proof

The full GitLab-backed proof is:

```bash
cd /opt/agentic-it/SOC_TESTING/soc-dashboard
python3 scripts/agentic_gitlab_cicd_demo.py \
  --dashboard http://localhost:25480 \
  --runner-dashboard http://127.0.0.1:25480 \
  --gitlab http://localhost \
  --model qwen/qwen3.6-27b
```

Latest verified run on 2026-05-11:

- GitLab project `root/agentic-cicd-demo-1778538475`
- Ticket `83`: `CI/CD security gate: root/agentic-cicd-demo-1778538475`
- Initial GitLab pipeline `9`: failed by design after all scanner jobs ran
- Initial dashboard run `11`: failed with 7 findings
- Remediation agent `50`, task `48`: completed
- Remediation change `39`: approved before edits and completed after verification
- GitLab branch `agent/remediate-security-gate`
- GitLab MR `!1`
- Final GitLab pipeline `10`: success
- Final dashboard run `12`: passed with 0 findings
- Deployment change `40`: approved and completed
- Postmortem `21`: ready for review

Live GitLab verification:

- Project `15`: `root/agentic-cicd-demo-1778538475`
- MR `!1`: `agent/remediate-security-gate` -> `main`, state `opened`
- Pipeline `9` on `main`: `failed`; all scanner jobs succeeded and the
  dashboard gate failed because findings existed
- Pipeline `10` on `agent/remediate-security-gate`: `success`; unit tests,
  Semgrep, Trivy, ZAP, Nuclei, and dashboard record all succeeded

Runner configuration requirements discovered by the live test:

- Project runners must be attached to new demo/customer projects, or the runner
  should be registered as an instance/shared runner.
- Docker executor jobs must run on `gitlab-net` so artifact upload/download can
  resolve the GitLab coordinator hostname.
- The runner Docker volume list must include `/tmp/zap-wrk:/zap/wrk` for the
  OWASP ZAP Docker image when JSON reports are requested.
- GitLab CI variable `SOC_DASHBOARD_URL` must be reachable from job containers.
  Do not use `localhost` unless the dashboard runs inside the same job
  container.
- ZAP writes JSON to `/zap/wrk/zap.json`; copy it back to `zap.json` for GitLab
  artifacts.
- Keep Nuclei template selection bounded for demos; full-template scans are
  valid but slow on local hardware.
