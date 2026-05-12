# Deployment Runbook

Last updated: 2026-05-11.

## Requirements

- Docker and Docker Compose on the target server.
- PostgreSQL is provided by the compose stack.
- Claude Code installed in the API image/runtime path if agent execution is enabled.
- A reachable model/proxy endpoint in `AGENT_LLM_BASE_URL`.
- Server credentials stored in the credential-vault.

Do not hardcode secrets in compose, docs, or source. Use environment variables or vault-backed deployment tooling.

## Current Lab

| Item | Value |
| --- | --- |
| Server | AI server |
| Path | `${PLATFORM_HOME}/soc-dashboard` |
| URL | `${SOC_DASHBOARD_URL}` |
| Proxy | `${AGENT_LLM_BASE_URL}` |
| Default model | `qwen/qwen3.6-27b` |

## Upload

Use server-manager from Windows:

```powershell
python <server-manager>/ssh_client.py --server ai --upload-dir "C:\path\to\soc-dashboard" "${PLATFORM_HOME}/soc-dashboard"
```

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
cd ${PLATFORM_HOME}/soc-dashboard
docker compose up -d --build api
```

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

## Reference Mailcow API Shim

If the deployment includes the reference Mailcow email stack and the optional HTTP compatibility shim, manage it from the Mailcow deployment root, not from the dashboard compose stack:

```bash
cd ${MAILCOW_DEPLOY_DIR}
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
sudo chown -R ${PLATFORM_USER}:${PLATFORM_GROUP} ${PLATFORM_HOME}/soc-dashboard/agent_work
```

## Rollback

This project directory is not currently a git repository in this workspace. Before major live changes, copy the deployed directory or commit it in a proper repo. Database rollback is not implemented; migrations are additive and idempotent where possible.
