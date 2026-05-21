# Deployment Runbook

Last updated: 2026-05-21.

## Requirements

- Docker and Docker Compose on the target server.
- PostgreSQL is provided by the compose stack.
- Docker Compose can build the API and built-in AI proxy images.
- OpenSSL is available on the target host for first-start local CA and server
  certificate generation, or pre-created cert/key files are placed in
  `runtime/tls`.
- Hermes Agent host auth/mounts, Claude Code credentials, or Codex `CODEX_HOME`/runtime API key are available when agent execution is enabled.
- A reachable model gateway in `AGENT_LLM_BASE_URL`; built-in installs use `http://ai-proxy:4001` inside Docker.
- Server credentials stored in the server-manager vault.

Do not hardcode secrets in compose, docs, or source. Use environment variables or vault-backed deployment tooling.

## Current Lab

| Item | Value |
| --- | --- |
| Server | AI server |
| Path | `/home/cereal/SOC_TESTING/soc-dashboard` |
| URL | `https://192.168.50.222:25443` |
| Local API | `http://127.0.0.1:25480` |
| Proxy | `http://ai-proxy:4001` inside Docker; `http://192.168.50.222:4001` from the LAN |
| Default harness | Hermes Agent; Claude Code and Codex selectable |
| Product default model | `local/agent-default` |
| Lab external model | `deepseek/deepseek-v4-flash` |
| Ops Chat | `https://192.168.50.222:3303` Element/Matrix client |

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
AI_MODEL_ROUTE=local
AI_PROXY_MODEL_ROUTE=local
AI_PROXY_EXTERNAL_ENABLED=false
AGENT_DEFAULT_MODEL=local/agent-default
HERMES_DEFAULT_PROVIDER=dashboard-proxy
CODEX_HOME_DIR=./runtime/codex
CODEX_AUTH_MODE=proxy
CODEX_MODEL_PROVIDER=agentic_proxy
CODEX_SANDBOX=danger-full-access
CODEX_APPROVAL_POLICY=never
CODEX_API_KEY=<optional vault/runtime secret>
DASHBOARD_BIND=127.0.0.1
DASHBOARD_HTTPS_BIND=0.0.0.0
DASHBOARD_HTTPS_PORT=25443
DASHBOARD_TLS_DIR=./runtime/tls
```

Keep production and regulated deployments local/on-prem first unless an
external model route is explicitly approved. The demo/lab route can be toggled
without editing secrets:

```bash
python scripts/switch_model_route.py --route external --restart
python scripts/switch_model_route.py --route local --restart
```

The switch updates `.env`, `runtime/proxy_config.json`, and
`agent_models.json`. Provider keys remain in the vault/runtime environment.

For Codex subscription/OAuth mode, set `CODEX_AUTH_MODE=oauth`, preserve
`CODEX_HOME_DIR`, and enroll once with:

```bash
docker compose exec api codex login --device-auth
docker compose exec api codex login status
```

The OAuth/device-login approval is a human approval gate, but the platform owns
the lifecycle around it: detect missing login, open a setup/access ticket, show
the device URL/code, poll status, and smoke-test the harness. Treat
`CODEX_HOME_DIR` as secret runtime state, similar to a vault-backed credential
lease. Do not commit it or bake it into images.

In OAuth mode, debug with Codex's own JSONL stream rather than the AI proxy:
`codex exec --json --output-last-message ...`. Subscription/OAuth runs use the
mounted ChatGPT login in `CODEX_HOME`; proxy mode remains available through
`CODEX_AUTH_MODE=proxy` for local/API-compatible model routes.

Agent-memory is mounted from `reference_skills` into read-only container paths.
Inside API/agent containers, use the container runtime:

```bash
AGENT_MEMORY_SKILL_DIR=/root/.agents/skills/agent-memory \
python3 /root/.agents/skills/agent-memory/scripts/agent_memory.py --json status
```

Use the skill-local `.venv` only for host/workstation management after
installing `reference_skills/agent-memory/requirements.txt`. Set
`AGENT_MEMORY_LOG_DIR` to a writable path such as `/tmp/agent-memory/logs` if
running the CLI in a read-only mounted skill tree.

Current lab route switch, for operators or agents using the `server-manager`
skill:

```bash
cd /home/cereal/SOC_TESTING/soc-dashboard
python3 scripts/switch_model_route.py --route external --restart
python3 scripts/switch_model_route.py --route local --restart
```

Verify the current live route from the AI server:

```bash
curl -sS http://127.0.0.1:4001/health
curl -sS -X POST http://127.0.0.1:4001/api/route \
  -H 'Content-Type: application/json' \
  -d '{"model":"deepseek/deepseek-v4-flash"}'
```

In the current lab, the proxy host port is intentionally bound to
`0.0.0.0:4001` so tools outside the dashboard harness can use the same managed
proxy. Dashboard/API containers use `http://ai-proxy:4001`. There should be no
separate standalone `ai-proxy` container and no host `4401` listener in this
setup.

## HTTPS Edge

The default deployment exposes the operator UI through `dashboard-tls-proxy`
on `DASHBOARD_HTTPS_PORT` and keeps direct FastAPI HTTP on loopback for local
containers, scripts, and agents. Do not bind the dashboard to standard `443`
by default; customer environments often already use it for an enterprise proxy
or another product. Generate runtime-only local CA and server certs before
starting compose:

```bash
python3 scripts/generate_dashboard_tls.py --out-dir runtime/tls
docker compose up -d --build
python3 scripts/smoke_dashboard_https.py https://localhost:${DASHBOARD_HTTPS_PORT:-25443}
```

The generated `runtime/tls/dashboard-ca.crt` can be imported into a demo
workstation trust store so browsers stop showing a certificate warning. On
Windows, copy or download the CA cert locally and run:

```powershell
.\scripts\install_dashboard_ca_windows.ps1 -CertPath .\runtime\trusted-ca\dashboard-ca.crt
```

`runtime/tls/dashboard.key` and `runtime/tls/dashboard-ca.key` are secret
runtime material and must never be committed. For production, replace the
runtime certs with enterprise PKI or ACME-issued certificates and keep
`DASHBOARD_COOKIE_SECURE=true`.

## Ops Chat Reference Deployment

Ops Chat is the Matrix/Element user-facing intake path. It is part of the
reference deployment, not a separate demo shim. The stack is:

- `ops-chat`: Element Web UI.
- `ops-chat-synapse`: Matrix homeserver.
- `ops-chat-db`: PostgreSQL database for Synapse only.
- `ops-chat-bridge`: Matrix appservice bridge into the dashboard.
- Keycloak: OIDC identity provider.
- Dashboard API: canonical ticket, note, agent, provider-sync, and audit system.

Default browser URL:

```text
https://<host>:3303/#/user/@agentic-ops:agentic-ops.local
```

The older `http://<host>:3301` listener is only a compatibility redirect to the
HTTPS Element UI. Do not use it as the demo entry point. Direct Synapse
diagnostics remain available on `https://<host>:3302`, while browser Matrix
client calls should use the same-origin Element path
`https://<host>:3303/_matrix/client/versions`.

Required environment values:

```text
OPS_CHAT_PORT=3301
OPS_CHAT_HTTPS_PORT=3303
OPS_CHAT_SYNAPSE_PORT=3302
MATRIX_SERVER_NAME=agentic-ops.local
MATRIX_PUBLIC_BASEURL=https://<host>:3303
MATRIX_ELEMENT_PUBLIC_URL=https://<host>:3303
MATRIX_OIDC_ISSUER=https://<host>:8443/realms/<realm>
MATRIX_OIDC_CLIENT_ID=agentic-ops-chat
MATRIX_OIDC_CLIENT_SECRET=<from vault/runtime secret>
MATRIX_OIDC_CA_CERT_PATH=./runtime/tls/dashboard-ca.crt
MATRIX_AS_TOKEN=<from vault/runtime secret>
MATRIX_HS_TOKEN=<from vault/runtime secret>
OPS_CHAT_AGENT_MODEL=<active route model>
OPS_CHAT_OUTBOUND_ENABLED=true
OPS_CHAT_UPLOAD_DIR=/app/data/ops_chat_uploads
OPS_CHAT_ARTIFACT_DIR=/app/data/ops_chat_artifacts
OPS_CHAT_MAX_ATTACHMENT_BYTES=10485760
OPS_CHAT_MAX_ARTIFACT_INLINE_BYTES=8388608
```

Deployment:

```bash
docker compose up -d --build ops-chat-db ops-chat-synapse ops-chat-bridge ops-chat
python3 scripts/setup_ops_chat_keycloak.py
```

Validation:

```bash
curl -sk https://<host>:3303/config.json
curl -sk https://<host>:3303/_matrix/client/versions
curl -sk https://<host>:3302/_matrix/client/versions
curl -sS -H "X-Dashboard-Service-Token: $DASHBOARD_SERVICE_TOKEN" \
  http://127.0.0.1:25480/api/ops-chat/matrix/health
```

The chat intake turn is harness-driven. The Matrix bridge sends messages to
`/api/ops-chat/message`, the dashboard invokes Hermes, Claude Code, or Codex with the
`ops_chat_tool.py` toolbelt, and the chat agent either answers directly or uses
the tool to create a traceable ticket. Do not replace this with an app-side JSON
classifier. Risky actions still require real downstream barriers: access
requests, scoped credential leases, provider permission failures, workflow
policy, and approval gates.

Harness selection is deployment-configurable. Leave `OPS_CHAT_AGENT_HARNESS`
blank to follow the global `AGENT_HARNESS` default, or set it to `hermes`,
`claude-code`, or `codex` for an entire bridge instance. Targeted tests can also
send `harness` / `agent_harness` and `model` / `agent_model` directly to
`POST /api/ops-chat/message`. This is intentionally a small selector over the
same bridge contract; do not fork the chat bridge for Codex.

Local agent chat turns are allowed to run for one hour by default:
`OPS_CHAT_GENERAL_AGENT_TIMEOUT_SECONDS=3600`,
`OPS_CHAT_INTAKE_AGENT_TIMEOUT_SECONDS=3600`, and
`OPS_CHAT_DASHBOARD_TIMEOUT_SECONDS=3600`. Element users see Matrix typing plus
the working acknowledgement while the harness runs. Short demo/client timeouts
make local agents look broken and can strand child processes, so keep these
values at one hour unless the deployment has a separate supervisor policy.

Matrix file/image/video/audio uploads are part of the reference deployment.
The bridge downloads the Matrix upload and sends it to the dashboard; the
dashboard stores it under `OPS_CHAT_UPLOAD_DIR`, copies it into the harness
workspace under `attachments/`, and links it to created/continued tickets as
attachment metadata. Agent-generated artifacts from `validate-artifact` are
persisted under `OPS_CHAT_ARTIFACT_DIR` and small files are uploaded back into
Element. Uploaded files are untrusted input; agents must not execute embedded
macros, links, shell snippets, or instructions unless a workflow and platform
gate explicitly allow that action.

Current lab proof is documented in
`docs/OPS_CHAT_AGENTIC_UI_TESTING_AND_DEMO_READINESS.md`. The most recent
checkpoint includes:

- Element browser send marker `ops-chat-playwright-1779301274503`, ticket
  `1177`.
- Clarification, iTop sync, and reassignment proof on ticket `1176`, iTop ref
  `595`.
- Real Hermes chat/ticket agents on tickets `1185` and `1191`.
- Broad no-spawn scenario coverage marker `ops-chat-scenarios-1779302571`.

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
- operator browser UI uses HTTPS through `dashboard-tls-proxy`; unauthenticated
  browser UI requests redirect to `/login`; direct static, health, and API
  requests return `403`
- first-party `/login` uses vault-backed local dashboard users and signs a
  HttpOnly `dashboard_session` cookie for the UI/WebSocket flow
- dashboard PostgreSQL, agent-memory PostgreSQL, and the AI proxy are bound to
  localhost on the AI Server
- run `python scripts/smoke_dashboard_auth_enforcement.py http://192.168.50.222:25480`
  with `DASHBOARD_TRUSTED_AUTH_SECRET` and `DASHBOARD_SERVICE_TOKEN` sourced
  from the credential vault before regulated demos
- run `python scripts/smoke_dashboard_login.py http://192.168.50.222:25480 --username demo_account_1 --password-file <temp-vault-password-file>`
  to prove login, bad-credential redirect, signed session cookie, and
  `/api/access/me`
- run `python scripts/smoke_dashboard_https.py https://192.168.50.222:25443`
  to prove the TLS edge, secure redirect behavior, and security headers. After
  trusting `dashboard-ca.crt`, also verify a normal TLS client reaches
  `https://192.168.50.222:25443/nginx-health` without `--insecure`.
- run `python scripts/smoke_setup_agent.py http://192.168.50.222:25480 local/agent-default`
  to prove a real Hermes worker can use scoped agent-session auth against
  protected dashboard endpoints. Latest live proof after the login deployment:
  ticket `611`, agent `246`, task `243`, completed with the expected agent
  note and checkpoint, then ticket `611` was resolved locally.
- run `python scripts/smoke_permission_provider_matrix.py http://192.168.50.222:25480 --model deepseek/deepseek-v4-flash`
  to prove RBAC, row-level separation, vault lease denial/grant, and access
  request gates

## Reference Module Login Validation

The lab demo account is `demo_account_1`; its password lives only in the local
server-manager vault key `demo_account_1`. Do not commit or print the value.

Latest live credential smoke on 2026-05-18:

| Module | Check | Result |
| --- | --- | --- |
| Agentic Operations | First-party login page and signed session | PASS, `/` redirects to `/login`, bad credentials redirect to `/login?error=1`, `demo_account_1` lands in the dashboard as `platform-admin`, sidebar shows the account, logout returns to login |
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
