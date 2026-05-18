# One-Line Installer

The installer deploys the autonomous enterprise operations control plane,
plants the built-in AI proxy by default, writes an initial setup plan, and
creates the first setup ticket. It does not try to finish customer-specific
integration work in shell. The shell/Python bootstrap plants the seed; the
platform agent continues onboarding from the setup ticket with approval gates.

The near-term installer proves the SOC/IT seed domain. The long-term installer
is the bootstrap for a private agentic operations layer that can connect to an
existing enterprise, deploy approved reference modules for missing capabilities,
and start routing IT, security, DevOps, cloud, network, service desk,
compliance, and maintenance work to governed agents.

## Local Linux Install

From a checked-out release:

```bash
./install.sh --profile soc --proxy-mode deploy --harness auto --provider nous --model deepseek/deepseek-v4-flash
```

Default proxy-first install:

```bash
./install.sh --profile soc --proxy-mode deploy --harness auto --provider nous --model deepseek/deepseek-v4-flash
```

Dry run:

```bash
./install.sh --dry-run --no-start --profile minimal
./install.sh --dry-run --profile full-it --harness hermes --proxy-mode deploy
```

## Local Windows Install

```powershell
.\install.ps1 --profile soc --proxy-mode deploy --harness auto --provider nous --model deepseek/deepseek-v4-flash
```

## Remote Curl Form

When this repo is published behind an internal release URL:

```bash
curl -fsSL https://YOUR_RELEASE_HOST/agentic-ops/install.sh | bash -s -- --profile soc --proxy-mode deploy --harness auto --provider nous --model deepseek/deepseek-v4-flash
```

## Important Flags

- `--profile minimal|soc|full-it`: chooses the initial setup plan.
- `--target PATH`: installation directory.
- `--dashboard-port PORT`: host port for the UI/API.
- `--db-port PORT`: host port for PostgreSQL.
- `--project-name NAME`: Docker Compose project name. Defaults to a sanitized name from the target directory.
- `--harness auto|hermes|claude-code`: selected agent harness. `auto` prefers Hermes when a host Hermes install is available, otherwise Claude Code.
- `--proxy-mode deploy|external`: deploy the built-in proxy or point the dashboard at an existing proxy.
- `--proxy-port PORT`: host port for the built-in proxy, default `4001`.
- `--provider openai|anthropic|nous|lmstudio|custom`: default provider route in the generated proxy config.
- `--provider-base-url URL`: provider base URL override for custom/external routes.
- `--ai-base-url URL`: external proxy compatibility endpoint. Built-in proxy mode uses `http://ai-proxy:4001` inside Docker and prints a host-facing proxy URL.
- `--model MODEL_ID`: default agent model recorded in the setup plan.
- `--spawn-setup-agent`: create the setup ticket and immediately assign the onboarding agent.
- `--itop-sync-enabled true|false`: defaults to false for product-agnostic fresh installs.
- `--no-start`: prepare files without starting Docker.
- `--dry-run`: validate installer behavior without writing or starting containers.

## Generated Files

- `.env`: local runtime config. The installer generates a random PostgreSQL password at install time. Product credentials must be added through environment management or vault references.
- `AGENT_MEMORY_DB_PASSWORD`: generated in `.env` for the shared PostgreSQL/pgvector agent memory service.
- `docker-compose.override.yml`: reserved for site-specific overrides.
- `runtime/empty_credentials.json`: empty placeholder so the control plane can start before Claude Code OAuth credentials are configured.
- `runtime/claude_settings.json`: generated model/proxy settings for Claude Code fallback runs.
- `runtime/proxy_config.json`: generated provider/model routing config for the built-in AI proxy. It contains aliases and base URLs, not secrets.
- Hermes auth state is mounted from the operator/host runtime when Hermes is selected; the installer does not write Nous Portal tokens into source-controlled files.
- `install_state/install-log.jsonl`: installer events.
- `install_state/last-plan.json`: initial profile plan.

## Post-Install

1. Open the dashboard URL printed by the installer.
2. Go to Setup.
3. Mark existing products by capability, for example existing ServiceNow,
   Splunk, Defender, Proofpoint, Okta, GitHub, Entra ID, AWS, Azure, GCP,
   Kubernetes, M365, or network/security tooling.
4. Leave reference modules enabled only for gaps you want the platform to deploy.
5. Review the setup ticket/work item created by the installer.
6. Assign or resume the setup agent when model credentials and approval policy are ready. If `--spawn-setup-agent` was used, the agent starts immediately or records a clear missing-credential/access reason.

The setup ticket becomes the auditable deployment record. The onboarding agent must inspect installed modules, verify proxy and harness health, run model and spawn smoke tests, propose missing integrations, request access/credential approvals, and record notes/postmortems/workflows before marking setup complete. Agents must request changes before modifying infrastructure.

The installer also deploys `agent-memory-db`, registers **Agent Memory** on the Tools page, and wires spawned dashboard agents to the `agent-memory` skill. Agent prompts, tool calls, session stops, deliberate notes, and smoke-test sentinels are stored in the shared memory service with async PostgreSQL writes, JSONB metadata, full-text search, trigram search, and pgvector retrieval. Running **Tools -> Check All** should report Agent Memory as healthy when the database service is deployed.

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
selected harness/model, proxy URL, dashboard URL, and a dry-run setup ticket
handoff payload.

The previous full one-line install proof used:

```bash
cd /home/cereal/SOC_TESTING/soc-dashboard
./install.sh \
  --profile soc \
  --source /home/cereal/SOC_TESTING/soc-dashboard \
  --target /home/cereal/SOC_TESTING/soc-dashboard-install-e2e-20260512 \
  --dashboard-port 25482 \
  --db-port 5435 \
  --project-name soc-dashboard-e2e-20260512 \
  --proxy-mode deploy \
  --proxy-port 4001 \
  --harness hermes \
  --provider nous \
  --model deepseek/deepseek-v4-flash \
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
python3 scripts/smoke_local_model_agent.py "$BASE" deepseek/deepseek-v4-flash
python3 scripts/smoke_setup_agent.py "$BASE" deepseek/deepseek-v4-flash
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
python installer\bootstrap.py --dry-run --profile full-it --harness hermes --proxy-mode deploy --target C:\Users\cereal\AppData\Local\Temp\soc-platform-dryrun --dashboard-port 25580 --db-port 55433 --model deepseek/deepseek-v4-flash
```

Expected result: JSON status `dry_run`, dashboard URL `http://localhost:25580`, and no files or containers created.
