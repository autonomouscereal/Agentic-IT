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

Multiple installs can run on the same host when different `--target`, `--dashboard-port`, `--db-port`, and optionally `--project-name` values are used. The compose file does not use fixed container names.

## Post-Install Doctor

After the first start, run:

```bash
cd /path/to/soc-platform
python3 scripts/platform_doctor.py --base http://localhost:25480
```

The doctor is read-only. It validates the dashboard, setup manifest, ticket sorting API, iTop UI when configured, optional Mailcow HTTP API shim, CI/CD scanner bundle, AI proxy skill, SearXNG skill, and EDR/Sysmon bundle. Warnings on the optional Mailcow HTTP shim do not block the direct MySQL Mailcow bridge, which remains the reference deployment's canonical Mailcow path.
