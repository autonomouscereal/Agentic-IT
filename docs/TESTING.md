# Testing Runbook

Last updated: 2026-05-21.

## Pre-Demo Non-Agent Smoke Checkpoint

2026-05-21 last-minute demo checkpoint intentionally avoided real agent
invocations.

Local/source checks:

- `python -m pytest -q`: `210 passed`
- `python -m py_compile api\routes\ops_chat.py api\services\ticket_service.py deploy\ops-chat\bridge\bridge.py`: passed
- `python scripts\text_hygiene.py`: passed
- `node --check scripts\smoke_ops_chat_playwright.js`: passed

Live AI-server checks against `http://127.0.0.1:25480` and
`https://127.0.0.1:25443`:

- `/health`: `ok`
- `/api/agents/active`: `{"agents":[],"count":0}` before and after
- `scripts/smoke_global_search.py`: passed, ticket `1429`
- `scripts/smoke_setup_platform.py`: passed with `spawn_agent=false`, setup
  ticket `1430`, module ticket count `9`, single-module ticket `1440`
- `scripts/smoke_dashboard_auth_enforcement.py`: passed, auth mode `header`,
  enforcement `enforce`, no secret values returned
- `scripts/smoke_dashboard_https.py`: passed, `/login` redirect, HSTS, and
  `X-Frame-Options: DENY`

This checkpoint validates platform health, auth, HTTPS, search, and setup
ticket fan-out without starting any harness tasks during the live-demo window.

## Agent Queue Recovery Checkpoint

2026-05-21 live queue recovery validated the runner after Ops Chat spawned
multiple tickets during demo preparation:

- Root symptom: tickets `1441` and `1444` showed `spawned` / `queued` with no
  live harness processes.
- Fix deployed: queue workers now survive per-task exceptions, runner health
  and active-agent polling self-heal durable DB-queued tasks, and the live
  default `max_concurrent_agents` is `5`.
- `/api/agents/runner-health` reported `worker_count=5`,
  `max_concurrent_agents=5`, `queued_depth=0`, Codex OAuth `logged_in`, and
  model proxy health `ok`.
- Startup self-heal requeued task `393` for ticket `1441` and task `396` for
  ticket `1445`.
- Ticket `1441` continuation agent `396` ran after self-heal and resolved the
  static-site deployment ticket.
- Ticket `1444` replacement agent `400` / task `397` ran through Codex and
  resolved the queue-health ticket.
- Ticket `1445` correctly stopped at a real access wall:
  `awaiting_access`, access request `61`, approval gate `320`.
- Final active-agent count after recovery was `0`; queue health remained
  `worker_count=5`, `queued_depth=0`.

## Agent Harness Validation

2026-05-21 Codex harness checkpoint:

- Direct Codex CLI proof passed inside the API container with
  `codex-cli 0.132.0`, model `local/agent-default`, proxy
  `http://ai-proxy:4001/v1`, and marker `CODEX_SKILLS_OK`.
- Dashboard-spawned Codex proof passed on ticket `1393`: agent `365`, task
  `362`, harness `codex`, model `local/agent-default`, note marker
  `CODEX_HARNESS_CLEAN_PASS`, ticket status `resolved`.
- Ops Chat remains harness-agnostic. `/api/ops-chat/message` accepts optional
  `harness` / `agent_harness` and `model` / `agent_model` fields for targeted
  smokes, while the Matrix bridge follows `OPS_CHAT_AGENT_HARNESS` when set or
  the global `AGENT_HARNESS` default when blank. After harness changes, verify
  Hermes default, explicit Codex, and Claude Code still execute through the
  same bridge contract.
- 2026-05-21 Ops Chat harness retest: health reported
  `available_harnesses=["claude-code","codex","hermes"]`, `codex-cli 0.132.0`,
  Claude Code `2.1.146`, and `ffmpeg 7.1.4`. Hermes remains the live default.
  Codex reaches the AI proxy through `/v1/responses` for both
  `qwen/qwen3.6-27b` and `deepseek/deepseek-v4-flash`, but those test model
  routes did not produce the required Codex tool call for `ops_chat_tool.py`
  within the one-hour local-agent window. Treat Codex as registered and
  proxy-connected, but not the demo Ops Chat engine until a tool-capable Codex
  account/model route is available.
- Codex OAuth/subscription mode uses `CODEX_AUTH_MODE=oauth`; verify
  `/api/agents/runner-health` reports `codex_login_status.status=logged_in`
  after `codex login --device-auth` completes. In OAuth mode the harness must
  not inject `model_provider="agentic_proxy"` or `OPENAI_API_KEY`.
- Codex noninteractive subprocesses must close stdin. If stdin is inherited,
  Codex can print `Reading additional input from stdin...` and wait instead of
  starting the task. The runner and Ops Chat harness launch Codex with
  `stdin=subprocess.DEVNULL`.
- OAuth proof after enrollment: `codex exec --json --output-last-message ...`
  with `--model gpt-5.5 --config reasoning_effort="high"` created
  `/tmp/codex_oauth_file_probe.txt` containing exactly `CODEX_FILE_OK`.
- Dashboard-spawned OAuth proof passed on ticket `1399`: agent `369`, task
  `366`, model `gpt-5.5`, harness `codex`, iTop ref `817`, provider sync
  `synced`, title length `240`, marker `CODEX_HARNESS_SYNC_OK`, ticket
  `resolved`, task `completed`, agent `finished`.
- Agent-memory proof passed on ticket `1400`: agent `370`, task `367`, iTop
  ref `818`, marker `CODEX_MEMORY_OK`; the spawned Codex agent used the
  container `python3` memory path, reported `driver=asyncpg`, and resolved the
  synced ticket.
- The API container mounts `/root/.agents/skills` from deployable
  `reference_skills`; Codex skill frontmatter loads cleanly.
- Containerized Codex uses `CODEX_SANDBOX=danger-full-access` because hardened
  Docker hosts commonly disable the unprivileged user namespaces required by
  `workspace-write`. The enforceable boundary remains dashboard RBAC, scoped
  vault leases, approval gates, and the API container.
- Ticket `1410` follow-up fixed two demo-polish regressions: large Codex JSONL
  stream events no longer fail the runner with `Separator is found, but chunk is
  longer than limit`, and outbound iTop creates now prefer the dashboard
  assignment group Team (`Identity & Access` for account work) before falling
  back to the legacy Security Team ID.

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

## Dashboard UI Overhaul Smoke

The 2026-05-21 console overhaul is documented in
`docs/UI_OVERHAUL_2026-05-21.md`. Required UI smoke coverage now includes:

- global search modal type/status/sort controls
- overview metric tile navigation
- sortable/filterable Intake, Tickets, Changes, Workflows, Postmortems, CI/CD,
  Learning, Skills, Tools, Access, and Audit surfaces
- Skills activate/deactivate/view/edit/profile assignment
- Settings profile skill checklist
- compact expandable audit rows
- Setup page without Runtime Handoff or Generated Setup Plan

Focused local pass:

```powershell
node --check frontend/js/dashboard.js
python -m py_compile api\routes\tickets.py api\services\agent_runner.py
python -m pytest tests/test_access_control_policy.py tests/test_agent_harness.py tests/test_frontend_ui_regressions.py tests/test_setup_module_scope.py tests/test_skill_sync_preserve.py -q
```

## Prohibited Pattern Sweep

Application code should not contain ORM/Pydantic/SQLAlchemy usage or hardcoded secrets.

```powershell
rg -n --glob '!README.md' --glob '!*.md' --glob '!__pycache__/**' "pydantic|sqlalchemy|sk-[A-Za-z0-9]{20,}|host\.docker|docker\.internal|soc_password_change_me|itop_admin" .\soc-dashboard\api .\soc-dashboard\frontend .\soc-dashboard\scripts .\soc-dashboard\docker-compose.yml
```

Expected result: no matches.

The database cleanup text may intentionally mention ComfyUI in `init_db.sql` only to remove it from inventory.

## Access RACI Routing

```bash
python scripts/smoke_access_raci_routing.py http://localhost:25480
```

Expected: Mailcow routes to Email Operations, Wazuh/SIEM to Security
Operations, GitLab to DevSecOps, Keycloak/IAM to Identity & Access, iTop to
Business Applications, Agentic Operations platform admin to Platform Operations,
and network controls to Network Operations.

## Ops Chat And Agent Intake

The full deployment and demo-readiness checkpoint lives in
`docs/OPS_CHAT_AGENTIC_UI_TESTING_AND_DEMO_READINESS.md`. Treat this section as
the quick runbook and the checkpoint doc as the evidence catalog. The detailed
2026-05-21 lifecycle hardening report lives in
`docs/OPS_CHAT_LIFECYCLE_TEST_REPORT_2026-05-21.md`.
The canonical Element/Keycloak prompt-handling bundle lives in
`docs/OPS_CHAT_PLAYWRIGHT_BUNDLE.md`; use that pattern for future Ops Chat UI
tests.

```bash
python3 scripts/smoke_ops_chat_scenarios.py http://localhost:25480
python3 scripts/smoke_ops_chat_scenarios.py http://localhost:25480 --spawn-agent --agent-case account-lockout --agent-timeout 420
python3 scripts/smoke_ops_chat_scenarios.py http://localhost:25480 --spawn-agent --agent-case software-request --agent-timeout 420
```

Browser proof from the API container or an operator workstation with Playwright:

```bash
DASHBOARD_URL=https://<host>:25443 \
DASHBOARD_USER=demo_account_1 \
DASHBOARD_PASSWORD=<from vault> \
OPS_CHAT_URL=https://<host>:3303 \
OPS_CHAT_USER=demo_account_1 \
OPS_CHAT_PASSWORD=<from vault> \
OPS_CHAT_SEND_MESSAGE=true \
OPS_CHAT_ALLOW_IDENTITY_RESET=false \
PLAYWRIGHT_IGNORE_HTTPS_ERRORS=true \
node scripts/smoke_ops_chat_playwright.js
```

For a demo account that already has a bot DM, prefer the deterministic room
path so Element does not detour through the profile/invite screens:

```powershell
$env:OPS_CHAT_ROOM_ID="!zSTElAvfSUDmAKZSWm:agentic-ops.local"
```

The smoke test intentionally skips/cancels Element device-verification and
encryption setup prompts. Ops Chat demo messages do not need end-to-end Matrix
encryption; the test goal is Keycloak login, same-origin Matrix health, bridge
delivery, dashboard ticket linkage, and agent response. Do not choose "confirm"
or reset digital identity during demo smoke unless explicitly testing Matrix
E2EE.

Latest live proof on 2026-05-21:

- Settings quick controls set `codex-primary`, fast mode on, low reasoning,
  and `max_concurrent_agents=5`.
- Element Playwright smoke logged in as `demo_account_1`, skipped verification,
  used the existing bot room, sent marker `demo-reliability-1779401709`, and
  received a ticket-linked agent response on ticket `1444`.
- The bridge and dashboard recorded the user message and outbound agent notes;
  final runner health showed no stuck active agents.

End-user UX proof through Element:

```powershell
$env:OPS_CHAT_URL="https://192.168.50.222:3303"
$env:OPS_CHAT_USER="demo_chat_direct4"
$env:OPS_CHAT_PASSWORD="<from vault>"
$env:PLAYWRIGHT_IGNORE_HTTPS_ERRORS="true"
node scripts/smoke_ops_chat_user_experience.js
```

One-room Element marathon proof:

```powershell
$env:OPS_CHAT_URL="https://192.168.50.222:3303"
$env:OPS_CHAT_USER="demo_chat_marathon5"
$env:OPS_CHAT_PASSWORD="<from vault: demo_chat_marathon5>"
$env:PLAYWRIGHT_IGNORE_HTTPS_ERRORS="true"
$env:OPS_CHAT_MARATHON_MARKER="ops-chat-marathon-<unique>"
node scripts/smoke_ops_chat_workspace_marathon.js
```

Developer artifact proof through Element:

```powershell
$env:OPS_CHAT_URL="https://192.168.50.222:3303"
$env:OPS_CHAT_USER="demo_chat_marathon5"
$env:OPS_CHAT_PASSWORD="<from vault: demo_chat_marathon5>"
$env:PLAYWRIGHT_IGNORE_HTTPS_ERRORS="true"
$env:OPS_CHAT_DEV_ARTIFACT_MARKER="ops-chat-dev-artifact-<unique>"
node scripts/smoke_ops_chat_dev_artifacts.js
```

Expected:

- harmless/general chat returns an answer without a ticket;
- benign current-information questions can use the private web-search tool
  without creating a ticket;
- ambiguous operational requests can ask one clarification before ticket
  creation;
- once enough context exists, the chat agent creates a ticket, preserves recent
  chat context in ticket evidence, syncs to the configured ticket provider, and
  queues the real Hermes/Claude ticket agent when enabled;
- follow-up chat becomes `user-response` notes;
- a room can contain harmless chat plus multiple tickets; the chat harness
  chooses answer/create/continue instead of the app blindly attaching every
  later message to the latest ticket;
- cancellation-like updates cancel the correct ticket and stop its active
  chat-created agent when one exists;
- replacement asks in the same room create a distinct ticket unless the harness
  explicitly decides it is a same-ticket scope update;
- `/api/tickets/{id}/assignment` can reassign or escalate the ticket with a
  `ticket-assignment` audit note.
- the marathon can keep one Matrix room open while the user asks unrelated
  harmless questions, opens several tickets, cancels specific tickets, asks for
  replacement work, updates scope on an existing urgent ticket, and asks for a
  room-scoped status summary.
- provider sync remains active for chat-created tickets, so iTop refs and sync
  status should be visible after each operational ticket.
- dev one-off artifact asks can return tested Python, HTML, Markdown, and Bash
  artifacts as rendered Element code blocks without creating tickets.

Latest verified result on 2026-05-20:

```text
clarification/reassignment: ticket 1176, iTop ref 595, Tier 2 Endpoint Support, P2
browser Element send: marker ops-chat-playwright-1779301274503, ticket 1177
real agent account-lockout: marker ops-chat-scenarios-1779301430, ticket 1185, agent 326
real agent software-request: marker ops-chat-scenarios-1779301734, ticket 1191, agent 327
active agents after cleanup: 0
browser UI retest: marker ops-chat-ui-exec-1779283445, ticket 1197, outbound chat user-response passed
50-case enterprise retest: marker ops-chat-enterprise-matrix-1779305167, tickets 1198-1248, 50/50 passed
post-guard real agent: marker ops-chat-scenarios-1779307368, ticket 1255, agent 333, canonical-ticket no-duplicate prompt verified
direct watermelon UX: session !ux-watermelon2-1779308718, tickets 1259 cancelled and 1260 pizza replacement, both synced to iTop
Element watermelon UX: marker ops-chat-ux-live-1779314587, tickets 1266 cancelled and 1267 pizza replacement, passed
Element one-room marathon: marker ops-chat-marathon-1779299559, tickets 1276 cancelled, 1277 in_progress, 1278 in_progress, 1279 in_progress, 1280 cancelled; iTop refs 695-699; real agents 350-352 spawned and then smoke-cleaned; active agents after cleanup 0
Element dev artifacts: marker ops-chat-dev-artifact-1780000005, Python/HTML/Markdown/Bash validated and rendered as code blocks; ticket delta 0 for all four cases
```

Latest verified result on 2026-05-21:

```text
broad enterprise matrix: marker ops-chat-enterprise-matrix-1779334693, tickets 1320-1368, 45/50 initial pass with iTop sync; misses documented and fixed
broad enterprise matrix rerun: marker ops-chat-enterprise-matrix-1779443778, targeted new-hire case created ticket 1595 / iTop 997 and routed to Identity & Access after the onboarding guidance fix
platform doctor: 19 passed, 0 failed after adding DASHBOARD_SERVICE_TOKEN support for auth-hardened dashboard API checks
focused enterprise rerun: marker ops-chat-enterprise-matrix-1779336161, tickets 1369-1373, 5/5 passed with iTop sync and cleanup
scenario lifecycle smoke: marker ops-chat-scenarios-1779336984, tickets 1378-1382, general chat/current-info/cat memory/account/software/VPN/phishing/delivery gate passed with cleanup
developer artifact UI: marker ops-chat-dev-artifact-1779337398804, Python/HTML/Markdown/Bash validated and rendered in Element; ticket delta 0
extended artifact/upload UI: marker hermes-ui-artifacts-1779355887, Python/HTML/Markdown/Bash validated, MP4 animation returned via animation-video helper, Matrix file upload returned as validated Markdown summary; ticket delta 0
multi-ticket lifecycle: marker ops-chat-multiticket-1779338352, watermelon 1384 cancelled, pizza 1385 created separately, account 1386 created and updated, summary answered with no new ticket
active agents after cleanup: 0
active processes after cleanup: 0
```

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
gitlab_keycloak_full_sso: PASS lands_in_gitlab=True
itop_rest_post: PASS code=0 count=1
wazuh_dashboard_login_endpoint: PASS http=200
mailcow_mailbox: PASS exists=True
wazuh_api_auth: PASS token_issued=True
```

Important implementation notes:

- Wazuh Dashboard auth requires OpenSearch Security `internal_users.yml` sync and `securityadmin.sh` reload.
- Native Wazuh API auth is separate from Dashboard auth; verify both paths
  before demos because the UI can work while API RBAC is stale.
- iTop demo users must be real `UserLocal` objects with `Administrator` and `REST Services User`; raw partial rows can be counted by OQL but fail object reload and login.
- GitLab local login requires a valid personal namespace on the GitLab user. Missing namespace causes the generic GitLab 422 page even when the password is correct.
- GitLab OIDC requires the Keycloak CA in GitLab trusted certs. The live demo
  uses `https://192.168.50.222:8443/realms/gitlab` as the browser-routable
  issuer; `keycloak.internal:host-gateway` may remain in compose only as a
  container-side compatibility alias.
- GitLab OIDC also depends on Keycloak protocol mapper shape. The setup script
  updates existing mappers idempotently; rerun it if GitLab SSO fails with an
  opaque OmniAuth `Unknown error` after Keycloak changes.
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
- `/api/cicd/runs/{run_id}/reports/semgrep` dashboard-readable Semgrep evidence
- external CI artifact links marked as provider-authenticated
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
- Dashboard scanner report links are the operator-readable source of truth for
  demos; GitLab artifact links may require a separate provider login.
- The Trivy Docker image command should be `fs ...` because the image entrypoint
  is already `trivy`.

## Global Search Smoke

```bash
cd /home/cereal/SOC_TESTING/soc-dashboard
export DASHBOARD_SERVICE_TOKEN=<from runtime secret source>
python3 scripts/smoke_global_search.py http://localhost:25480
```

Covers:

- authenticated `/api/search/global`
- row-level ticket and ticket-note search
- UI-safe search result shape
- no dependency on unauthenticated dashboard APIs

## Ops Chat Smoke

```bash
cd /home/cereal/SOC_TESTING/soc-dashboard
export DASHBOARD_SERVICE_TOKEN=<from runtime secret source>
python3 scripts/smoke_ops_chat.py http://localhost:25480
```

Covers:

- direct dashboard chat intake
- Matrix/Element readiness metadata from `/api/ops-chat/matrix/health`
- ticket creation from chat
- real dashboard agent harness queue handoff for operational work
- follow-up chat continuing the same ticket through `user-response` notes
- `Ops Chat agent-created ticket` note in ticket context
- outbound delivery of user-facing `/request-info` and ticket status notes to
  Matrix via `/api/ops-chat/outbound/pending` and idempotent ack
- dashboard service-token authentication for the Matrix bridge

## Ops Chat Scenario Smoke

```bash
cd /home/cereal/SOC_TESTING/soc-dashboard
export DASHBOARD_SERVICE_TOKEN=<from runtime secret source>
python3 scripts/smoke_ops_chat_scenarios.py http://localhost:25480
python3 scripts/smoke_ops_chat_scenarios.py http://localhost:25480 --spawn-agent --agent-timeout 600
python3 scripts/smoke_ops_chat_scenarios.py http://localhost:25480 --spawn-agent --all-agent-cases --agent-timeout 600
python3 scripts/smoke_ops_chat_enterprise_matrix.py http://localhost:25480
```

Covers a demo-realistic conversation set:

- general chat that does not create a ticket
- account lockout routed to Identity & Access
- software request routed to Endpoint Support
- VPN connectivity routed to Network Operations
- phishing report routed to Security Operations without an intake-time approval
  gate; containment gates must appear only during downstream ticket execution
- CI/CD delivery-gate request routed to DevSecOps without an intake-time
  approval gate; deployment gates must appear only during downstream execution
- chat follow-up recorded as a `user-response` note
- global search visibility for all scenario tickets
- optional real Hermes/Claude agent handoff through the configured proxy
- 50-case no-spawn enterprise chat coverage for broad demo prompts

For browser-level proof, use Playwright against
`https://<host>:3303`. The expected path is: Element login through Keycloak,
DM invite to `@agentic-ops:agentic-ops.local`, appservice auto-join, dashboard
ticket creation, and real harness spawn when `spawn_agent` policy allows it.

Latest live result on 2026-05-20:

```text
smoke_ops_chat_scenarios.py: PASS marker=ops-chat-scenarios-1779250145
general chat: no ticket
account-lockout: ticket 750, Identity & Access
software-request: ticket 751, Endpoint Support
phishing-report: ticket 752, change 204, Security Operations
deployment-gate: ticket 753, change 205, DevSecOps
real-agent-handoff: ticket 754, agent 284, task 281, Hermes/deepseek-v4-flash
final state: ticket 754 awaiting_user_response, no active agents
```

Follow-up proof:

```text
ticket 749: first chat agent 282 asked which system the user could not access
user replied through Ops Chat with Keycloak/SSO details
continuation agent 283 wrote user-facing Keycloak/SSO troubleshooting guidance
ticket 749 ended awaiting_user_response with clean agent/task status
```

Additional live regression on 2026-05-20:

```text
all-agent-cases marker=ops-chat-scenarios-1779250846: PASS
account lockout: ticket 769, agent 285, awaiting_user_response
delivery gate: ticket 770, agent 286, awaiting_user_response
phishing + EDR: ticket 771, agent 287, blocked at approval
software request: ticket 772, agent 288 asked for details
VPN outage: ticket 773, agent 289 asked whether this was VPN or access
software follow-up: ticket 772, continuation agent 291 completed detail collection/routing
VPN follow-up: ticket 773, continuation agent 292 completed triage and identified Network/VPN handoff
placeholder-note guardrail rerun: ticket 778, agent 290, no "test note", stopped at pending_approval
VPN routing rerun: ticket 781, intent vpn-connectivity, Network Operations
approval-resume rerun: ticket 784, change 223 bound to agent 293, approval spawned agent 294, change completed, ticket closed
final state: no active dashboard agents and no active Hermes processes
```

Latest Element/Matrix UI proof on 2026-05-20:

```text
Direct bot-profile UI path: PASS
URL: https://192.168.50.222:3303/#/user/@agentic-ops:agentic-ops.local
Profile: Agentic Ops Agent
Action: clicked Send message, sent a GitLab login request
Marker: element-direct-agent-ui-1779283071
Ticket: 909
Agent: 308 / task 305

smoke_ops_chat_playwright.js: PASS without HTTPS bypass
Dashboard login: PASS as demo_account_1
Element login: PASS as demo_chat_live11 at https://192.168.50.222:3303/#/home
Same-origin Matrix probe: PASS at https://192.168.50.222:3303/_matrix/client/versions
Matrix UI DM marker: ops-chat-same-origin-playwright-1779261056
Dashboard ticket: 908
Agent: 307 / task 304
Final ticket state: awaiting_user_response
Final active agents: 0

Element login: PASS as demo_chat_alice at https://192.168.50.222:3303/#/home
Matrix UI DM marker: matrix-ui-live-chat-1779258900
Room: !ggxyGdDLBtBqDWoygC:agentic-ops.local
Dashboard ticket: 907
Agent: 306 / task 303
Final ticket state: awaiting_user_response
Global search: marker returned ticket 907
Final active agents: 0
```

Latest broad-routing proof:

```text
smoke_ops_chat_enterprise_matrix.py: PASS
marker: ops-chat-enterprise-matrix-1779257312
case_count: 50
failure_count: 0
tickets: 846-895
covered groups: Executive Support, Identity & Access, Email Operations,
Security Operations, Network Operations, Endpoint Support, Procurement &
Vendor Management, Infrastructure Operations, Cloud Operations, Database
Operations, Business Applications, DevSecOps, Compliance & Audit, Platform
Operations
```

Latest all-agent scenario proof:

```text
smoke_ops_chat_scenarios.py --spawn-agent --all-agent-cases: PASS
marker: ops-chat-scenarios-1779257332
tickets: 896-906
agents: 301-305 plus Matrix UI agent 306
final state: no active dashboard agents
```

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

The demo approval flow should make it obvious that a guardrail exists. Live
demos should use manual dashboard approval; auto-approval is reserved for
unattended regression runs.

Verification on the main dashboard:

```bash
BASE=http://localhost:25480
TICKET=$(curl -sS -X POST "$BASE/api/tickets" \
  -H 'Content-Type: application/json' \
  -d '{"title":"Demo transparent approval gate verification","description":"Verify approval gates show opened, approved, and completed notes/audit details.","provider":"local","sync_provider":false,"created_by":"approval-gate-test"}' \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["id"])')

CHANGE=$(curl -sS -X POST "$BASE/api/changes/request" \
  -H 'Content-Type: application/json' \
  -d "{\"ticket_id\":$TICKET,\"action\":\"demo_block_url\",\"target\":\"https://example.invalid/phish\",\"reason\":\"Demonstrate a guardrailed remediation approval chain.\",\"risk_level\":\"medium\",\"approval_policy\":{\"requires_human\":true}}" \
  | python3 -c 'import json,sys; print(json.load(sys.stdin)["change_id"])')

curl -sS -X POST "$BASE/api/changes/$CHANGE/approve" \
  -H 'Content-Type: application/json' \
  -d '{"approved_by":"demo-operator","reason":"Operator reviewed the evidence and approved the scoped lab action."}'

curl -sS -X POST "$BASE/api/changes/$CHANGE/complete" \
  -H 'Content-Type: application/json' \
  -d '{"completed_by":"approval-gate-test","result":"No production action executed. Demo gate lifecycle verified with audit and notes."}'
```

Latest verified result:

```text
ticket_id=102
change_id=52
change_status=completed
approved_by=demo-operator
note_count=3
has_gate_opened_note=true
has_manual_approved_note=true
has_completed_note=true
manual_audit_entries=4
audit_sources=audit,event,note
active_agent_processes=0
```

Frontend asset verification:

```text
served /static/js/dashboard.js contains Approval Gate
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

## Roundcube Webmail / Tools Regression - 2026-05-18

Source and local checks:

```text
python -m py_compile api/services/health_check.py api/routes/tools.py scripts/platform_doctor.py scripts/smoke_operational_metrics.py reference_skills/keycloak-mailcow-bridge/scripts/deploy_mailcow_api.py reference_skills/keycloak-mailcow-bridge/scripts/debug_deploy.py
python scripts/sync_reference_skills.py manifest  # 37 skills, 0 missing
python scripts/text_hygiene.py                    # passed
git diff --check                                  # passed
python -m pytest tests -q                         # 131 passed
```

Do not use bare `python -m pytest` from the repository root unless all live
integration `.env` files are present. Root collection also discovers reference
skill integration scripts such as `keycloak-mailcow-bridge/scripts/test_integration.py`,
which intentionally exits when its deployment `.env` is absent.

Live dashboard checks:

```text
python3 scripts/platform_doctor.py --base http://127.0.0.1:25480
python3 scripts/smoke_operational_metrics.py http://127.0.0.1:25480
python3 scripts/smoke_setup_platform.py http://127.0.0.1:25480
python3 scripts/smoke_setup_agent.py http://127.0.0.1:25480
```

Results:

- Platform doctor: `19 passed, 0 warned, 0 failed`.
- Operational metrics smoke: passed; setup modules include
  `Roundcube Webmail Client`, and tools include healthy `Roundcube Webmail`.
- Setup platform smoke: passed, setup ticket `582`.
- Setup agent smoke: passed, setup ticket `583`, agent `230`, task `227`.
- `/api/tools/check-all`: `Mailcow API/UI Shim` healthy and `Roundcube Webmail`
  healthy.

## Keycloak Admin UI / GitLab OIDC Regression - 2026-05-18

Live target: AI server `192.168.50.222`.

Changes validated:

- Keycloak Admin Console is accessible at
  `https://192.168.50.222:8443/admin/master/console/`.
- Keycloak `KC_HOSTNAME` and `KC_HOSTNAME_ADMIN` use the browser-routable
  full URL `https://192.168.50.222:8443`.
- GitLab OmniAuth issuer now matches the browser-routable realm issuer:
  `https://192.168.50.222:8443/realms/gitlab`.
- Historical hardcoded GitLab OIDC client secret was removed from source and
  the live Keycloak GitLab client secret was rotated.

Validation:

```text
Playwright Keycloak Admin Console login: PASS
  URL: https://192.168.50.222:8443/admin/master/console/
  visible markers: Manage realms, Realm settings, Clients, Users, Sessions,
  Events, master

python3 scripts/test_keycloak.py --url http://localhost:8080
  PASSED: 26
  FAILED: 0

bash /home/cereal/gitlab-keycloak-integration/scripts/diagnose.sh
  13 passed, 0 warnings, 0 failed

bash /home/cereal/gitlab-keycloak-integration/scripts/test_integration.sh
  Total: 27
  Passed: 27
  Failed: 0
  Skipped: 0

Playwright GitLab Keycloak full SSO check: PASS
  Final URL: http://192.168.50.222/
  visible markers: SOC Demo Account user's menu, Projects, Admin
```

Mailcow/Roundcube checks:

```text
cd /home/cereal/Mailcow/deploy
python3 scripts/deploy_mailcow_api.py
python3 scripts/test_mailcow_api_shim.py --mysql-parity
curl -fsS http://127.0.0.1:2581/webmail/ | grep -q Roundcube
docker exec roundcube-mailcow-demo sh -lc 'php -l /var/www/html/plugins/report_phish/report_phish.php && php -l /var/www/html/plugins/report_phish/localization/en_US.inc'
docker exec php-fpm-mailcow-api sh -lc 'php -l /web/mailcow_demo_report.php'
```

Results:

- Mailcow API/UI/Roundcube deployer: passed all built-in checks.
- Mailcow API shim regression: `13 passed, 0 failed`.
- Roundcube route check: passed.
- Roundcube plugin PHP lint: passed.
- Hidden report endpoint PHP lint: passed.

## Static Site Deployment Boundary - 2026-05-21

Regression covered:

- Agent-created web pages must not be marked deployed when they are only served
  by a container-local preview URL.
- Real dashboard-reachable static page publishing must require an approved
  change gate and go through the managed static-site deployment adapter.

Local verification:

```text
python -m py_compile api\app.py api\routes\agents.py api\routes\ops_chat.py api\services\access_control.py api\services\static_deployments.py api\services\task_prompts.py
python -m pytest -q tests\test_static_site_deployment_adapter.py tests\test_access_control_policy.py tests\test_deployment_boundary_prompts.py
docker compose config --quiet
```

Expected:

- Static publish copies a valid tree into the configured published-site root.
- Path escape, missing `index.html`, symlinks, and unsafe file types are
  rejected.
- `POST /api/agents/{agent_id}/deploy/static-site` requires an approved gate
  linked to the same agent/ticket, completes the gate, writes a ticket note,
  and records `static_site_deployed`.
- Auth policy maps the route to `deployments:write`; `/published/...` remains
  behind dashboard `ui:read`.
- Agent prompts say `127.0.0.1` inside the API container is preview evidence,
  not a durable deployment.

Live AI server verification:

```text
python3 scripts/smoke_static_site_deployment.py
```

Result on 2026-05-21:

- `ok=true`
- ticket `1415`
- agent `383`
- task `380`
- change gate `312`
- published URL:
  `https://192.168.50.222:25443/published/static-site-deploy-smoke-1779382884/`
- returned page rendered the smoke marker through the dashboard HTTPS edge.
- `/api/agents/active` returned zero active agents after the smoke cleaned up
  its synthetic task/agent/ticket.
