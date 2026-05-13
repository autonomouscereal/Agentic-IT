# Testing Runbook

Last updated: 2026-05-12.

## Local Source Validation

From the workspace root:

```powershell
python -m compileall .\soc-dashboard\api
node --check .\soc-dashboard\frontend\js\dashboard.js
node --check .\soc-dashboard\frontend\js\agents.js
node --check .\soc-dashboard\frontend\js\charts.js
node --check .\soc-dashboard\frontend\js\websocket.js
python -m py_compile .\soc-dashboard\scripts\smoke_agentic_system.py .\soc-dashboard\scripts\smoke_local_model_agent.py .\soc-dashboard\scripts\smoke_service_desk_intake.py .\soc-dashboard\scripts\smoke_cicd_security_pipeline.py .\soc-dashboard\scripts\smoke_agent_auditor.py .\soc-dashboard\scripts\smoke_provider_adapters.py .\soc-dashboard\scripts\run_cicd_security_pipeline.py .\soc-dashboard\scripts\agentic_cicd_full_demo.py .\soc-dashboard\scripts\agentic_gitlab_cicd_demo.py .\soc-dashboard\scripts\platform_doctor.py .\soc-dashboard\scripts\repair_agent_supervision_env.py
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
python3 scripts/platform_doctor.py --base http://localhost:25480
```

Expected:

- API status `ok`
- runner harness configured
- model API reachable
- `ps_path` present
- no active processes after completed smoke tests

`platform_doctor.py` is the preferred pre-demo check. It is non-destructive and verifies dashboard health, setup manifest hygiene, ticket sorting, provider adapters, iTop UI reachability, Mailcow HTTP API domain/mailbox/alias counts, scanner skills, AI proxy skill, SearXNG skill, and EDR/Sysmon bundle presence.

Latest verified result on 2026-05-12:

```text
platform_doctor.py: PASS 18, WARN 0, FAIL 0
runner timeout_minutes: 0
default_model: qwen/qwen3.6-27b
effective_anthropic_base_url: http://192.168.50.222:4001
```

## Cross-Platform Demo Credential Smoke

Credential value lives in the local encrypted vault key `demo_account_1`. Do not print it.

Latest verified result on 2026-05-12:

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
- RACI group/rule CRUD
- automatic provider sync fallback to `local_only` when outbound provider
  creation is not fully configured

## RACI Auto-Assignment Policy Smoke

```bash
cd /home/cereal/SOC_TESTING/soc-dashboard
python3 scripts/smoke_auto_assignment_policy.py
```

Covers:

- matching Security Operations phishing tickets auto-spawn exactly one agent
- the policy prompt is included in the standard ticket-resolution prompt
- non-matching tickets remain in the manual queue
- tickets with an existing agent are not duplicated
- an internal ticket note is recorded for the assignment

## Awaiting User Response Smoke

```bash
cd /home/cereal/SOC_TESTING/soc-dashboard
python3 scripts/smoke_user_response_workflow.py http://localhost:25480
```

Covers:

- `/api/tickets/{id}/request-info`
- ticket status `awaiting_user_response`
- requester response notes through `/api/tickets/{id}/user-response`
- restoration of the previous ticket status
- agent-resume-ready note and context behavior

## Provider Adapter Smoke

```bash
cd /home/cereal/SOC_TESTING/soc-dashboard
python3 scripts/smoke_provider_adapters.py http://localhost:25480
```

Covers:

- provider registry lists `local`, `itop`, `servicenow`, `jira`, and `generic-webhook`
- local outbound push remains `local_only`
- ServiceNow/Jira adapters fail closed when not configured
- failed external push records `provider_sync_status=create_failed` and `provider_last_error`

Latest verified result on 2026-05-12:

```text
providers: generic-webhook, itop, jira, local, servicenow
local_push: local_only
servicenow: fail-closed not configured
jira: fail-closed not configured
```

## CI/CD Security Pipeline Smoke

```bash
cd /home/cereal/SOC_TESTING/soc-dashboard
python3 scripts/smoke_cicd_security_pipeline.py http://localhost:25480
```

Covers:

- GitLab-default pipeline template
- Semgrep, Trivy, OWASP ZAP, and Nuclei job definitions
- local canonical scanner output
- `/api/cicd/runs` persistence
- evidence ticket creation
- production deployment approval gate

## Full Agentic CI/CD Remediation

```bash
cd /home/cereal/SOC_TESTING/soc-dashboard
python3 scripts/agentic_cicd_full_demo.py \
  --base http://localhost:25480 \
  --model qwen/qwen3.6-27b \
  --workspace /home/cereal/SOC_TESTING/soc-dashboard/demo_runs
```

Covers:

- real Docker scanner execution for Semgrep, Trivy, OWASP ZAP, and Nuclei
- canonical `/api/cicd/runs` evidence capture
- approval-gated source remediation by a local-model agent
- ticket notes, attachments, change requests, and process logs
- final scanner rerun after agent edits
- local Git branch plus patch artifact for PR/MR demonstration. This is the
  local-only fallback proof; the GitLab runner proof below creates a real
  GitLab project, MR, and branch pipeline.
- postmortem task launch for reusable workflow learning

Latest verified result on 2026-05-11:

```text
ticket_id=82
initial_run_id=8 status=needs_review
agent_id=48 task_id=46 status=completed
remediation_change_id=34 status=approved
final_run_id=10 status=passed
deployment_change_id=36 status=completed
branch=agent/remediate-security-gate
patch=/home/cereal/SOC_TESTING/soc-dashboard/agent_work/48/agent-remediation.patch
```

Notes from the live run:

- The API container creates agent work directories as root. The demo harness
  repairs host write permissions with `docker exec soc-dashboard-api-1 chown`
  before seeding the agent repo.
- Recreating the API container while an agent is running kills that harness
  process. Do not rebuild the API during the middle of a live model demo.
- ZAP exit code `2` is warnings-found, not scanner failure.
- The Trivy Docker image command should be `fs ...` because the image entrypoint
  is already `trivy`.

## Wazuh EDR/Sysmon E2E

```bash
cd /home/cereal/SOC_TESTING/soc-dashboard/reference_skills/wazuh-edr-sysmon
bash scripts/test-edr-e2e.sh
```

Latest verified result on 2026-05-11:

```text
16/16 passed
Wazuh Manager API authentication: PASS
Wazuh Manager processes running: PASS
Wazuh Indexer cluster healthy: PASS
Alert search works: PASS
Fresh Sysmon exact-marker alert flow: PASS, marker CODEX_SYSMON_E2E_1778567257, alerts=2
Live Sysmon decoder/rule shape: PASS, decoder has no <location>, XML marker child and raw marker fallback present
Sysmon rules loaded and searchable: PASS, 271 sysmon rules found
iTop API authentication: PASS
iTop test incident creation: PASS
Active Response enabled in config: PASS
EDR AR script configured: PASS
Bridge state file valid: PASS
```

The exact-marker check is important: it triggers harmless endpoint file-create activity
with a unique `CODEX_SYSMON_*` marker and verifies that exact marker in Wazuh
Indexer. This catches the failure mode where Sysmon, rules, and APIs are all up,
but Wazuh is not indexing current endpoint telemetry.

The live shape check catches Wazuh 4.14 decoder regressions by verifying the
manager's `sysmon_decoder.xml` does not contain unsupported `<location>` inside
a decoder, and that rule `100230` handles real Sysmon XML markers while rule
`100231` remains available for raw manager diagnostics.

## Full Workflow Verification Snapshot

Latest verified result on 2026-05-11:

```text
platform_doctor.py: PASS 18/18 checks, includes dashboard health, ticket sorting, iTop UI, Mailcow API domain/mailbox/alias counts, provider adapters, and required skills
smoke_setup_platform.py: PASS setup_ticket_id=86
smoke_provider_adapters.py: PASS ticket_id=84 local_push=local_only providers=local,itop,servicenow,jira,generic-webhook
smoke_service_desk_intake.py: PASS ticket_id=85 change_id=41 intent=phishing
smoke_agent_auditor.py: PASS audited=1 recent=25
agentic_gitlab_cicd_demo.py: PASS ticket_id=83 project_id=15 initial_pipeline=9 final_pipeline=10 initial_run_id=11 final_run_id=12 agent_id=50 task_id=48 mr=!1 postmortem_id=21
agentic_cicd_full_demo.py: PASS ticket_id=82 initial_run_id=8 final_run_id=10 agent_id=48 task_id=46 change_id=36
smoke_setup_platform.py: PASS setup_ticket_id=78
smoke_agentic_system.py: PASS ticket_id=76 local_push_ticket_id=77
smoke_service_desk_intake.py: PASS ticket_id=71 change_id=30 intent=phishing
smoke_phishing_workflow_lifecycle.py: PASS ticket_id=74 workflow_id=4 postmortem_id=18
smoke_cicd_security_pipeline.py: PASS provider=gitlab run_id=4 ticket_id=73 change_id=31
smoke_agent_auditor.py: PASS audited=3 recent=25
smoke_local_model_agent.py: PASS ticket_id=75 agent_id=44 task_id=42 completed note_written=true active_process_count=0
```

Latest full regression on 2026-05-12:

```text
local source compile: PASS
frontend node --check: PASS
forbidden pattern sweep: PASS, no ORM/Pydantic/SQLAlchemy/hardcoded test secret matches
platform_doctor.py: PASS 18/18
smoke_setup_platform.py: PASS setup_ticket_id=89
smoke_provider_adapters.py: PASS ticket_id=90 local_push=local_only
smoke_service_desk_intake.py: PASS ticket_id=91 change_id=45 intent=phishing
smoke_agentic_system.py: PASS ticket_id=92 local_push_ticket_id=93 change_id=46 postmortem_id=23 workflow_id=22 skill_id=24
smoke_phishing_workflow_lifecycle.py: PASS ticket_id=94 workflow_id=4 postmortem_id=24
smoke_cicd_security_pipeline.py: PASS provider=gitlab run_id=15 ticket_id=95 change_id=48
smoke_agent_auditor.py: PASS audited=3 recent=25
smoke_change_auto_completion.py: PASS ticket_id=96 agent_id=57 task_id=55 change_id=49 completed
smoke_local_model_agent.py: PASS ticket_id=97 agent_id=58 task_id=56 completed note_written=true active_process_count=0
siem-ticket-bridge unit: PASS 40 tests, 3 expected live skips
siem-ticket-bridge E2E: PASS connectivity and direct iTop ticket creation; poll dedup correctly skipped old injected alert
soc_bridge iTop connector: PASS 22 tests
soc_bridge Mailcow connector: PASS 13 tests
soc_bridge E2E: PASS 11 tests
report_phish/test_report.py: PASS, internal Mailcow report sent; Wazuh forwarding disabled unless WAZUH_API_PASSWORD is supplied
report_phish/test_reporter.py: PASS after compatibility update
itop-deployment/scripts/test_itop.py: PASS after current-schema update
itop-deployment/scripts/test_approval_chain.py: PASS after adding required ev_plan fallback field
log_forwarder/test_integration.py: PASS 18/18
log_forwarder/test_logtest.py: PASS after switching to docker exec against the Wazuh manager container
wazuh_deploy/test_wazuh.py: PASS after removing pytest/hardcoded credential dependency
mailcow API shim: PASS 13/13 with MySQL parity
wazuh-edr-sysmon E2E: PASS 15/15 exact marker
agentic_cicd_full_demo.py: PASS ticket_id=98 initial_run=16 failed final_run=17 passed remediation_agent=59 task=57 deployment_change=51 completed postmortem=25 ready_for_review active_processes=0
```

Post-deployment live regression on 2026-05-12 after commit `6a9b766`:

```text
dashboard health: PASS version=1.3.0
POST /api/intake/clarify: PASS 200 OK
source compile: PASS
frontend node --check: PASS
unit tests: PASS 4/4
migration audit against reference_skills: PASS
platform_doctor.py: PASS 18/18
smoke_setup_platform.py: PASS ticket_id=152
smoke_provider_adapters.py: PASS ticket_id=153 local_push=local_only
smoke_service_desk_intake.py: PASS ticket_id=154 change_id=73 intent=phishing
smoke_user_response_workflow.py: PASS ticket_id=155 final_status=new
smoke_agentic_system.py: PASS ticket_id=156 local_push_ticket_id=157 change_id=74 postmortem_id=39 workflow_id=39 workflow_status=active skill_id=47
smoke_phishing_workflow_lifecycle.py: PASS ticket_id=158 change_id=75 workflow_id=4 postmortem_id=40
smoke_cicd_security_pipeline.py: PASS provider=gitlab run_id=19 ticket_id=159 change_id=76
smoke_agent_auditor.py: PASS audited=0 recent=25
smoke_postmortem_promotion.py: PASS ticket_id=160 postmortem_id=41 knowledge_article_id=40 workflow_id=41 skill_ids=48,49
smoke_change_auto_completion.py: PASS ticket_id=161 agent_id=69 task_id=67 change_id=77 completed
smoke_local_model_agent.py: PASS ticket_id=162 agent_id=70 task_id=68 completed note_written=true active_process_count=0
smoke_setup_agent.py: PASS ticket_id=163 agent_id=71 task_id=69 completed note_written=true active_process_count=0
final container check: PASS api up, db healthy
```

Two fixes came out of this deployment regression:

- Explicit `provider: "local"` is now honored even when iTop is configured as
  the automatic outbound provider.
- Postmortem promotion notes include the source postmortem id so ticket context
  preserves the promotion evidence link.

The GitLab proof ran all scanner jobs through GitLab Runner:

- `unit_tests`: success
- `semgrep_sast`: success
- `trivy_fs`: success
- `zap_dast`: success
- `nuclei_exposure`: success
- `dashboard_record`: failed on the initial branch because the security gate
  found high findings, then succeeded on the remediation branch with 0 findings.

The proof also verified runner project attachment, `gitlab-net` executor
networking, `/zap/wrk` report handling, dashboard change gates, GitLab MR
creation, final deployment approval, and postmortem artifact creation.

Live GitLab verification:

```text
project id=15 path=root/agentic-cicd-demo-1778538475
MR !1 state=opened source=agent/remediate-security-gate target=main
pipeline 9 ref=main status=failed
pipeline 9 jobs=unit_tests:success, semgrep_sast:success, trivy_fs:success, zap_dast:success, nuclei_exposure:success, dashboard_record:failed
pipeline 10 ref=agent/remediate-security-gate status=success
pipeline 10 jobs=unit_tests:success, semgrep_sast:success, trivy_fs:success, zap_dast:success, nuclei_exposure:success, dashboard_record:success
dashboard run 11=failed, dashboard run 12=passed
changes 39 and 40=completed
```

## Mailcow API Shim

Full operator blueprint: `docs/MAILCOW_API_SHIM.md`.

```bash
cd /home/cereal/Mailcow/deploy
python3 scripts/deploy_mailcow_api.py
python3 scripts/test_mailcow_api_shim.py --mysql-parity

curl -H "X-API-Key: <from restricted key file or vault>" http://localhost:8081/api/v1/get/domain/all
curl -H "X-API-Key: <from restricted key file or vault>" http://localhost:8081/api/v1/get/mailbox/all
curl -H "X-API-Key: <from restricted key file or vault>" http://localhost:8081/api/v1/get/alias/all
```

Latest verified result on 2026-05-12:

```text
deploy_mailcow_api.py: DEPLOYMENT SUCCESSFUL
invalid key: HTTP 401
missing key: HTTP 401
valid get/domain/all: HTTP 200, 2 domains
valid get/mailbox/all: HTTP 200, 11 mailboxes, no password hashes in response
valid get/alias/all: HTTP 200, 6 aliases
selector reads: domain=1, mailbox=1, alias=1
POST to read compatibility endpoint: HTTP 405
direct MySQL smoke: 2 domains, 11 mailboxes, 6 aliases
test_mailcow_api_shim.py --mysql-parity: 13 passed, 0 failed
platform_doctor.py: 18 passed, 0 failed, 0 warned
keycloak-mailcow bridge E2E: 47 passed, 0 failed, 1 skipped
```

## Postmortem Evidence Endpoint

```bash
curl -sS "http://localhost:25480/api/postmortems/evidence/83?task_log_lines=5"
```

Latest verified result on 2026-05-11:

```text
ticket_id=83
notes=6
attachments=2
changes=2
agent_tasks=2
cicd_runs=2
postmortems=1
audit=28
first_task_has_tail=true
```

This endpoint exists so postmortem agents can consume scoped evidence directly
instead of guessing provider-specific note URLs or reading arbitrary files.

## Postmortem Promotion Smoke

```bash
cd /home/cereal/SOC_TESTING/soc-dashboard
python3 scripts/smoke_postmortem_promotion.py http://localhost:25480
```

Covers:

- reviewed postmortem can be promoted into reusable assets
- knowledge article body includes the structured postmortem sections
- workflow is created in `draft` with human-review activation guardrails
- skill proposals become enabled candidate skills
- ticket context receives a human-readable promotion note
- audit trail includes `postmortem_promoted`
- repeat promotion updates the same KB/workflow/skill assets instead of
  duplicating them

Latest verified result on 2026-05-12:

```text
ticket_id=109
postmortem_id=30
knowledge_article_id=30
workflow_id=28
skill_ids=31,32
second_promotion_actions=knowledge:updated,workflow:updated,skills:updated+updated
ui_promotion_hooks=present
```

## Agent Auditor Smoke

```bash
cd /home/cereal/SOC_TESTING/soc-dashboard
python3 scripts/smoke_agent_auditor.py http://localhost:25480
```

Covers:

- manual auditor poll
- audit review listing
- non-blocking progress/recovery supervision path

## Approved Change Auto-Completion Smoke

```bash
cd /home/cereal/SOC_TESTING/soc-dashboard
docker compose cp scripts/smoke_change_auto_completion.py api:/app/smoke_change_auto_completion.py
docker compose exec -T api sh -lc 'cd /app && python smoke_change_auto_completion.py'
```

Covers:

- synthetic completed agent task
- approved agent-linked remediation change
- `agent_auditor` sweep
- automatic transition from `approved` to `completed`
- evidence persisted in `change_requests.result`
- audit review entry `approved_change_auto_completed`

Latest verified result:

```text
ticket_id=87
agent_id=52
task_id=50
change_id=42
change_status=completed
result_has_evidence=true
review=approved_change_auto_completed
```

## Real Agentic CI/CD Flow

```bash
cd /home/cereal/SOC_TESTING/soc-dashboard
SOC_DASHBOARD_URL=http://localhost:25480 \
AGENT_MODEL=qwen/qwen3.6-27b \
CICD_DOCKER_NETWORK=host \
python3 scripts/agentic_cicd_full_demo.py \
  --base http://localhost:25480 \
  --host-ip 192.168.50.222 \
  --timeout 2400
```

Latest verified result:

```text
ticket_id=88
initial_run=13 failed high=1 medium=6 low=6 info=1
remediation_agent=53 task=51 completed
remediation_change=43 completed
final_run=14 passed high=0 critical=0
deployment_change=44 completed
postmortem=22 ready_for_review
ticket_status=resolved
active_agent_processes=0
```

Latest verified result on 2026-05-12:

```text
ticket_id=98
initial_run=16 failed high=1 medium=6 low=6 info=1 unknown=2
remediation_agent=59 task=57 completed
remediation_change=50 completed
final_run=17 passed high=0 critical=0
deployment_change=51 completed
postmortem=25 ready_for_review
ticket_status=resolved
active_agent_processes=0
```

This is a real local-model flow, not just a smoke: Docker scanner containers ran
Semgrep, Trivy, OWASP ZAP, and Nuclei; the local model edited the test app;
the fixed branch compiled; the scanner gate reran; changes advanced with
evidence; and the supervisor generated the postmortem when model postmortem
attempts stalled on evidence processing.

Latest verified result from a fresh one-line install on 2026-05-12:

```text
install_target=/home/cereal/SOC_TESTING/soc-dashboard-install-e2e-20260512
dashboard=http://localhost:25482
ticket_id=13
initial_run=5 failed high=1 medium=6 low=6 info=1 unknown=2
remediation_agent=7 task=7 completed
remediation_change=8 completed
final_run=6 passed high=0 critical=0
deployment_change=9 completed
postmortem=4 ready_for_review
mr_artifact=/home/cereal/SOC_TESTING/soc-dashboard-install-e2e-20260512/agent_work/7/agent-remediation.patch
active_agent_processes=0
```

For one-line/container installs, run the DB-coupled change-completion smoke
inside the API container because it imports the API database module and depends
on container Python packages:

```bash
cd /home/cereal/SOC_TESTING/soc-dashboard-install-e2e-20260512
docker compose exec -T api python smoke_change_auto_completion.py http://localhost:8000
```

Fresh install regression suite verified on `http://localhost:25482`:

```text
platform_doctor.py: PASS 18/18
smoke_setup_platform.py: PASS ticket_id=14
smoke_provider_adapters.py: PASS ticket_id=15 local_push=local_only
smoke_service_desk_intake.py: PASS ticket_id=16 change_id=10
smoke_agentic_system.py: PASS ticket_id=17 local_push_ticket_id=18 change_id=11 postmortem_id=5 workflow_id=3 skill_id=24
smoke_phishing_workflow_lifecycle.py: PASS ticket_id=19 change_id=12 workflow_id=2 postmortem_id=6
smoke_cicd_security_pipeline.py: PASS run_id=7 ticket_id=20 change_id=13 provider=gitlab
smoke_agent_auditor.py: PASS audited=2
smoke_change_auto_completion.py: PASS ticket_id=21 agent_id=9 task_id=9 change_id=14 completed
smoke_local_model_agent.py: PASS ticket_id=22 agent_id=10 task_id=10 completed
smoke_setup_agent.py: PASS ticket_id=23 agent_id=11 task_id=11 completed
```

## Demo Activity Trail Verification

The dashboard now treats ticket notes as first-class activity alongside audit
and event rows. This makes demo ticket details easier to follow while retaining
the full audit trail.

API-level verification on the main dashboard:

```bash
BASE=http://localhost:25480
TICKET=$(curl -sS -X POST "$BASE/api/tickets" \
  -H 'Content-Type: application/json' \
  -d '{"title":"Demo activity trail verification","description":"Verify notes appear in activity and audit trail.","provider":"local","sync_provider":false,"created_by":"activity-test"}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')

curl -sS -X POST "$BASE/api/tickets/$TICKET/notes" \
  -H 'Content-Type: application/json' \
  -d '{"body":"Manual verification note: normalized note trail should include ticket id and full note body.","author":"activity-test","source":"verification","visibility":"internal"}'

curl -sS "$BASE/api/dashboard/stats"
curl -sS "$BASE/api/dashboard/audit?limit=20&ticket_id=$TICKET"
curl -sS "$BASE/api/tickets/$TICKET/context"
```

Latest verified result:

```text
ticket_id=100
context_notes=1
recent_activity_note_visible=true
audit_note_visible=true
audit_sources=event,note
```

Real local-model verification:

```bash
cd /home/cereal/SOC_TESTING/soc-dashboard
python3 scripts/smoke_local_model_agent.py http://localhost:25480 qwen/qwen3.6-27b
```

Latest verified result:

```text
ticket_id=101
agent_id=61
task_id=59
status=completed
total_notes=5
agent_note_sources=agent,agent-checkpoint,agent-control-plane
agent_note_titles=Agent assigned; Agent started; local model agent smoke note complete; Agent checkpoint: local-model-agent-smoke; Agent completed
audit_note_count=5
active_agent_processes=0
```

Frontend asset verification:

```text
node --check frontend/js/dashboard.js: PASS
served /static/js/dashboard.js contains openAuditTrail
served / contains the Notes audit source filter
served /static/css/dashboard.css contains activity-note-body
```

## Transparent Approval Gate Verification

The demo approval flow should make it obvious that a guardrail exists even when
the lab is configured to auto-approve.

Verification on the main dashboard:

```bash
BASE=http://localhost:25480
TICKET=$(curl -sS -X POST "$BASE/api/tickets" \
  -H 'Content-Type: application/json' \
  -d '{"title":"Demo transparent approval gate verification","description":"Verify approval gates show opened, auto-approved, and completed notes/audit details.","provider":"local","sync_provider":false,"created_by":"approval-gate-test"}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')

CHANGE=$(curl -sS -X POST "$BASE/api/changes/request" \
  -H 'Content-Type: application/json' \
  -d "{\"ticket_id\":$TICKET,\"action\":\"demo_block_url\",\"target\":\"https://example.invalid/phish\",\"reason\":\"Demonstrate a guardrailed remediation approval chain.\",\"risk_level\":\"medium\",\"approval_policy\":{\"demo_auto_approval\":true}}" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["change_id"])')

curl -sS -X POST "$BASE/api/changes/$CHANGE/approve" \
  -H 'Content-Type: application/json' \
  -d '{"approved_by":"demo-auto-approver","reason":"Demo mode auto-approval to prove the approval gate without waiting for a human."}'

curl -sS -X POST "$BASE/api/changes/$CHANGE/complete" \
  -H 'Content-Type: application/json' \
  -d '{"completed_by":"approval-gate-test","result":"No production action executed. Demo gate lifecycle verified with audit and notes."}'
```

Latest verified result:

```text
ticket_id=102
change_id=52
change_status=completed
approved_by=demo-auto-approver
note_count=3
has_gate_opened_note=true
has_auto_approved_note=true
has_completed_note=true
auto_audit_entries=4
audit_sources=audit,event,note
active_agent_processes=0
```

Frontend asset verification:

```text
served /static/js/dashboard.js contains Auto-approved demo gate
served /static/css/dashboard.css contains gate-card
```

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
ticket_id=66
agent_id=43
task_id=41
status=completed
progress=100
note_written=true
active_process_count=0
```

2026-05-12 regression evidence:

- Agents `82` and `83` were spawned by this smoke after the memory hook contract
  fix.
- Both agents ended `failed`; their recorded PIDs were gone from the API
  container.
- Both checkpoints stayed at the initial `init`/`queued` state even though the
  task rows showed `progress_pct=40`.
- Agent `83` did write the required ticket note, proving useful work happened,
  but it did not update the done checkpoint or finish the exact smoke contract.
- The smoke script now prints active evidence on status changes and final
  failure: process snapshot, stream log tail, checkpoint state, ticket notes,
  and audit reviews. Treat `progress_pct` as `progress_pct_ui_hint` only.

See `docs/AGENT_RUN_FAILURES_2026-05-12.md` for the detailed failure note.

2026-05-12 real local-agent closure proof after runner queue/stall fixes:

```text
runtime:
  MAX_CONCURRENT_AGENTS=1
  AGENT_TIMEOUT_MINUTES=0
  AGENT_NO_OUTPUT_STALL_SECONDS=3600
first proof:
  ticket_id=340
  agent_id=112
  task_id=109
  task_status=completed
  ticket_status=resolved
  evidence_notes=420,421
  finding=agent_progress_ok
  active_process_count=0
content-alias regression:
  ticket_id=341
  note_id=424
  passed=true
second proof:
  ticket_id=342
  agent_id=113
  task_id=110
  task_status=completed
  ticket_status=resolved
  evidence_notes=427,428
  checkpoint_note=429
  completion_note=430
  finding=agent_progress_ok
  active_process_count=0
```

The first proof found that agents naturally used `content` for note bodies; the
API previously accepted only `body`/`note`/`title`, so notes retained only their
titles. `POST /api/tickets/{ticket_id}/notes` now accepts `content` as an alias,
and the V2 proof confirms full note bodies are retained while the runner closes
successful `ticket_resolution` work.

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
- Incident/UserRequest outbound create prefers `ITOP_DEFAULT_ORG_ID` and `ITOP_DEFAULT_CALLER_ID`, but derives usable defaults from iTop when they are absent
- Incident outbound create maps dashboard priority to iTop `impact` and `urgency`

If no organization or caller can be resolved from iTop, expected status is `create_failed` with a clear `provider_last_error`. Otherwise expected status is `synced` with a concrete iTop `provider_ref`.

Focused unit coverage:

```bash
python -m unittest tests.test_itop_outbound
```

Live smoke used for the 2026-05-12 fix:

- dashboard direct create produced `UserRequest::169` and `Incident::170`
- both dashboard tickets returned `provider_sync_status=synced`
- iTop verified org/caller/team defaults on both records and `impact=2`, `urgency=2` for the `P2` Incident

Optional repeatable live smoke:

```bash
python3 scripts/smoke_provider_adapters.py http://localhost:25480 --itop-create
```

## SIEM Bridge Correlation Regression

The SIEM bridge should not create separate tickets for multiple Wazuh rules that
are clearly part of the same explicit test/incident marker. Exact dedup still
keys on rule/source/timestamp, while cross-rule correlation keys on explicit
`correlation_key` values or marker strings such as `CODEX_*`.

Local/source verification:

```powershell
python -m unittest reference_skills.siem-ticket-bridge.tests.test_bridge
python -m py_compile reference_skills\siem-ticket-bridge\siem_ticket_bridge\bridge.py reference_skills\siem-ticket-bridge\siem_ticket_bridge\config.py
```

Latest verified result on 2026-05-12:

```text
SIEM bridge tests: Ran 41, OK, skipped 3 live tests
marker correlation: 2 related Sysmon marker alerts -> 1 ticket + 1 correlated event
live bridge status: active
BRIDGE_CORRELATION_WINDOW=300
processed_alerts=552
ticket_correlation_keys=0 before next marker run
```

Live recovery/fanout proof:

```text
EDR rerun before recovery: 15/16, exact marker missing after 90s
root cause evidence: marker present in /var/log/sysmon/sysmon.log, absent from Wazuh Indexer
recovery: logrotate /etc/logrotate.d/sysmon-edr + Wazuh manager/logcollector restart
recovery marker: CODEX_SYSMON_E2E_RECOVERY_1778630817
indexed alerts: 2 (rules 100230 and 100231)
bridge state after poll: ticket_correlation_keys=1
auto-assignment cap proof:
  first_ticket=351 assigned agent=122
  second_ticket=352 skipped reason=auto_assignment_capacity_reached
  active_after_stop=0
```
