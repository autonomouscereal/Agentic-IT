# Installer E2E Results

Last verified: 2026-05-11

## Scratch Install

Command shape:

```bash
python3 installer/bootstrap.py \
  --profile soc \
  --source /home/cereal/SOC_TESTING/soc-dashboard \
  --target /home/cereal/SOC_TESTING/soc-dashboard-install-e2e \
  --dashboard-port 25481 \
  --db-port 5434 \
  --project-name soc-dashboard-e2e \
  --ai-base-url http://192.168.50.222:4001 \
  --itop-sync-enabled false
```

Result:

- Fresh Docker Compose project: `soc-dashboard-e2e`.
- API: `http://localhost:25481`.
- PostgreSQL: host port `5434`.
- Health returned version `1.3.0`.
- Runner health reached the model proxy at `http://192.168.50.222:4001`.
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
cd /home/cereal/SOC_TESTING/soc-dashboard-install-e2e
docker compose down -v --remove-orphans
```
