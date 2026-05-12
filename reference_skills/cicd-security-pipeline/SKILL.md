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

Scanner result semantics:

- Semgrep returns findings in JSON; use repo-local `.semgrep.yml` when present
  for deterministic customer demos and compact agent remediation prompts.
- The `aquasec/trivy` Docker image entrypoint is already `trivy`; Docker
  invocations should pass `fs ...`, not `trivy fs ...`.
- OWASP ZAP baseline exit code `2` means warnings were found. Treat it as
  completed-with-findings and let severity decide the gate. Treat only execution
  failures as tool errors.
- Nuclei can legitimately return no matches; record the completed scan and zero
  findings.

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
  --docker-network "$CICD_DOCKER_NETWORK" \
  --output cicd-security-result.json

curl -sS -X POST "$SOC_DASHBOARD_URL/api/cicd/runs" \
  -H "Content-Type: application/json" \
  --data-binary @cicd-security-result.json
```

For lab apps listening on the same Linux host as Docker, use
`CICD_DOCKER_NETWORK=host` or `--docker-network host` so ZAP and Nuclei can
reach the target without relying on Docker bridge hostnames. Leave it unset for
normal provider-hosted CI targets.

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

Full local-model proof:

```bash
python scripts/agentic_cicd_full_demo.py \
  --base http://localhost:25480 \
  --model qwen/qwen3.6-27b \
  --workspace /opt/agentic-it/SOC_TESTING/soc-dashboard/demo_runs
```

Latest verified full run on 2026-05-11:

- Ticket `82`
- Initial CI/CD run `8`: `needs_review`
- Local remediation agent `48`, task `46`
- Agent remediation change `34`: approved before edits
- Final CI/CD run `10`: `passed`
- Deployment change `36`: approved and completed
- Patch artifact: `/opt/agentic-it/SOC_TESTING/soc-dashboard/agent_work/48/agent-remediation.patch`

The agent removed command injection and a hardcoded password, updated a stale
dependency, added a non-root container user, wrote ticket evidence, and produced
a patch/branch artifact for PR/MR review. This path is the local-only fallback
proof; use the GitLab runner proof below when the demo needs a real GitLab
project, MR, and branch pipeline.

GitLab runner proof:

```bash
python scripts/agentic_gitlab_cicd_demo.py \
  --dashboard http://localhost:25480 \
  --gitlab http://localhost \
  --model qwen/qwen3.6-27b \
  --workspace /opt/agentic-it/SOC_TESTING/soc-dashboard/demo_runs \
  --timeout 3000
```

Latest verified GitLab-backed run on 2026-05-11:

- GitLab project `root/agentic-cicd-demo-1778538475`, project id `15`
- Ticket `83`
- Initial GitLab pipeline `9`: failed as intended after unit tests, Semgrep,
  Trivy, OWASP ZAP, and Nuclei all ran
- Initial dashboard run `11`: failed with seven findings
- Local remediation agent `50`, task `48`
- Agent change `39`: approved before edits and completed after the agent fix
- Remediation branch `agent/remediate-security-gate`
- Remediation commit `2f0984f2b074764927dd21ec024638eb020b9185`
- Merge request `!1`
- Final GitLab pipeline `10`: passed
- Final dashboard run `12`: passed with zero findings
- Deployment change `40`: approved and completed
- Postmortem `21`: ready for review

Live GitLab verification:

- Project `15`: `root/agentic-cicd-demo-1778538475`
- MR `!1`: `agent/remediate-security-gate` -> `main`, state `opened`
- Pipeline `9` on `main`: `failed`; unit tests and all scanner jobs succeeded,
  dashboard record failed because the initial branch had findings
- Pipeline `10` on `agent/remediate-security-gate`: `success`; unit tests,
  Semgrep, Trivy, ZAP, Nuclei, and dashboard record all succeeded

Reference GitLab Runner requirements:

- Attach the runner to generated demo projects, or configure it as an instance
  runner.
- Job containers must reach GitLab and the dashboard. In the lab, use
  `network_mode = "gitlab-net"` and `SOC_DASHBOARD_URL=http://127.0.0.1:25480`.
- Mount `/tmp/zap-wrk:/zap/wrk` so ZAP can write JSON output from its container.
- Keep Nuclei bounded for demos with small template lists and explicit targets.
