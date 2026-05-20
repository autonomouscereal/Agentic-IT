# One-Line Installer

The installer deploys the autonomous enterprise operations control plane,
plants the built-in AI proxy by default, writes an initial setup plan, and
creates the first setup-ticket handoff. It does not try to finish
customer-specific integration work in shell. The shell/Python bootstrap plants
the seed; the platform continues onboarding through auditable setup tickets
with approval gates.

The near-term installer proves the SOC/IT seed domain. The long-term installer
is the bootstrap for a private agentic operations layer that can connect to an
existing enterprise, deploy approved reference modules for missing capabilities,
and start routing IT, security, DevOps, cloud, network, service desk,
compliance, and maintenance work to governed agents.

## Local Linux Install

From a checked-out release:

```bash
./install.sh --profile soc --proxy-mode deploy --harness auto --model-route local
```

External lab/provider install:

```bash
./install.sh --profile soc --proxy-mode deploy --harness auto --model-route external --provider nous --model deepseek/deepseek-v4-flash
```

Dry run:

```bash
./install.sh --dry-run --no-start --profile minimal
./install.sh --dry-run --profile full-it --harness hermes --proxy-mode deploy
```

## Local Windows Install

```powershell
.\install.ps1 --profile soc --proxy-mode deploy --harness auto --model-route local
```

## Remote Curl Form

When this repo is published behind an internal release URL:

```bash
curl -fsSL https://YOUR_RELEASE_HOST/agentic-ops/install.sh | bash -s -- --profile soc --proxy-mode deploy --harness auto --model-route local
```

## Important Flags

- `--profile minimal|soc|full-it`: chooses the initial setup plan.
- `--target PATH`: installation directory.
- `--dashboard-port PORT`: host port for the UI/API.
- `--https-port PORT`: host port for the operator-facing HTTPS UI, default
  `25443`.
- `--disable-https`: skip the bundled TLS proxy; intended only for local
  development behind another trusted reverse proxy.
- `--tls-common-name NAME`: common name used for the generated local-CA signed
  certificate.
- `--tls-days DAYS`: server certificate lifetime, default `825`.
- `--db-port PORT`: host port for PostgreSQL.
- `--memory-db-port PORT`: host port for the bundled PostgreSQL/pgvector agent
  memory database, default `25490`. Use this when reinstalling on a host that
  already has a separate memory service or another lab stack bound to `25490`.
- `--project-name NAME`: Docker Compose project name. Defaults to a sanitized name from the target directory.
- `--harness auto|hermes|claude-code`: selected agent harness. `auto` prefers Hermes when a host Hermes install is available, otherwise Claude Code.
- `--proxy-mode deploy|external`: deploy the built-in proxy or point the dashboard at an existing proxy.
- `--proxy-port PORT`: host port for the built-in proxy, default `4001`.
  Hardened installs bind the proxy to `127.0.0.1`; the installer checks
  `http://localhost:<port>` from the deployment host even when the dashboard
  HTTPS URL is LAN-facing.
- `--model-route local|external`: deployment posture for the generated proxy
  config. `local` is the product default and routes generic aliases through
  the local/on-prem gateway. `external` enables the configured cloud/lab route
  and its fallbacks.
- `--provider openai|anthropic|nous|lmstudio|custom`: provider for the active
  route. Defaults to `lmstudio` when `--model-route local`; use `nous`,
  `openai`, `anthropic`, or `custom` only when external routing is allowed.
- `--provider-base-url URL`: provider base URL override for custom/external routes.
- `--ai-base-url URL`: external proxy compatibility endpoint. Built-in proxy
  mode uses `http://ai-proxy:4001` inside Docker and prints a deployment-host
  local proxy URL such as `http://localhost:4001`.
- If the host port has to move because another proxy already owns `4001`, keep
  `AGENT_LLM_BASE_URL=http://ai-proxy:4001` for containers and change only the
  deployment-host local `--proxy-port` / `AI_PROXY_PORT` value.
- `--model MODEL_ID`: default agent model recorded in the setup plan. The
  local default is `local/agent-default`; the lab external example is
  `deepseek/deepseek-v4-flash`.
- `--spawn-setup-agent`: create the setup ticket and immediately assign the onboarding agent.
- `--itop-sync-enabled true|false`: defaults to false for product-agnostic fresh installs.
- `--no-start`: prepare files without starting Docker.
- `--dry-run`: validate installer behavior without writing or starting containers.

## Generated Files

- `.env`: local runtime config. The installer generates a random PostgreSQL password at install time. Product credentials must be added through environment management or vault references.
- `runtime/tls/dashboard-ca.crt`, `runtime/tls/dashboard-ca.key`,
  `runtime/tls/dashboard.crt`, and `runtime/tls/dashboard.key`: runtime-only
  local CA and HTTPS assets for the dashboard TLS proxy. Trust
  `dashboard-ca.crt` on demo workstations; key files must never leave the
  deployment host.
- `AGENT_MEMORY_DB_PASSWORD`: generated in `.env` for the shared PostgreSQL/pgvector agent memory service.
- `docker-compose.override.yml`: reserved for site-specific overrides.
- `runtime/empty_credentials.json`: empty placeholder so the control plane can start before Claude Code OAuth credentials are configured.
- `runtime/claude_settings.json`: generated model/proxy settings for Claude Code fallback runs.
- `runtime/proxy_config.json`: generated provider/model routing config for the built-in AI proxy. It contains aliases and base URLs, not secrets.
- Hermes auth state is mounted from the operator/host runtime when Hermes is selected; the installer does not write Nous Portal tokens into source-controlled files.
- `install_state/install-log.jsonl`: installer events.
- `install_state/last-plan.json`: initial profile plan.

## Model Routing Posture

Fresh product installs are local/on-prem first:

```ini
AI_MODEL_ROUTE=local
AI_PROXY_MODEL_ROUTE=local
AI_PROXY_EXTERNAL_ENABLED=false
AGENT_DEFAULT_MODEL=local/agent-default
HERMES_DEFAULT_PROVIDER=dashboard-proxy
```

That posture keeps generic aliases such as `local/agent-default`,
`default`, and the current lab model aliases on the local gateway unless an
operator explicitly enables external routing. For lab demos where external
providers are approved, flip the route:

```bash
python scripts/switch_model_route.py --route external --restart
python scripts/switch_model_route.py --route local --restart
```

The switch updates `.env`, `runtime/proxy_config.json`, and
`agent_models.json`; it does not write or rotate provider secrets. External
routes can use Nous/OpenRouter/OpenAI/Anthropic/custom providers when runtime
vault/environment credentials are present. Local/on-prem deployments can point
`LM_STUDIO_BASE` or the generated provider base URL at LM Studio, vLLM, Ollama
with an OpenAI-compatible shim, Azure OpenAI on a private endpoint, or another
customer-managed gateway.

Run the switch from the installed deployment directory, not from an arbitrary
source checkout. With `--restart`, the script verifies required runtime env
values such as `SOC_DB_PASSWORD` before editing files and restarting Compose.
On the current lab server that means:

```bash
cd /home/cereal/SOC_TESTING/soc-dashboard
python3 scripts/switch_model_route.py --route external --restart
python3 scripts/switch_model_route.py --route local --restart
```

Agents should execute the same commands through the `server-manager` skill
against server `ai`. After switching, verify from the AI server with
`curl http://127.0.0.1:4001/health` and `POST /api/route`; the live lab maps
the Compose-managed proxy to host/LAN port `4001`, and containers use
`http://ai-proxy:4001`.

## Post-Install

1. Open the HTTPS dashboard URL printed by the installer. For default local-CA
   installs, import `runtime/tls/dashboard-ca.crt` into the operator
   workstation trust store to avoid browser warnings.
2. Go to Setup.
3. Choose scope for each module:
   - `Deploy reference` when the organization wants the bundled open-source
     module installed or managed.
   - `Integrate existing` when the organization already has an equivalent
     enterprise tool such as ServiceNow, Splunk, Defender, Proofpoint, Okta,
     GitHub, Entra ID, AWS, Azure, GCP, Kubernetes, M365, or network/security
     tooling.
   - `Off / not in scope` when the organization does not want that capability
     deployed or integrated in this environment.
4. Leave reference modules enabled only for gaps you want the platform to
   deploy. Disabled modules are omitted from setup work, and dependent modules
   are shown as blocked by disabled dependencies.
5. Review the parent setup ticket and the scoped module setup tickets created
   by the installer or Setup page.
6. Assign or resume the setup agent when model credentials and approval policy
   are ready. If `--spawn-setup-agent` was used, the first agent run is a
   bounded bootstrap verification: it reads the setup ticket, runner health,
   manifest, and profiles, writes a `SETUP_ONBOARDING_BOOTSTRAP_COMPLETE`
   note, and stops with a 100% checkpoint. Follow-on deployment/integration
   work should be spawned from that ticket with explicit approvals.

The parent setup ticket becomes the auditable deployment record. Each scoped
child ticket owns one module or integration so agents can work iTop, Wazuh,
Mailcow, GitLab, Keycloak, proxy, bridge, email, CI/CD, and optional modules
without mixing evidence. The onboarding agent must inspect installed modules,
verify proxy and harness health, run model and spawn smoke tests, propose
missing integrations, request access/credential approvals, and record
notes/postmortems/workflows before marking setup complete. Agents must request
changes before modifying infrastructure.

Operators can also work one module at a time from Setup. Each module card shows
the inferred deployment status, a module-specific notes box, and buttons to
create a deploy/integrate ticket, create and assign an agent, undeploy, or
reinstall. Use this path when a customer wants to integrate just one provider,
change one port/credential mapping, or migrate from a reference module to an
existing enterprise product without recreating the whole setup plan.

The installer also deploys `agent-memory-db`, registers **Agent Memory** on the Tools page, and wires spawned dashboard agents to the `agent-memory` skill. Agent prompts, tool calls, session stops, deliberate notes, and smoke-test sentinels are stored in the shared memory service with async PostgreSQL writes, JSONB metadata, full-text search, trigram search, and pgvector retrieval. Running **Tools -> Check All** should report Agent Memory as healthy when the database service is deployed.

When `ops-chat-client` is in scope, Compose deploys Element Web, Matrix Synapse,
and the Ops Chat Matrix bridge. Synapse delegates user login to Keycloak OIDC,
while the bridge delivers room messages to the dashboard-owned Ops Chat endpoint.
Operational chat creates traceable tickets and queues real Hermes/Claude Code
agent harness tasks through the configured AI proxy instead of a separate hidden
bot workflow.

The reference chat deployment serves Element on HTTPS port `3303`; HTTP port
`3301` redirects to that UI. Element also proxies `/_matrix/` and `/_synapse/`
to Synapse on the same browser origin, so `MATRIX_PUBLIC_BASEURL` and
`MATRIX_ELEMENT_PUBLIC_URL` should both point at `https://<host>:3303`.
Synapse's direct HTTPS port `3302` remains available for diagnostics, while the
bridge uses Synapse's internal HTTP listener.

Keep the chat URLs browser-routable and HTTPS before running
`scripts/setup_ops_chat_keycloak.py`. If the installer also deploys or manages
the Keycloak edge, Keycloak should use the same runtime CA chain as the
dashboard or another CA supplied through `MATRIX_OIDC_CA_CERT_PATH`. Synapse
installs that CA in the container trust bundle before OIDC token exchange. Do
not disable TLS verification to make a demo work.

Multiple installs can run on the same host when different `--target`, `--dashboard-port`, `--db-port`, and optionally `--project-name` values are used. The compose file does not use fixed container names.

## Post-Install Doctor

After the first start, run:

```bash
cd /path/to/soc-platform
python3 scripts/platform_doctor.py --base http://localhost:25480
```

The doctor is read-only. It validates the dashboard, setup manifest, ticket sorting API, provider adapters, iTop UI when configured, optional Mailcow HTTP API domain/mailbox/alias counts, CI/CD scanner bundle, AI proxy skill, SearXNG skill, and EDR/Sysmon bundle. Warnings on the optional Mailcow HTTP shim do not block the direct MySQL Mailcow bridge, which remains the reference deployment's canonical Mailcow path.

## Full Post-Install Regression

The current source-level dry-run acceptance is:

```bash
python installer/bootstrap.py --dry-run --profile minimal
python installer/bootstrap.py --dry-run --profile full-it --harness hermes --proxy-mode deploy
```

Expected result: JSON status `dry_run`, a generated proxy config summary,
selected harness/model, proxy URL, HTTPS dashboard URL, TLS summary, and a
dry-run setup-ticket handoff payload. Runtime setup ticket creation returns a
`parent_ticket` plus `module_tickets` for actionable deploy/integrate modules;
steps turned off by `module_actions` are reported in `disabled_modules`, and
dependent steps are reported as `blocked_disabled_dependency`.

The previous full one-line install proof used:

```bash
cd /home/cereal/SOC_TESTING/soc-dashboard
./install.sh \
  --profile soc \
  --source /home/cereal/SOC_TESTING/soc-dashboard \
  --target /home/cereal/SOC_TESTING/soc-dashboard-install-e2e-20260512 \
  --dashboard-port 25482 \
  --db-port 5435 \
  --memory-db-port 25492 \
  --project-name soc-dashboard-e2e-20260512 \
  --proxy-mode deploy \
  --proxy-port 4001 \
  --harness hermes \
  --model-route local \
  --provider lmstudio \
  --model local/agent-default \
  --itop-sync-enabled false \
  --non-interactive
```

Then run the installed-stack checks:

```bash
cd /home/cereal/SOC_TESTING/soc-dashboard-install-e2e-20260512
BASE=http://localhost:25482
python3 scripts/platform_doctor.py --base "$BASE"
python3 scripts/smoke_setup_platform.py "$BASE"
python3 scripts/smoke_provider_adapters.py "$BASE"
python3 scripts/smoke_service_desk_intake.py "$BASE"
python3 scripts/smoke_agentic_system.py "$BASE"
python3 scripts/smoke_phishing_workflow_lifecycle.py "$BASE"
python3 scripts/smoke_cicd_security_pipeline.py "$BASE"
python3 scripts/smoke_agent_auditor.py "$BASE"
docker compose cp scripts/smoke_change_auto_completion.py api:/app/smoke_change_auto_completion.py
docker compose exec -T api python /app/smoke_change_auto_completion.py
python3 scripts/smoke_local_model_agent.py "$BASE" local/agent-default
python3 scripts/smoke_setup_agent.py "$BASE" local/agent-default
docker compose exec -T api python /root/.claude/skills/agent-memory/scripts/agent_memory.py --json status
```

Run the real local-model CI/CD remediation demo:

```bash
SOC_DASHBOARD_URL="$BASE" \
AGENT_MODEL=qwen/qwen3.6-27b \
CICD_DOCKER_NETWORK=host \
python3 scripts/agentic_cicd_full_demo.py \
  --base "$BASE" \
  --host-ip 192.168.50.222 \
  --timeout 2400
```

Latest verified full demo: ticket `13`, initial gate failed, remediation agent
`7` completed, final gate passed with zero high/critical findings, changes `8`
and `9` completed, postmortem `4` reached `ready_for_review`, and
`/api/agents/processes` returned no active processes.

## Optional Mailcow API Shim

When the setup plan includes the reference Mailcow email module, the platform can also deploy the optional HTTP compatibility shim for tools that expect Mailcow-style API reads. The shim is not the canonical write path; provisioning and Keycloak sync still use the direct MySQL bridge in the reference deployment.

Reference deployment and validation:

```bash
cd /home/cereal/Mailcow/deploy
python3 scripts/deploy_mailcow_api.py
python3 scripts/test_mailcow_api_shim.py --mysql-parity
```

The shim blueprint is documented in `docs/MAILCOW_API_SHIM.md`. It covers endpoint contracts, security posture, rollback, troubleshooting, demo UI repair, Roundcube webmail deployment, and the difference between the Mailcow reference implementation and the provider-agnostic email capability contract. The 2026-05-18 deployer also repairs UI schema drift, deploys `roundcube-mailcow-demo`, validates that `/webmail/` renders Roundcube, and checks that the Mailcow admin pages do not show invalid JSON/DataTables or SQL-column warnings after login. The dashboard Tools inventory should show `Mailcow API/UI Shim` and `Roundcube Webmail` after `/api/tools/sync-manifest` runs.

Latest dry-run proof:

```powershell
python installer\bootstrap.py --dry-run --profile full-it --harness hermes --proxy-mode deploy --model-route local --target C:\Users\cereal\AppData\Local\Temp\soc-platform-dryrun --dashboard-port 25580 --db-port 55433 --model local/agent-default
```

Expected result: JSON status `dry_run`, dashboard URL
`http://localhost:25580`, HTTPS dashboard URL `https://localhost:25443`, TLS
summary `dry_run`, and no files or containers created.
