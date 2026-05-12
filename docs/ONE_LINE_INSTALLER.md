# One-Line Installer

The installer deploys the control plane and writes an initial setup plan. It does not assume the customer wants the reference open-source stack. Product choices are made in the Setup page and tracked as tickets.

## Local Linux Install

From a checked-out release:

```bash
./install.sh --profile soc --ai-base-url http://YOUR_AI_PROXY:4001
```

Dry run:

```bash
./install.sh --dry-run --no-start --profile minimal
```

## Local Windows Install

```powershell
.\install.ps1 --profile soc --ai-base-url http://YOUR_AI_PROXY:4001
```

## Remote Curl Form

When this repo is published behind an internal release URL:

```bash
curl -fsSL https://YOUR_RELEASE_HOST/soc-dashboard/install.sh | bash -s -- --profile soc --ai-base-url http://YOUR_AI_PROXY:4001
```

## Important Flags

- `--profile minimal|soc|full-it`: chooses the initial setup plan.
- `--target PATH`: installation directory.
- `--dashboard-port PORT`: host port for the UI/API.
- `--db-port PORT`: host port for PostgreSQL.
- `--project-name NAME`: Docker Compose project name. Defaults to a sanitized name from the target directory.
- `--ai-base-url URL`: local or external model gateway endpoint.
- `--model MODEL_ID`: default agent model recorded in the setup plan.
- `--itop-sync-enabled true|false`: defaults to false for product-agnostic fresh installs.
- `--no-start`: prepare files without starting Docker.
- `--dry-run`: validate installer behavior without writing or starting containers.

## Generated Files

- `.env`: local runtime config. The installer generates a random PostgreSQL password at install time. Product credentials must be added through environment management or vault references.
- `AGENT_MEMORY_DB_PASSWORD`: generated in `.env` for the shared PostgreSQL/pgvector agent memory service.
- `docker-compose.override.yml`: reserved for site-specific overrides.
- `runtime/empty_credentials.json`: empty placeholder so the control plane can start before Claude Code OAuth credentials are configured.
- `runtime/claude_settings.json`: generated model/proxy settings for the runner.
- `install_state/install-log.jsonl`: installer events.
- `install_state/last-plan.json`: initial profile plan.

## Post-Install

1. Open the dashboard URL printed by the installer.
2. Go to Setup.
3. Mark existing products by capability, for example existing ServiceNow, Splunk, Defender, Proofpoint, Okta, or GitHub.
4. Leave reference modules enabled only for gaps you want the platform to deploy.
5. Create a setup ticket.
6. Assign an agent only after the AI endpoint and approval policy are ready.

The setup ticket becomes the auditable deployment record. Agents must request changes before modifying infrastructure.

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

The latest full one-line install proof used:

```bash
cd /home/cereal/SOC_TESTING/soc-dashboard
./install.sh \
  --profile soc \
  --source /home/cereal/SOC_TESTING/soc-dashboard \
  --target /home/cereal/SOC_TESTING/soc-dashboard-install-e2e-20260512 \
  --dashboard-port 25482 \
  --db-port 5435 \
  --project-name soc-dashboard-e2e-20260512 \
  --ai-base-url http://192.168.50.222:4001 \
  --model qwen/qwen3.6-27b \
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
python3 scripts/smoke_local_model_agent.py "$BASE" qwen/qwen3.6-27b
python3 scripts/smoke_setup_agent.py "$BASE" qwen/qwen3.6-27b
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

The shim blueprint is documented in `docs/MAILCOW_API_SHIM.md`. It covers endpoint contracts, security posture, rollback, troubleshooting, and the difference between the Mailcow reference implementation and the provider-agnostic email capability contract.

Latest dry-run proof:

```powershell
python installer\bootstrap.py --dry-run --profile soc --target C:\Users\cereal\AppData\Local\Temp\soc-platform-dryrun --dashboard-port 25580 --db-port 55433 --ai-base-url http://192.168.50.222:4001 --model qwen/qwen3.6-27b
```

Expected result: JSON status `dry_run`, dashboard URL `http://localhost:25580`, and no files or containers created.
