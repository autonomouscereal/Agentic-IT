# Deployment Runbook

Last updated: 2026-05-18.

## Requirements

- Docker and Docker Compose on the target server.
- PostgreSQL is provided by the compose stack.
- Docker Compose can build the API and built-in AI proxy images.
- Hermes Agent host auth/mounts or Claude Code credentials are available when agent execution is enabled.
- A reachable model gateway in `AGENT_LLM_BASE_URL`; built-in installs use `http://ai-proxy:4001` inside Docker.
- Server credentials stored in the server-manager vault.

Do not hardcode secrets in compose, docs, or source. Use environment variables or vault-backed deployment tooling.

## Current Lab

| Item | Value |
| --- | --- |
| Server | AI server |
| Path | `/home/cereal/SOC_TESTING/soc-dashboard` |
| URL | `http://192.168.50.222:25480` |
| Proxy | `http://192.168.50.222:4001` |
| Default harness | Hermes Agent |
| Default model | `deepseek/deepseek-v4-flash` |

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
AGENT_HARNESS=hermes
AGENT_DEFAULT_MODEL=deepseek/deepseek-v4-flash
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
docker compose up -d --build --force-recreate api ai-proxy
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
DASHBOARD_SERVICE_TOKEN="<from vault: dashboard_service_token>"
curl -sS -H "X-Dashboard-Service-Token: $DASHBOARD_SERVICE_TOKEN" http://localhost:25480/health
curl -sS -H "X-Dashboard-Service-Token: $DASHBOARD_SERVICE_TOKEN" http://localhost:25480/api/agents/runner-health
curl -sS -H "X-Dashboard-Service-Token: $DASHBOARD_SERVICE_TOKEN" http://localhost:25480/api/agents/processes
python3 scripts/platform_doctor.py
```

Expected:

- health status `ok`
- runner harness `hermes` or the explicitly selected fallback harness
- model API status `ok`
- proxy health/model aliases are reachable
- process diagnostics include `/usr/bin/ps`

Security posture for regulated demos, verified 2026-05-18:

- dashboard auth is enforced with trusted header mode
- direct unauthenticated UI, static, health, and API requests return `403`
- dashboard PostgreSQL, agent-memory PostgreSQL, and the AI proxy are bound to
  localhost on the AI Server
- run `python scripts/smoke_dashboard_auth_enforcement.py http://192.168.50.222:25480`
  with `DASHBOARD_TRUSTED_AUTH_SECRET` and `DASHBOARD_SERVICE_TOKEN` sourced
  from the credential vault before regulated demos
- run `python scripts/smoke_setup_agent.py http://192.168.50.222:25480 deepseek/deepseek-v4-flash`
  to prove a real Hermes worker can use scoped agent-session auth against
  protected dashboard endpoints
- run `python scripts/smoke_permission_provider_matrix.py http://192.168.50.222:25480 --model deepseek/deepseek-v4-flash`
  to prove RBAC, row-level separation, vault lease denial/grant, and access
  request gates

## Reference Module Login Validation

The lab demo account is `demo_account_1`; its password lives only in the local
server-manager vault key `demo_account_1`. Do not commit or print the value.

Latest live credential smoke on 2026-05-18:

| Module | Check | Result |
| --- | --- | --- |
| iTop | REST POST to `webservices/rest.php` as `demo_account_1` | PASS, `code=0`, count `1` |
| Wazuh Dashboard | Dashboard login endpoint | PASS, HTTP 200 |
| Wazuh API | Native `/security/user/authenticate?raw=true` | PASS, token issued |
| GitLab local login | Fresh CSRF/session form POST | PASS, HTTP 302 |
| GitLab Keycloak OIDC | Full browser SSO as `demo_account_1` | PASS, lands in GitLab as SOC Demo Account |
| Mailcow | demo UI, Roundcube webmail, mailbox auth, report phish | PASS, UI `http://192.168.50.222:2581` bare-root login reaches `/admin/dashboard`, including stale-session recovery; dashboard/system/mailbox/queue/quarantine pages show no invalid JSON or SQL-column warning banners; `/webmail` is Roundcube on real Mailcow IMAP/SMTP; `/SOGo/*` redirects to Roundcube; Report Phish proof created ticket `580`, iTop Incident `372`, agent `229`, access request `581`, and visible quarantine row `21a705b151642568d375c748a9ea1a6b` |

GitLab OIDC deployment requirements:

- `gitlab` compose service includes `extra_hosts: ["keycloak.internal:host-gateway"]`.
- Keycloak integration CA is copied into
  `/etc/gitlab/trusted-certs/keycloak-internal-ca.crt`, followed by
  `gitlab-ctl reconfigure`.
- Keycloak should use a browser-routable full URL for the demo issuer/admin
  surface, for example `KC_HOSTNAME=https://192.168.50.222:8443` and
  `KC_HOSTNAME_ADMIN=https://192.168.50.222:8443`.
- GitLab OmniAuth should use the same browser-routable issuer,
  `https://192.168.50.222:8443/realms/gitlab`. The `keycloak.internal`
  host-gateway route can remain as an internal compatibility alias, but the
  browser demo path should not require workstation hosts-file changes.
- Keycloak GitLab protocol mappers must be current. Run
  `/home/cereal/gitlab-keycloak-integration/scripts/setup_oidc.py` after
  mapper changes; it updates existing mappers in place so stale Keycloak
  mapper types cannot leave GitLab SSO failing with an opaque OmniAuth error.

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

The shim redeploys only the sidecars: `php-fpm-mailcow-api`, `nginx-mailcow-api`, and `roundcube-mailcow-demo`. It does not recycle the main Mailcow mail path. The reference deployer also exposes the demo UI on port `2581`, routes the bare root URL to the verified admin UI, recovers stale user-session cookies that would otherwise redirect to the blank `/user` path, repairs the custom deployment's UI compatibility schema, supplies Mailcow/DataTables JSON for domain search, quarantine, and template reads, proxies `/webmail` to Roundcube on loopback port `2582`, redirects `/SOGo/*` to Roundcube, and keeps extensionless Mailcow routes behind FastCGI so PHP source is never served as static text. Full details, endpoint contracts, rollback, and troubleshooting are in `docs/MAILCOW_API_SHIM.md`.

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
