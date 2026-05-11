# Testing Runbook

Last updated: 2026-05-11.

## Local Source Validation

From the workspace root:

```powershell
python -m compileall .\soc-dashboard\api
node --check .\soc-dashboard\frontend\js\dashboard.js
node --check .\soc-dashboard\frontend\js\agents.js
node --check .\soc-dashboard\frontend\js\charts.js
node --check .\soc-dashboard\frontend\js\websocket.js
python -m py_compile .\soc-dashboard\scripts\smoke_agentic_system.py .\soc-dashboard\scripts\smoke_local_model_agent.py .\soc-dashboard\scripts\smoke_service_desk_intake.py .\soc-dashboard\scripts\smoke_cicd_security_pipeline.py .\soc-dashboard\scripts\run_cicd_security_pipeline.py
```

## Prohibited Pattern Sweep

Application code should not contain ORM/Pydantic/SQLAlchemy usage or hardcoded secrets.

```powershell
rg -n --glob '!README.md' --glob '!*.md' --glob '!__pycache__/**' "pydantic|sqlalchemy|sk-[A-Za-z0-9]{20,}|host\.docker|docker\.internal|soc_password_change_me|itop_admin" .\soc-dashboard\api .\soc-dashboard\frontend .\soc-dashboard\scripts .\soc-dashboard\docker-compose.yml
```

Expected result: no matches.

The database cleanup text may intentionally mention ComfyUI in `init_db.sql` only to remove it from inventory.

## Server Health

```bash
curl -sS http://localhost:25480/health
curl -sS http://localhost:25480/api/agents/runner-health
curl -sS http://localhost:25480/api/agents/processes
```

Expected:

- API status `ok`
- runner harness configured
- model API reachable
- `ps_path` present
- no active processes after completed smoke tests

## Cross-Platform Demo Credential Smoke

Credential value lives in the local encrypted vault key `demo_account_1`. Do not print it.

Latest verified result on 2026-05-11:

```text
wazuh_api: PASS http=200
itop_rest: PASS code=0
gitlab_password: PASS active=true admin=true
wazuh_dashboard_backend: PASS
mailcow_mailbox: PASS exists
```

Important implementation notes:

- Wazuh user/password sync should use the native Wazuh API first.
- Wazuh Dashboard auth also requires OpenSearch Security `internal_users.yml` sync and `securityadmin.sh` reload.
- iTop demo users must be real `UserLocal` objects with `Administrator` and `REST Services User`; raw partial rows can be counted by OQL but fail object reload and login.
- If a failed iTop debug trace logs a password in `/var/www/html/log/error.log`, rotate the vault key and scrub the log before demo use.

## Agentic API Smoke

```bash
cd /home/cereal/SOC_TESTING/soc-dashboard
python3 scripts/smoke_agentic_system.py http://localhost:25480
```

Covers:

- health
- provider registry
- local ticket creation
- local provider outbound create/push contract
- notes
- attachment metadata
- knowledge articles
- skills
- approval-gated changes
- postmortems
- workflows and review
- context bundle
- process diagnostics

## Service Desk Intake Smoke

```bash
cd /home/cereal/SOC_TESTING/soc-dashboard
python3 scripts/smoke_service_desk_intake.py http://localhost:25480
```

Covers:

- seeded service groups
- seeded RACI rules
- phishing classification
- canonical ticket creation
- attachment metadata
- approval gate creation
- ticket context and intake session visibility

## CI/CD Security Pipeline Smoke

```bash
cd /home/cereal/SOC_TESTING/soc-dashboard
python3 scripts/smoke_cicd_security_pipeline.py http://localhost:25480
```

Covers:

- GitLab-default pipeline template
- Semgrep, Trivy, Nuclei job definitions
- local canonical scanner output
- `/api/cicd/runs` persistence
- evidence ticket creation
- production deployment approval gate

## Local Model Agent Smoke

```bash
cd /home/cereal/SOC_TESTING/soc-dashboard
python3 scripts/smoke_local_model_agent.py http://localhost:25480 qwen/qwen3.6-27b
```

Covers:

- dashboard ticket creation
- Claude Code spawn
- local proxy/model route
- agent reads context via dashboard API
- agent writes a ticket note via dashboard API
- agent writes done checkpoint
- task completes
- tracker terminates harness process
- no active process remains

Latest verified result:

```text
ticket_id=28
agent_id=26
task_id=24
status=completed
progress=100
note_written=true
active_process_count=0
```

## Manual Provider Push Smoke

Local provider:

```bash
ticket_id=$(curl -sS -X POST http://localhost:25480/api/tickets \
  -H 'Content-Type: application/json' \
  -d '{"title":"Local provider push smoke","description":"test","provider":"local","sync_provider":false}' \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["id"])')

curl -sS -X POST http://localhost:25480/api/tickets/$ticket_id/push-provider \
  -H 'Content-Type: application/json' \
  -d '{"provider":"local"}'
```

Expected: `local_only`.

iTop provider:

- requires `ITOP_SYNC_ENABLED=true`
- requires `ITOP_HOST`, `ITOP_USER`, `ITOP_PASSWORD`
- Incident/UserRequest outbound create requires `ITOP_DEFAULT_ORG_ID` and `ITOP_DEFAULT_CALLER_ID`

If defaults are missing, expected status is `create_failed` with a clear `provider_last_error`.
