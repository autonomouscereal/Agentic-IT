# Deployment Runbook

Last updated: 2026-05-12.

## Requirements

- Docker and Docker Compose on the target server.
- PostgreSQL is provided by the compose stack.
- Claude Code installed in the API image/runtime path if agent execution is enabled.
- A reachable model/proxy endpoint in `AGENT_LLM_BASE_URL`.
- Server credentials stored in the server-manager vault.

Do not hardcode secrets in compose, docs, or source. Use environment variables or vault-backed deployment tooling.

## Current Lab

| Item | Value |
| --- | --- |
| Server | AI server |
| Path | `/home/cereal/SOC_TESTING/soc-dashboard` |
| URL | `http://192.168.50.222:25480` |
| Proxy | `http://192.168.50.222:4001` |
| Default model | `qwen/qwen3.6-27b` |

## Upload

Use server-manager from Windows. Do not copy runtime state back into the source
tree. Package code with exclusions for `.env`, `.git`, `data`, `agent_work`,
`runtime`, caches, and bytecode, then upload the archive to the server.

```powershell
tar --exclude='__pycache__' --exclude='*.pyc' --exclude='.pytest_cache' --exclude='data' --exclude='agent_work' --exclude='runtime' --exclude='.git' -czf soc-dashboard-deploy.tgz api frontend platform reference_skills scripts tests installer deploy docs agent_models.json docker-compose.yml README.md install.ps1 install.sh .env.example
python C:\Users\cereal\.agents\skills\server-manager\ssh_client.py --server ai --upload .\soc-dashboard-deploy.tgz /tmp/soc-dashboard-deploy.tgz
```

On the server, extract to a staging directory, replace only source-controlled
directories and files, and preserve `.env`, database volumes, `data`,
`agent_work`, and `runtime`.

## Environment

Create `.env` from `.env.example` on the server. Required for any deployment:

```text
SOC_DB_USER=<from vault or deployment secret>
SOC_DB_PASSWORD=<from vault or deployment secret>
AGENT_LLM_BASE_URL=http://<proxy-host>:4001
```

For iTop deployments:

```text
ITOP_SYNC_ENABLED=true
ITOP_HOST=<itop-host>
ITOP_PORT=25432
ITOP_WEB_BASE=http://<itop-host>:25432
ITOP_USER=<from vault or deployment secret>
ITOP_PASSWORD=<from vault or deployment secret>
ITOP_SECURITY_TEAM_ID=65
```

For local-only or non-iTop deployments:

```text
ITOP_SYNC_ENABLED=false
ITOP_HOST=
ITOP_USER=
ITOP_PASSWORD=
```

For outbound iTop ticket creation:

```text
ITOP_DEFAULT_ORG_ID=<environment-specific org id>
ITOP_DEFAULT_CALLER_ID=<environment-specific caller id>
```

Without those defaults, inbound iTop sync can still work, but dashboard-to-iTop creation of Incident/UserRequest tickets will record `create_failed`.

## Build And Start

On the server:

```bash
cd /home/cereal/SOC_TESTING/soc-dashboard
docker compose up -d --build --force-recreate api
```

Use `--force-recreate` after replacing bind-mounted source directories. This
prevents stale mounts such as an empty `/app/platform` from surviving a source
sync.

## Migrations

Existing deployments should apply migrations in order:

```bash
docker exec -i soc-dashboard-db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < api/migrations/002_agent_runner_hardening.sql
docker exec -i soc-dashboard-db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < api/migrations/003_agentic_system_objects.sql
```

Fresh deployments get the current schema from `api/init_db.sql`.

## Health Checks

```bash
curl -sS http://localhost:25480/health
curl -sS http://localhost:25480/api/agents/runner-health
curl -sS http://localhost:25480/api/agents/processes
python3 scripts/platform_doctor.py
```

Expected:

- health status `ok`
- runner harness `claude-code`
- model API status `ok`
- process diagnostics include `/usr/bin/ps`

After a source deployment, run the full live regression:

```bash
python3 -m compileall api scripts tests
for file in frontend/js/*.js; do node --check "$file"; done
python3 -m unittest discover -s tests -v
python3 scripts/audit_codex_migration.py --source-roots "/home/cereal/SOC_TESTING/soc-dashboard/reference_skills"
python3 scripts/platform_doctor.py --base http://localhost:25480 --env-file .env
python3 scripts/smoke_setup_platform.py http://localhost:25480
python3 scripts/smoke_provider_adapters.py http://localhost:25480
python3 scripts/smoke_service_desk_intake.py http://localhost:25480
python3 scripts/smoke_user_response_workflow.py http://localhost:25480
python3 scripts/smoke_agentic_system.py http://localhost:25480
python3 scripts/smoke_phishing_workflow_lifecycle.py http://localhost:25480
python3 scripts/smoke_cicd_security_pipeline.py http://localhost:25480
python3 scripts/smoke_agent_auditor.py http://localhost:25480
python3 scripts/smoke_postmortem_promotion.py http://localhost:25480
docker compose cp scripts/smoke_change_auto_completion.py api:/app/smoke_change_auto_completion.py
docker compose exec -T api python /app/smoke_change_auto_completion.py http://localhost:8000
python3 scripts/smoke_local_model_agent.py http://localhost:25480 qwen/qwen3.6-27b
python3 scripts/smoke_setup_agent.py http://localhost:25480 qwen/qwen3.6-27b
```

## Reference Mailcow API Shim

If the deployment includes the reference Mailcow email stack and the optional HTTP compatibility shim, manage it from the Mailcow deployment root, not from the dashboard compose stack:

```bash
cd /home/cereal/Mailcow/deploy
python3 scripts/deploy_mailcow_api.py
python3 scripts/test_mailcow_api_shim.py --mysql-parity
```

The shim redeploys only `php-fpm-mailcow-api` and `nginx-mailcow-api`. It does not recycle the main Mailcow mail path. Full details, endpoint contracts, rollback, and troubleshooting are in `docs/MAILCOW_API_SHIM.md`.

## Rebuild Triggers

Rebuild API container after:

- Python source changes
- requirements changes
- Dockerfile changes
- compose environment contract changes

Frontend-only JS/CSS/HTML changes generally need upload only because frontend is bind-mounted into the API container.

## Ownership Fix

If `agent_work` was created by an earlier root-run container and later bind mounts/users change:

```bash
sudo chown -R cereal:cereal /home/cereal/SOC_TESTING/soc-dashboard/agent_work
```

## Rollback

This project directory is not currently a git repository in this workspace. Before major live changes, copy the deployed directory or commit it in a proper repo. Database rollback is not implemented; migrations are additive and idempotent where possible.
