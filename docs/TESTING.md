# Testing Runbook

Last updated: 2026-05-18.

## Local Source Validation

From the workspace root:

```powershell
python -m compileall .\soc-dashboard\api
node --check .\soc-dashboard\frontend\js\dashboard.js
node --check .\soc-dashboard\frontend\js\agents.js
node --check .\soc-dashboard\frontend\js\charts.js
node --check .\soc-dashboard\frontend\js\websocket.js
python -m py_compile .\soc-dashboard\scripts\smoke_agentic_system.py .\soc-dashboard\scripts\smoke_local_model_agent.py .\soc-dashboard\scripts\smoke_service_desk_intake.py .\soc-dashboard\scripts\smoke_cicd_security_pipeline.py .\soc-dashboard\scripts\smoke_agent_auditor.py .\soc-dashboard\scripts\smoke_provider_adapters.py .\soc-dashboard\scripts\smoke_operational_metrics.py .\soc-dashboard\scripts\run_cicd_security_pipeline.py .\soc-dashboard\scripts\agentic_cicd_full_demo.py .\soc-dashboard\scripts\agentic_gitlab_cicd_demo.py .\soc-dashboard\scripts\platform_doctor.py .\soc-dashboard\scripts\repair_agent_supervision_env.py
python -m unittest discover -s .\soc-dashboard\tests -p "test_*.py"
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

`platform_doctor.py` is the preferred pre-demo check. It is non-destructive and verifies dashboard health, setup manifest hygiene, ticket sorting, provider adapters, iTop UI reachability, Mailcow HTTP API domain/mailbox/alias counts, scanner skills, AI proxy skill, SearXNG skill, and EDR/Sysmon bundle presence. For the Mailcow demo surface, also verify `http://192.168.50.222:2581` renders the login page, generated `/cache` CSS/JS assets return HTTP `200` with no-store cache headers and `?v=` URL versions, stale `MCSESSID` recovery sends `/user` back to the admin login, admin form login from the bare root URL reaches `/admin/dashboard` with visible dashboard text, admin/mailbox/quarantine UI table JSON does not raise DataTables dialogs, System/Mailbox/Queue/Quarantine pages show no SQL or invalid JSON alerts, and IMAP login for `demo_account_1@mailcow.local` returns `OK` using the vault password.

Latest verified result on 2026-05-13:

```text
platform_doctor.py: PASS 18, WARN 0, FAIL 0
runner timeout_minutes: 0
default_model: qwen/qwen3.6-27b
effective_anthropic_base_url: http://192.168.50.222:4001
```

## Operational Metrics Smoke

```bash
cd /home/cereal/SOC_TESTING/soc-dashboard
python3 scripts/smoke_operational_metrics.py http://localhost:25480
```

Covers:

- `/api/dashboard/ops-metrics` sections for agent work, SLA, gates, workflows,
  CI/CD, auto-assignment, and tool health.
- server-derived nonnegative agent idle/runtime/working/gated seconds.
- workflow `review_state` and run counters.
- dynamic tools/setup-module inventory with ComfyUI excluded.
- CI/CD scanner grouping and OWASP ZAP baseline exit code `2` normalization.

Latest verified result on 2026-05-13:

```text
status=passed
cicd_run_id=26
zap_status=completed_with_findings
setup_modules=38
negative_agent_timing_fields=0
```

## Current Live Agentic Proofs

Latest verified on 2026-05-13 after the operational metrics deployment:

```text
Phishing auto-assignment:
  dashboard_ticket=410
  agent=148
  task=145 completed/100
  change=119 completed
  final_note=682
  postmortem=61
  dashboard_status=resolved

SIEM -> iTop -> dashboard -> agent:
  iTop_incident=267 / I-000276
  dashboard_ticket=422
  agent=149
  task=146 completed/100
  approval_gate=123 approved_by=codex-live-test-approver completed
  triage_note=687
  postmortem=62
  dashboard_status=resolved
  forced_provider_sync=synced
  direct_iTop_status=resolved
  direct_iTop_solution contains agent completion summary
```

Both runs were monitored with `/api/agents/audits/run`; the auditor raised
checkpoint-age warnings while heartbeat/output/note activity was fresh, and no
wall-clock timeout or process kill was used.

## Cross-Platform Demo Credential Smoke

Credential value lives in the local encrypted vault key `demo_account_1`. Do not print it.

Latest verified result on 2026-05-18:

```text
gitlab_local_login: PASS http=302
gitlab_oidc_start: PASS http=302 keycloak_redirect=True
itop_rest_post: PASS code=0 count=1
wazuh_dashboard_login_endpoint: PASS http=200
mailcow_mailbox: PASS exists=True
wazuh_api_auth: WARN http=401
```

Important implementation notes:

- Wazuh Dashboard auth requires OpenSearch Security `internal_users.yml` sync and `securityadmin.sh` reload.
- Native Wazuh API auth is separate from Dashboard auth; the current demo user returns HTTP 401 and should not be used as the primary Wazuh demo path until repaired.
- iTop demo users must be real `UserLocal` objects with `Administrator` and `REST Services User`; raw partial rows can be counted by OQL but fail object reload and login.
- GitLab local login requires a valid personal namespace on the GitLab user. Missing namespace causes the generic GitLab 422 page even when the password is correct.
- GitLab OIDC requires both the container-side `keycloak.internal:host-gateway` mapping and the Keycloak CA in GitLab trusted certs. Browser-based OIDC also requires the operator workstation to resolve `keycloak.internal` to `192.168.50.222`.
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

## Real Report-Phish Agentic E2E

This is the current live proof that the bridge and local model path work beyond
smoke tests.

Flow exercised:

- Report-phish CLI/email path created a phishing report marker
  `CODEX_PHISH_E2E_1778637511`.
- SOC bridge created iTop Incident `236` (`I-000245`) and dashboard ticket
  `364`.
- RACI auto-assignment spawned local-model agent `127`, task `124`.
- Agent wrote triage note `491`.
- Agent created approval gates `100`, `101`, and `102`.
- `codex-e2e-lab-approver` approved all three gates.
- Agent resumed automatically, completed all three gates, wrote resolution note
  `502`, created postmortem `47`, and wrote final checkpoint
  `resolution_complete` at `100%`.
- Dashboard ticket `364` resolved and direct iTop read confirmed Incident `236`
  status `resolved`, resolution code `assistance`, with the agent summary in
  the provider solution field.

Evidence:

```text
marker=CODEX_PHISH_E2E_1778637511
itop_incident=236
itop_ref=I-000245
dashboard_ticket=364
agent=127
task=124
triage_note=491
changes=100:block phishing URL, 101:search/quarantine mailbox, 102:password reset/session review
approver=codex-e2e-lab-approver
resolution_note=502
postmortem=47
final_status=dashboard resolved, iTop resolved
```

Guardrail evidence:

- The auditor recorded `agent_waiting_on_approval` while gates were pending.
- Intermediate checkpoint stayed `running` at `35%`; the ticket did not close
  until the final `done` checkpoint at `100%`.
- Lab-safe change results name the production adapters that should execute real
  URL block, mailbox quarantine, and IAM password/session operations.

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

## Access Request Resume Smoke

Control-plane proof:

```bash
cd /home/cereal/SOC_TESTING/soc-dashboard
python3 scripts/smoke_access_request_control_plane.py http://localhost:25480
```

Covers:

- `/api/tickets/{id}/access-request`
- child access request ticket creation
- `access_requests` audit row
- approval gate approval/completion
- access request status changing to `granted`
- parent and child ticket notes with grant evidence

Real local-model proof:

```bash
cd /home/cereal/SOC_TESTING/soc-dashboard
python3 scripts/agentic_access_request_resume_demo.py http://localhost:25480 qwen/qwen3.6-27b
```

Covers:

- an actual dashboard agent simulating a 403 permission wall
- agent-created access request and `waiting_for_access` checkpoint
- runner preserving the waiting state instead of resolving the ticket
- approval-driven resume of the original ticket
- resumed agent completing the access gate and resolving the ticket
- explicit `POST /api/tickets/{id}/status` from the resumed agent after the
  grant is verified; runner completion alone must not close the ticket

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

Latest verified result on 2026-05-18:

```text
providers: generic-webhook, itop, jira, local, servicenow
local_push: local_only
servicenow: fail-closed not configured
jira: fail-closed not configured
```

For real outbound iTop proof, include `--itop-create`:

```bash
python3 scripts/smoke_provider_adapters.py http://localhost:25480 --itop-create
```

Latest verified on 2026-05-13: dashboard tickets `420` and `421` synced to
iTop provider refs `265` and `266`.

## Live Bridge Regression

Bridge tests must be run from their own directories so relative config and
`.env` files load correctly.

```bash
cd /home/cereal/SOC_TESTING/siem-ticket-bridge
PYTHONPATH=. python3 -m unittest tests.test_bridge -v
set -a; source .env; set +a
PYTHONPATH=. python3 -m siem_ticket_bridge.bridge --test-connection
PYTHONPATH=. python3 tests/test_ticket_e2e.py

cd /home/cereal/SOC_TESTING/soc_bridge
python3 tests/test_end_to_end.py
python3 tests/test_itop_connector.py
python3 tests/test_mailcow_connector.py

cd /home/cereal/iam-bridge && python3 scripts/test_bridge.py
cd /home/cereal/keycloak-mailcow-bridge && python3 scripts/test_integration.py
cd /home/cereal/keycloak-mailcow-bridge && python3 scripts/test_mailcow_api_shim.py
cd /home/cereal/keycloak-manager && python3 scripts/test_keycloak.py
```

Latest verified on 2026-05-13:

```text
siem-ticket-bridge: 41 unit tests OK, connection OK, E2E direct iTop ticket 267
soc-bridge: 11 + 22 + 13 tests OK
iam-bridge: 23 tests OK
keycloak-mailcow bridge: 47 passed, 1 expected skip
mailcow api shim: 10 tests OK
keycloak-manager: 26 tests OK
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

Latest verified result on 2026-05-18:

```text
deploy_mailcow_api.py: DEPLOYMENT SUCCESSFUL
invalid key: HTTP 401
missing key: HTTP 401
valid get/domain/all: HTTP 200, 2 domains
valid get/mailbox/all: HTTP 200, 11 mailboxes, no password hashes in response
valid get/alias/all: HTTP 200, 16 aliases
selector reads: domain=1, mailbox=1, alias=1
POST to read compatibility endpoint: HTTP 405
direct MySQL smoke: 2 domains, 11 mailboxes, 16 aliases
test_mailcow_api_shim.py --mysql-parity: 13 passed, 0 failed
demo UI table JSON: PASS for domain search, quarantine, domain templates, mailbox templates
Roundcube webmail route: PASS for /webmail and /SOGo/so compatibility redirect
demo UI browser crawl: PASS for /admin/dashboard, /admin/system, /admin/mailbox, /admin/queue, /quarantine, /webmail, /SOGo/so
webmail IMAP auth: PASS as demo_account_1@mailcow.local; Roundcube inbox renders real Mailcow messages and a Report Phish toolbar button
report-phish quarantine proof: PASS ticket=580 itop=372 agent=229 access_request=581 quarantine=21a705b151642568d375c748a9ea1a6b
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

EDR/Sysmon live rerun after harness and Sysmon noise fixes:

```text
neutral provider-health harness:
  generic iTop health ticket title now avoids EDR/SIEM/Sysmon keywords
  expected behavior: no accidental RACI security auto-assignment
Sysmon/Wazuh ingestion fix:
  removed broad shell/script suffix selectors from lab Sysmon config
  added match-nothing ProcessTerminate rule to suppress EventID 5 queue flood
  rotated /var/log/sysmon/sysmon.log and restarted Sysmon + Wazuh manager internals
EDR test:
  command: SYSMON_ALERT_WAIT_SECONDS=90 python3 reference_skills/wazuh-edr-sysmon/tests/test_edr_sysmon_e2e.py
  result: 16/16 passed
  marker: CODEX_SYSMON_E2E_1778632686
  marker_alerts: 2
SIEM bridge after poll:
  siem_connected=true
  ticketing_connected=true
  processed_alerts=574
  ticket_correlation_keys=2
  alert_count=74
  ticket_count=72
  error_count=0
auto-assignment/queue proof:
  active agent remained exactly 1
  active_agent=123
  active_ticket=354
  active_task=120
  skipped_while_busy=tickets 355,356,357,358,359 with auto_assignment_capacity_reached
agent auditor:
  manual sweep returned audited=14
  agent 123 finding=agent_progress_ok
  agent recovered after a rejected multiline inline-python command by trying a simpler approach
provider sync status guard:
  issue: iTop sync could mirror provider status "new" over an active dashboard agent ticket
  source fix: active-agent tickets preserve local in_progress/waiting state unless provider status is terminal
  local tests: python -m unittest tests.test_itop_sync_status tests.test_auto_assignment tests.test_itop_outbound -> PASS
  live deployment: source synced; API rebuild deferred until active agent 123 completes
agent note attribution:
  issue: agent triage note 456 defaulted to author/source dashboard
  source fix: ticket-agent prompts now require explicit author=agent-{agent_instance_id} and source=agent on note writes
  local compile: python -m py_compile api/services/task_prompts.py api/services/itop_sync.py -> PASS
  live deployment: source synced; API rebuild deferred until active agent 123 completes
provider closure:
  issue: ticket-resolution agents resolved dashboard tickets locally without guaranteeing iTop close
  source fix: successful ticket_resolution completion now calls the iTop provider close lifecycle when provider=itop
  local tests: python -m unittest tests.test_itop_sync_status tests.test_auto_assignment tests.test_itop_outbound tests.test_agent_lifecycle_guards -> PASS
  live proof: manual provider close for pre-fix ticket 354 returned status=resolved; evidence shows dashboard status=resolved and provider status=resolved
single ticket sync:
  issue: /api/tickets/354/sync returned HTTP 500 after status-guard refactor
  fix: removed stale exists variable references in iTopProvider.sync_ticket
  live proof: POST /api/tickets/354/sync returned HTTP 200 and is_new=false
```

## Full Bridge And Agentic Regression Rerun - 2026-05-13

Purpose: rerun bridge/unit/smoke coverage plus real local-model agent flows with
the AI server constrained to the slow local-model lab lane (`MAX_CONCURRENT_AGENTS=1`)
and no short model wall-clock kills.

Remote evidence files:

```text
/tmp/platform_full_test_summary_20260512_232845.txt
/tmp/platform_live_bridge_summary_live_bridges_20260512_233954.txt
/tmp/soc_dashboard_smoke_summary_serial_20260512_234803.txt
/tmp/soc_dashboard_model_smoke_summary_model_serial_20260513_001552.txt
/tmp/soc_dashboard_setup_agent_rerun_20260513_064257.summary
/tmp/soc_dashboard_itop_close_rerun_20260513_065044.summary
/tmp/soc_dashboard_full_green_acceptance_v2_20260513_070546.txt
```

Bridge/unit results:

```text
soc-dashboard unittest discovery: PASS
soc-dashboard core py_compile: PASS
siem-ticket-bridge unit/status: PASS
soc-bridge E2E/iTop/Mailcow: PASS
report-phish reporter/report/smtp sink: PASS
keycloak-manager unit: PASS
mailcow-api-shim: PASS
live iam-bridge: PASS
live keycloak-mailcow-bridge: PASS
live wazuh-bridge: PASS
live keycloak-manager: PASS 26/26
live mailcow-api-shim: PASS 10/10
live Mailcow SMTP/IMAP: PASS
```

Dashboard deterministic smoke results:

```text
smoke_agentic_system: PASS
smoke_provider_adapters: PASS
smoke_service_desk_intake: PASS
smoke_user_response_workflow: PASS
smoke_phishing_workflow_lifecycle: PASS
smoke_postmortem_promotion: PASS
smoke_setup_platform: PASS after setup auto-assignment guard
smoke_cicd_security_pipeline: PASS
smoke_agent_auditor: PASS
smoke_auto_assignment_policy: PASS
smoke_change_auto_completion: PASS
```

Model-backed local-agent results:

```text
smoke_local_model_agent: PASS
  ticket=405 agent=144 task=141
  checkpoint=done/100
  evidence note="local model agent smoke note complete"
  no lingering active process

smoke_setup_agent: PASS
  ticket=408 agent=146 task=143
  checkpoint=done/100
  note_written=true
  no lingering active process

smoke_itop_agent_close_e2e: PASS
  marker=CODEX_ITOP_CLOSE_RERUN_20260513_065044
  dashboard_ticket=409
  itop Incident=262 / I-000271
  agent=147 task=144
  dashboard_status=resolved
  provider_sync_status=synced
  direct_itop_status=resolved
  direct_itop_solution contains marker
  audit_findings=[agent_task_completed]
```

Important fixes discovered during this rerun:

- The full-smoke wrapper no longer queues overlapping model-backed agents behind
  slow local models. Model smokes wait for `/api/agents/active` to drain, run
  the auditor while waiting, and default to one-hour waits with
  `AGENT_SMOKE_STOP_ON_TIMEOUT=false`.
- `/api/agents/processes` can return process rows as strings; the local-model
  smoke parser now handles that shape.
- `smoke_change_auto_completion.py` self-dispatches into the API container so
  it uses the deployed raw-PostgreSQL runtime rather than requiring host Python
  packages.
- Setup tickets now call `ticket_service.create_ticket(..., auto_assign=False)`.
  `spawn_agent=false` is review-only and cannot leak into RACI auto-assignment.

2026-05-13 Wazuh/Sysmon bridge stability, false-positive, and priority queue proof:

- Live issue documented in `docs/KNOWN_ISSUES.md`: Wazuh previously logged
  `wazuh-analysisd: WARNING: Input queue is full`, Sysmon had a 16 GB historical
  archive in the hot log directory, and the SIEM ticket bridge had no installed
  system logrotate policy.
- Fixed bridge backpressure/state/logging: `BRIDGE_MAX_TICKETS_PER_POLL`,
  timestamped dedupe state, processed-alert retention, approved suppression
  rules file, bridge health JSON, and `/etc/logrotate.d/siem-ticket-bridge`.
- Fixed Sysmon hot-log hygiene: deployment now moves `sysmon.log.archive.*` to
  `/var/log/sysmon/archive` and tightens logrotate to `size 32M`, `rotate 14`.
- Fixed runner scheduling: queued agents are dequeued by priority rank, so P1/P2
  ticket-resolution work can overtake lower-priority queued work when
  `MAX_CONCURRENT_AGENTS` caps the local model lane.
- Local tests:
  `python -m unittest reference_skills.siem-ticket-bridge.tests.test_bridge -v`
  passed 44 tests, 3 live skipped.
- Local tests:
  `python -m unittest tests.test_agent_lifecycle_guards -v` passed 17 tests,
  including priority queue ordering.
- Remote bridge tests:
  `PYTHONPATH=. python3 -m unittest tests.test_bridge -v` passed 44 tests,
  3 live skipped.
- Remote dashboard tests:
  `python3 -m unittest tests.test_agent_lifecycle_guards -v` passed 17 tests.
- Deterministic false-positive workflow:
  `python3 scripts/smoke_false_positive_suppression_workflow.py
  http://localhost:25480` passed with ticket `429`, change `124`,
  postmortem `63`, workflow `59`.
- Real local-model false-positive classification:
  ticket `430`, agent `150`, task `147`, completed with required
  false-positive note present.
- Wazuh/Sysmon E2E:
  `SYSMON_ALERT_WAIT_SECONDS=90 python3
  reference_skills/wazuh-edr-sysmon/tests/test_edr_sysmon_e2e.py` passed 16/16
  with marker `CODEX_SYSMON_E2E_1778680907`.
- Full bridge-to-agent proof:
  fresh marker produced iTop Incident `275` / `I-000284`, dashboard ticket
  `431`, auto-assigned agent `151`, task `148`, false-positive notes `708`,
  `709`, `711`, postmortem `64`, dashboard status `resolved`, and direct iTop
  status `resolved`.
- Post-fix bridge health:
  `python3 deploy/check_bridge_health.py` returned `status: ok`, recent poll,
  `error_count: 0`, and `backpressure_count: 0`.
- `report_phish/test_smtp_server.py` uses a Python 3.12-compatible socketserver
  SMTP sink instead of the removed stdlib `smtpd` module.

## Permission And Provider Regression Rerun - 2026-05-14

Remote result file:

```text
/tmp/soc_broad_deterministic_results.json
```

Passing suites:

```text
python3 -m unittest discover -s tests -p 'test_*.py'  # 78 tests
python3 scripts/platform_doctor.py --base http://127.0.0.1:25480  # 18/18
python3 scripts/smoke_provider_adapters.py http://127.0.0.1:25480 --itop-create
python3 scripts/smoke_permission_provider_matrix.py http://127.0.0.1:25480 --manage-auth --repo /home/cereal/SOC_TESTING/soc-dashboard --model qwen/qwen3.6-27b
python3 scripts/smoke_access_request_control_plane.py http://127.0.0.1:25480
python3 scripts/smoke_agent_auditor.py http://127.0.0.1:25480
python3 scripts/smoke_operational_metrics.py http://127.0.0.1:25480
python3 scripts/smoke_auto_assignment_policy.py http://127.0.0.1:25480
python3 scripts/smoke_change_auto_completion.py http://127.0.0.1:25480
python3 scripts/smoke_service_desk_intake.py http://127.0.0.1:25480
```

Key evidence:

- Permission matrix marker `PERMISSION_PROVIDER_MATRIX_1778768984`.
- iTop parent ticket `511` provider ref `299`; access child `512` provider ref
  `300`; iTop readback for child was `resolved`.
- Agent `181` inherited scoped leases, denied forbidden GitLab/iTop leases with
  `missing_agent_vault_lease`, then received granted iTop lease id `64` only
  after approval/completion.
- Provider adapter smoke created iTop `UserRequest` provider ref `297` and
  iTop `Incident` provider ref `298`.
- Service desk intake synced ticket `516` to the configured ticket provider.
- Final `/api/agents/active` returned `0`.

Local-model agentic caveat:

- The current Qwen model aliases are not reliably emitting executable tools in
  the Claude Code harness for the permission-wall curl flow.
- Agent `180`, task `177`, marker `AGENTIC_PERMISSION_VAULT_1778768749`
  failed fast with a runner stall message after no output. This is the desired
  failure mode until a tool-capable local model/proxy is configured.
