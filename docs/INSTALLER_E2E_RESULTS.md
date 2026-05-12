# Installer E2E Results

Last verified: 2026-05-12

## Full One-Line Install Verification - 2026-05-12

Fresh install target:

- Target: `/opt/agentic-it/SOC_TESTING/soc-dashboard-install-e2e-20260512`
- Compose project: `soc-dashboard-e2e-20260512`
- Dashboard/API: `http://localhost:25482`
- PostgreSQL host port: `5435`
- AI proxy: `http://127.0.0.1:4001`
- Agent model: `qwen/qwen3.6-27b`
- iTop sync: disabled for provider-agnostic/local-only installer testing

Actual one-line installer command:

```bash
cd /opt/agentic-it/SOC_TESTING/soc-dashboard
./install.sh \
  --profile soc \
  --source /opt/agentic-it/SOC_TESTING/soc-dashboard \
  --target /opt/agentic-it/SOC_TESTING/soc-dashboard-install-e2e-20260512 \
  --dashboard-port 25482 \
  --db-port 5435 \
  --project-name soc-dashboard-e2e-20260512 \
  --ai-base-url http://127.0.0.1:4001 \
  --model qwen/qwen3.6-27b \
  --itop-sync-enabled false \
  --non-interactive
```

Result:

- Installer returned `status=installed`.
- `GET /health` returned `{"status":"ok","version":"1.3.0"}`.
- `docker compose ps` showed project-scoped `api` and healthy `db` containers.
- `runner-health` reached the proxy and resolved `ps_path=/usr/bin/ps`.
- `platform_doctor.py --base http://localhost:25482` passed `18/18`.

Regression suite executed against the fresh install:

```bash
python3 scripts/platform_doctor.py --base http://localhost:25482
python3 scripts/smoke_setup_platform.py http://localhost:25482
python3 scripts/smoke_provider_adapters.py http://localhost:25482
python3 scripts/smoke_service_desk_intake.py http://localhost:25482
python3 scripts/smoke_agentic_system.py http://localhost:25482
python3 scripts/smoke_phishing_workflow_lifecycle.py http://localhost:25482
python3 scripts/smoke_cicd_security_pipeline.py http://localhost:25482
python3 scripts/smoke_agent_auditor.py http://localhost:25482
docker compose exec -T api python smoke_change_auto_completion.py http://localhost:8000
python3 scripts/smoke_local_model_agent.py http://localhost:25482 qwen/qwen3.6-27b
python3 scripts/smoke_setup_agent.py http://localhost:25482 qwen/qwen3.6-27b
```

Observed outputs:

- Setup smoke: ticket `14`.
- Provider adapters: ticket `15`, local provider `local_only`, ServiceNow/Jira fail-closed as unconfigured.
- Service desk intake: ticket `16`, change `10`, phishing intent.
- Agentic system smoke: ticket `17`, local push ticket `18`, change `11`, postmortem `5`, workflow `3`, skill `24`.
- Phishing lifecycle: ticket `19`, change `12`, workflow `2`, postmortem `6`.
- CI/CD control-plane smoke: run `7`, ticket `20`, change `13`, provider `gitlab`.
- Change auto-completion: ticket `21`, agent `9`, task `9`, change `14`, status `completed`, evidence persisted.
- Local model agent smoke: ticket `22`, agent `10`, task `10`, status `completed`, note written.
- Setup agent smoke: ticket `23`, agent `11`, task `11`, status `completed`, note written.
- `/api/agents/processes` reported no active processes after the suite.

Real installed-stack CI/CD agent workflow:

```bash
cd /opt/agentic-it/SOC_TESTING/soc-dashboard-install-e2e-20260512
SOC_DASHBOARD_URL=http://localhost:25482 \
AGENT_MODEL=qwen/qwen3.6-27b \
CICD_DOCKER_NETWORK=host \
python3 scripts/agentic_cicd_full_demo.py \
  --base http://localhost:25482 \
  --host-ip 127.0.0.1 \
  --timeout 2400
```

Latest verified result:

```text
ticket_id=13
initial_run=5 failed high=1 medium=6 low=6 info=1 unknown=2
remediation_agent=7 task=7 completed
remediation_change=8 completed
final_run=6 passed high=0 critical=0
deployment_change=9 completed
postmortem=4 ready_for_review
mr_artifact=/opt/agentic-it/SOC_TESTING/soc-dashboard-install-e2e-20260512/agent_work/7/agent-remediation.patch
active_agent_processes=0
```

Issues found during this fresh installer run:

- `install.sh` did not preserve executable mode after file transfer. Fixed with
  `git update-index --chmod=+x install.sh`; remote source was repaired with
  `chmod +x`.
- `agentic_cicd_full_demo.py` repaired root-owned agent workdirs by fixed
  container name. Fresh installs use custom Compose project names, so the runner
  now uses `docker compose exec -T api` from the installed root and verifies
  host writability before seeding agent workspaces.
- Local-model postmortem agents can still stall or exit without writing a
  postmortem row. The runner now synthesizes a bounded `ready_for_review`
  postmortem directly when that happens, and the demo script stops the leftover
  postmortem agent after synthesis.
- The DB-coupled change-completion smoke requires API dependencies and should
  run inside the API container for one-line/container installs.

## Scratch Install

Command shape:

```bash
python3 installer/bootstrap.py \
  --profile soc \
  --source /opt/agentic-it/SOC_TESTING/soc-dashboard \
  --target /opt/agentic-it/SOC_TESTING/soc-dashboard-install-e2e \
  --dashboard-port 25481 \
  --db-port 5434 \
  --project-name soc-dashboard-e2e \
  --ai-base-url http://127.0.0.1:4001 \
  --itop-sync-enabled false
```

Result:

- Fresh Docker Compose project: `soc-dashboard-e2e`.
- API: `http://localhost:25481`.
- PostgreSQL: host port `5434`.
- Health returned version `1.3.0`.
- Runner health reached the model proxy at `http://127.0.0.1:4001`.
- `install_state/last-plan.json` recorded profile `soc` with 25 modules.
- `docker compose ps` showed project-scoped containers, no fixed-name collision.

## Tests Passed

```bash
python3 scripts/smoke_setup_platform.py http://localhost:25481
python3 scripts/smoke_agentic_system.py http://localhost:25481
python3 scripts/smoke_phishing_workflow_lifecycle.py http://localhost:25481
python3 scripts/sync_reference_skills.py check --source-roots reference_skills
python3 scripts/smoke_local_model_agent.py http://localhost:25481 qwen/qwen3.6-27b
python3 scripts/smoke_setup_agent.py http://localhost:25481 qwen/qwen3.6-27b
```

Observed outputs:

- Setup smoke created setup ticket `1`.
- Agentic system smoke created ticket `2`, local provider ticket `3`, change `1`, postmortem `1`, workflow `1`, and skill `19`.
- Phishing lifecycle smoke created ticket `4`, change `2`, workflow `2`, and postmortem `2`.
- Local model agent smoke created ticket `5`, agent `1`, task `1`; task completed and wrote the expected note.
- Setup agent smoke created setup ticket `6`, agent `2`, task `2`; task completed and wrote the expected setup note.
- `/api/agents/processes` reported no active processes after model-backed tests.

## Bugs Found And Fixed

- Fixed Docker install collisions by removing fixed container names and making ports/project name environment-driven.
- Fixed fresh installs missing global skills by seeding baseline skills in both `init_db.sql` and migration `004_seed_baseline_agent_skills.sql`.
- Fixed installer upgrade behavior by applying idempotent migrations after `docker compose up`.
- Fixed skill bundle drift by adding `scripts/sync_reference_skills.py`, an allowlisted `platform/skill_sync_config.json`, and sanitized `reference_skills/`.
- Removed hardcoded test/admin password fallbacks from the Keycloak-Mailcow bridge skill before bundling.

## Remaining Notes

The scratch E2E install is intentionally still running on `25481/5434` for inspection. It can be removed with:

```bash
cd /opt/agentic-it/SOC_TESTING/soc-dashboard-install-e2e
docker compose down -v --remove-orphans
```
