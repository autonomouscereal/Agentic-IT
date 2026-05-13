# Known Issues And Fix Log

Last updated: 2026-05-12.

## Fixed In Current Pass

### Acceptance reruns could hit API before restart finished

Problem:

- A live provider-adapter smoke rerun immediately after `docker compose restart api`
  hit `/api/providers` before Uvicorn was fully ready and raised
  `ConnectionResetError: [Errno 104] Connection reset by peer`.

Fix:

- Acceptance scripts and manual reruns should wait on `/health` after restarting
  the API before calling route-level smoke tests.

Verified:

- Rerun command waited on `/health` and completed provider-adapter smoke after
  the API rebuild/recreate sequence.

### Python service hot uploads do not change the running API container

Problem:

- Uploading `api/services/auto_assignment.py` to the live host source tree and
  restarting the API container did not change the code running inside `/app`.
- The API image bakes Python service files at build time; only selected volumes
  such as frontend, platform, skills, and agent work are mounted.

Impact:

- A policy fix can appear deployed on the host but still run old code until the
  API image is rebuilt.

Fix:

- For Python API/service/route changes, run `docker compose up -d --build api`
  after updating the host source.
- Keep simple restarts for frontend/skill/config changes that are actually
  mounted into the container.

Verified:

- Rebuilt API with `docker compose up -d --build api`.
- Container-side `_score_rule` returned `{'class_only_score': 0}`.
- `python3 scripts/smoke_provider_adapters.py http://localhost:25480` created
  ticket `174` and `GET /api/agents/active` remained empty afterward.

### Change auto-completion smoke command used the wrong container path

Status: fixed during the 2026-05-12 full acceptance regression pass.

Problem:

- The full regression command tried to run `python smoke_change_auto_completion.py`
  inside the API container.
- The script lives under `scripts/` in the source tree and is not mounted into
  `/app` by the running API container.

Impact:

- Baseline regression stopped at the approved-change auto-completion check even
  though earlier platform doctor, provider, intake, workflow, CI/CD, and auditor
  smokes passed.

Fix:

- Document the correct pattern: copy `scripts/smoke_change_auto_completion.py`
  into the API container, then run `/app/smoke_change_auto_completion.py`.
- Updated the acceptance command script to use the same copy-and-run pattern.

Verified:

- `docker compose cp scripts/smoke_change_auto_completion.py api:/app/smoke_change_auto_completion.py`: PASS.
- `docker compose exec -T api python /app/smoke_change_auto_completion.py`: PASS
  with ticket `172`, agent `76`, task `74`, change `82`, and
  `change_status=completed`.

### `ps` missing in API container

Problem:

- Agent process diagnostics could not work in the slim Python image.

Fix:

- API image installs `procps`.
- `/api/agents/processes` now reports `ps_path=/usr/bin/ps`.

### Wake/restart were not trustworthy enough

Problem:

- UI could show running/wake/restart state without proving a harness process existed.

Fix:

- Wake now checks active tasks and either refreshes heartbeat or spawns a replacement.
- Restart stops active task, terminates old agent row, and spawns replacement.
- Process diagnostics expose actual runner process state.

### Claude Code allowed-tools command ordering

Problem:

- Putting `--allowedTools` late in the command caused it to swallow the prompt because it is variadic.

Fix:

- `agent_harness.py` puts `--allowedTools` before `-p`.

### Full bypass refused as root

Problem:

- Claude Code refuses bypass mode from the current root-run API container.

Fix:

- Managed agents use `acceptEdits` and `Read,Write,Bash(curl *)`.

### Model process kept running after useful completion

Problem:

- Agent could write done checkpoint while the Claude process kept consuming GPU.

Fix:

- `task_tracker` completes the task from the done checkpoint and terminates the harness process.

### Docker-host style model route avoided

Problem:

- Docker networking aliases are fragile in this lab.

Fix:

- `AGENT_LLM_BASE_URL` uses routable LAN proxy URL, currently `http://192.168.50.222:4001`.

### Fresh DB init missing new approval columns

Problem:

- `init_db.sql` had older `change_requests` columns while route code writes `risk_level` and `approval_policy`.

Fix:

- Fresh schema now includes both columns.
- Existing deployments still use migration 003.

### iTop hardwired in compose

Problem:

- `docker-compose.yml` pinned `ITOP_HOST` to the lab IP and required iTop credentials.

Fix:

- `ITOP_HOST`, `ITOP_USER`, and `ITOP_PASSWORD` are environment-driven.
- `ITOP_SYNC_ENABLED=false` supports local-only/non-iTop deployments.

### Dashboard-created provider tickets did not actually push outward

Problem:

- `sync_provider=true` only marked tickets `pending_create`.

Fix:

- Added provider `create_ticket` contract.
- Added local provider create/push.
- Added guarded iTop outbound create.
- Added `POST /api/tickets/{id}/push-provider`.

### Non-iTop tickets could get iTop-shaped URLs

Problem:

- URL generation assumed iTop when refs looked non-local.

Fix:

- `external_ticket_url()` now returns provider URL first and only builds iTop URLs for iTop tickets.

### ComfyUI should not be in tool dashboard

Fix:

- Default tools omit ComfyUI.
- `init_db.sql` deletes existing ComfyUI row if present.

### Demo credentials were inconsistent across platforms

Problem:

- `/home/cereal/multiplatform_user_manager.py` had hardcoded iTop/Mailcow DB passwords, shell-expanded password hashes, a Wazuh scrypt salt mismatch, and no Wazuh Dashboard internal-user sync.
- `demo_account_1` worked in some backing databases but failed real auth checks.

Fix:

- Removed hardcoded DB passwords; iTop/Mailcow credentials now resolve from container environment or explicit env vars.
- Reworked SQL execution to stream SQL over stdin, avoiding bcrypt/scrypt `$` shell expansion.
- Switched Wazuh to native API updates first, with RBAC SQLite as fallback, and added Wazuh Dashboard OpenSearch Security sync.
- Rebuilt the iTop demo account as a valid `UserLocal` object with `Administrator` and `REST Services User` profiles.
- Rotated vault key `demo_account_1` and scrubbed the old failed debug password from iTop `error.log`.

Verified:

- iTop REST login returns `code:0`.
- Wazuh API auth returns HTTP 200.
- Wazuh Dashboard backend auth recognizes `demo_account_1`.
- GitLab Rails `valid_password?` passes and the account is active/admin.
- Mailcow mailbox exists.

### Agent timeout default could kill valid local-model runs

Problem:

- Local 256k-context runs can legitimately take a long time, and a fixed harness timeout can kill useful work while the model is still generating.

Fix:

- Installer, compose defaults, and `.env.example` now default `AGENT_TIMEOUT_MINUTES=0`.
- Local-model deployments should default to `MAX_CONCURRENT_AGENTS=1` until faster models are available. This prevents queued work from saturating the model and creating false stalled-agent symptoms.
- `AGENT_NO_OUTPUT_STALL_SECONDS` is configurable and defaults to `3600` for this environment. It is a last-resort silent-harness guard, not a short task timeout; agents that are streaming output or using tools should continue.
- The agent auditor is the supervision path and defaults to `AGENT_AUDITOR_AUTO_RECOVER=false` so recovery is auditable before being made automatic.
- Existing deployments can run `python3 scripts/repair_agent_supervision_env.py --env-file .env`, then recreate the API container.

### Agent note API dropped evidence when local agents used `content`

Problem:

- A real local-agent closure proof on ticket `340` completed and resolved the
  ticket, but the agent used `content` in `POST /api/tickets/340/notes`.
- The route accepted `body`, `note`, and `title` only, so notes `420` and `421`
  stored the titles without the detailed evidence body.

Fix:

- `POST /api/tickets/{ticket_id}/notes` now accepts `content` as a compatibility
  alias and combines it with `title` the same way it already handled `body` and
  `note`.
- Added unit coverage in `tests/test_agent_lifecycle_guards.py`.

Verified:

- Direct API proof ticket `341` created note `424` with title and full `content`
  body retained.
- Real local-agent closure proof V2 created ticket `342`, agent `113`, task
  `110`, notes `427` and `428` with full evidence bodies, checkpoint note `429`,
  completion note `430`, and final ticket status `resolved`.

### SIEM bridge EDR fanout can create too many local agents

Problem:

- A successful EDR/Sysmon rerun created multiple bridge tickets for closely
  related marker alerts, then RACI auto-assignment spawned agents for each.
- That behavior proves the bridge and auto-assignment hooks work, but it can
  saturate the current one-local-model lab and obscure the single incident
  narrative in demos.

Fix:

- The SIEM bridge now stores `ticket_correlation_keys` in bridge state.
- Exact alert dedup still works as before, while cross-rule correlation collapses
  alerts with an explicit `correlation_key` or marker such as `CODEX_*` into the
  first ticket for that incident.
- Added unit coverage proving two Sysmon marker alerts with different rules but
  the same marker produce one ticket and one correlated event.
- RACI auto-assignment now also enforces
  `AUTO_ASSIGNMENT_MAX_ACTIVE_PER_RULE=1` by default so related EDR/SIEM tickets
  do not queue several same-rule local agents while one matching agent is
  already active.

Verified:

- Recovery marker `CODEX_SYSMON_E2E_RECOVERY_1778630817` produced two Wazuh
  alerts but one bridge correlation key after the next poll.
- Live cap proof tickets `351` and `352` showed the first same-rule ticket
  assigned agent `122`; the second skipped with
  `auto_assignment_capacity_reached`. The proof agent was stopped immediately
  after verification.

### Mailcow HTTP API shim missing compatibility pieces

Full blueprint and runbook: `docs/MAILCOW_API_SHIM.md`.

Problem:

- The optional Mailcow HTTP API shim could reject valid API keys or return empty bodies because nginx did not forward `X-API-Key` into FastCGI and the mounted web code expected an `identity_provider` table.
- The stock `json_api.php` path can still return HTTP 200 with empty bodies for `get/domain/all` and `get/alias/all`, or `{}` for `get/mailbox/all`, in the custom reference deployment even though direct MySQL contains real data.

Fix:

- `deploy_mailcow_api.py` now forwards `HTTP_X_API_KEY`, sets `HTTP_SEC_FETCH_DEST=empty`, preserves content type, creates the `identity_provider` compatibility table, and stops printing API keys.
- The API shim now installs `mailcow_compat_api.php` and routes read-only `GET /api/v1/get/domain/*`, `GET /api/v1/get/mailbox/*`, and `GET /api/v1/get/alias/*` calls through that compatibility endpoint when the stock API path is unreliable.
- The compatibility endpoint validates `X-API-Key` against the Mailcow `api` table, uses the Mailcow DB connection from mounted Mailcow config/environment, and intentionally omits mailbox password hashes from responses.
- Invalid keys must return HTTP 401 during verification.
- Existing deployments that have shim containers but no restricted key file can run `bash scripts/repair_mailcow_api_keyfile.sh`.
- Fresh or repaired deployments should run `python3 scripts/deploy_mailcow_api.py`, then `python3 scripts/test_mailcow_api_shim.py --mysql-parity`.

Current note:

- Direct MySQL remains the canonical Mailcow bridge fallback for the reference deployment. The HTTP API shim is now usable for read-only compatibility checks and future provider-style tooling.
- The deployer no longer requires host-side `MYSQL_ROOT_PASSWORD`; it runs SQL inside the `mysql-mailcow` container using the container-held environment and writes the API key only to the restricted `api-nginx/.api_key` file.

Verified:

- Invalid API key returns HTTP `401`.
- Valid API key returns HTTP `200` with `2` domains, `11` mailboxes, and `6` aliases.
- Direct MySQL smoke confirms the same underlying counts.
- 2026-05-12 regression: `test_mailcow_api_shim.py --mysql-parity` passed `13/13`; platform doctor passed `18/18`; Keycloak-Mailcow bridge E2E passed `47/48` with `1` expected skip for the undeclared Keycloak custom attribute.

### Sysmon EDR test required manual secret injection

Problem:

- The EDR/Sysmon E2E test defaulted secret fields to empty strings and used POST for read-only Wazuh Indexer endpoints.

Fix:

- The test now reads deployed container/env-file values when explicit environment variables are absent, does not print secrets, uses GET for read-only indexer checks, and fixes the iTop REST URL encoding path.

### Sysmon EDR was green but not ingesting fresh endpoint telemetry

Problem:

- The old EDR/Sysmon test proved Wazuh, rules, iTop, and bridge primitives, but
  it did not prove current Sysmon events were reaching Wazuh alerts.
- SysmonForLinux was writing syslog-prefixed XML to
  `/var/log/sysmon/sysmon.log`.
- Wazuh was configured with `<log_format>json</log_format>` for that file.
- After changing the parser, the 15GB historical hot log filled the Wazuh
  logcollector queue and delayed fresh alerts.
- A later deployment pass exposed additional reality: the reference Linux
  Sysmon config used wrapper-style elements that SysmonForLinux v1.5.1/schema
  4.90 rejects, the generated systemd unit started the binary without the
  service install arguments, and the exact marker rule was standalone instead
  of a child of the level-0 Sysmon catch-all.

Fix:

- Wazuh Sysmon localfile now uses `<log_format>syslog</log_format>`.
- The oversized hot log was moved to a timestamped archive and a fresh hot log
  was created.
- `deploy-sysmon-linux.sh` now targets `/var/log/sysmon/sysmon.log` and installs
  a logrotate policy.
- `deploy-sysmon-linux.sh` now installs `rsyslog`, writes an early
  `/etc/rsyslog.d/10-sysmon-forward.conf`, validates/reinstalls SysmonForLinux
  through the Microsoft binary's own `-i <config>` flow, and avoids hand-written
  bad service units.
- `sysmon_config_linux.xml` now uses SysmonForLinux 4.90-compatible filters.
- `sysmon_decoder.xml` was reduced to a valid minimal decoder; the invalid
  `<location>` decoder was removed from the live manager.
- Rule `100230` is now the exact-marker child of base Sysmon rule `100200` for
  real Sysmon XML events, and rule `100231` is a raw-marker fallback for manager
  diagnostics. This preserves the real file-create E2E path while still making
  direct marker injection easy to test.
- `deploy-edr.sh` now detects when the live manager already has the broader
  Sysmon rule set in `local_rules.xml` and installs only
  `sysmon_marker_rules.xml` in that case, avoiding duplicate rule warnings.
- The E2E test now generates a unique `/tmp/CODEX_SYSMON_*.txt` file and
  verifies that exact marker in Wazuh Indexer.

Verified:

- Dashboard changes `37` and `38` were approved and completed.
- Wazuh EDR/Sysmon E2E passes `16/16`.
- 2026-05-12 regression passed with exact marker
  `CODEX_SYSMON_E2E_1778567257`, two alerts in Wazuh Indexer, `271` Sysmon
  rules searchable, Wazuh Indexer green, iTop API authenticated, live decoder
  shape verified for Wazuh 4.14, and bridge state valid.
- Logtest confirmed the XML Sysmon file-create marker fires rule `100230`.
- Logtest no longer emits duplicate Sysmon rule warnings after the marker-only
  live-manager install path.

### Legacy live test scripts drifted from current providers

Problem:

- `report_phish/test_reporter.py` imported old backend factory names that are
  no longer exported after the internal Mailcow SMTP backend became canonical.
- `itop-deployment/scripts/test_itop.py` and `test_approval_chain.py` assumed
  outdated iTop classes/fields (`Request`, `Problem`, `risk`, missing `org_id`,
  and missing `fallback` for `ev_plan`).
- `wazuh_deploy/test_wazuh.py` required pytest and embedded credentials.
- `log_forwarder/test_logtest.py` called `/var/ossec/bin/wazuh-logtest` on the
  host even though Wazuh runs in the manager container.
- `report_phish/backends/internal_email.py` defaulted Wazuh credentials to
  placeholder strings, causing an avoidable Wazuh auth failure during a
  successful internal Mailcow report.

Fix:

- Replaced `test_reporter.py` with a compatibility test around
  `PhishReporter` + `InternalEmailBackend`.
- Replaced the iTop tests with current-schema tests for Organization, Team,
  Person, Incident, UserRequest, NormalChange approval, and Incident pending.
- Replaced `test_wazuh.py` with a stdlib-only test that reads Wazuh credentials
  from the running container environment and does not print or store secrets.
- Updated `log_forwarder/test_logtest.py` to execute
  `/var/ossec/bin/wazuh-logtest` through `docker exec -i
  wazuh_deploy-wazuh.manager-1`.
- Updated the report-phish internal backend so Wazuh forwarding is enabled only
  when `WAZUH_API_PASSWORD` is supplied, with user/password read from
  environment variables instead of placeholders.

Verified:

- `report_phish/test_reporter.py`: passed.
- `itop-deployment/scripts/test_itop.py`: passed.
- `itop-deployment/scripts/test_approval_chain.py`: passed, including
  `ev_plan`, `ev_approve`, `ev_implement`, and incident `ev_pending`.
- `wazuh_deploy/test_wazuh.py`: passed.
- `log_forwarder/test_logtest.py`: passed.
- `report_phish/test_report.py`: passed with Wazuh forwarding explicitly
  disabled when no Wazuh credential env is present.

### Full CI/CD demo found scanner wrapper edge cases

Problem:

- The full local-model remediation run originally ended with a `needs_review`
  gate even after the agent fixed the intended source vulnerabilities.
- The Trivy Docker call passed `trivy fs ...` into an image whose entrypoint is
  already `trivy`.
- OWASP ZAP baseline returned exit code `2`, which means warnings were present,
  but the wrapper treated it as a scanner execution failure.

Fix:

- Docker Trivy invocations now pass `fs ...`.
- ZAP exit code `2` is treated as completed-with-findings.
- The gate status is decided by finding severity, with high/critical findings
  blocking production deployment and low/medium warnings recorded as evidence.

Verified:

- Ticket `82`, final scanner run `10` passed after local-model remediation.
- Semgrep, Trivy, OWASP ZAP, and Nuclei all completed.
- Change `36` was approved and completed; superseded change `35` was rejected.

### GitLab Runner CI/CD demo needed runner networking fixes

Problem:

- The first GitLab-backed demo project created a pipeline that stayed pending
  because the project runner was not attached to the new project.
- Docker job containers could not resolve the GitLab service name, so artifact
  upload/download failed even when scanner jobs completed.
- OWASP ZAP could not write JSON output until `/zap/wrk` existed as a mounted
  writable directory.
- GitLab job containers cannot use `localhost` for dashboard callbacks because
  `localhost` points to the job container, not the host/dashboard.

Fix:

- `agentic_gitlab_cicd_demo.py` now attaches the first available runner to the
  generated project when required.
- The reference runner config uses `network_mode = "gitlab-net"` so job
  containers can resolve and reach the GitLab container.
- The reference runner config mounts `/tmp/zap-wrk:/zap/wrk`.
- The demo script supports a separate runner-facing dashboard URL and defaults
  `SOC_DASHBOARD_URL` to `http://192.168.50.222:25480` for the lab.
- ZAP writes to `/zap/wrk/zap.json` and then copies that artifact into the
  project workspace.

Verified:

- Ticket `83` created from the GitLab security gate.
- GitLab pipeline `9` ran unit tests, Semgrep, Trivy, ZAP, and Nuclei, then
  failed the dashboard gate as intended.
- Dashboard CI/CD run `11` recorded seven findings.
- Local model remediation agent `50` requested change `39` before edits.
- After approval, the agent fixed the app, committed to branch
  `agent/remediate-security-gate`, and opened MR `!1`.
- GitLab pipeline `10` passed.
- Dashboard CI/CD run `12` passed with zero findings.
- Deployment change `40` was approved and completed.

### Agent postmortem context can be too large for slow local models

Problem:

- The postmortem task for the full CI/CD demo fetched the entire ticket context,
  including large prior agent logs and attachments.
- The model remained alive but slow after receiving a large payload.
- The first postmortem agent process exited successfully but did not create the
  required `postmortems` row, so process exit alone was not enough to prove task
  completion.

Resolution:

- Added `GET /api/postmortems/evidence/{ticket_id}` so postmortem agents receive
  bounded, scoped evidence instead of raw ticket context, full scanner JSON, or
  full agent logs.
- The endpoint now returns compact ticket context, notes, attachment metadata,
  change requests, task summaries, CI/CD severity counts and sampled findings,
  prior postmortems, and a short audit/event slice.
- The runner now treats postmortem tasks as failed if they exit without creating
  a postmortem artifact for the ticket/task.
- Added supervisor fallback `POST /api/postmortems/synthesize/{ticket_id}`.
  If local-model postmortem agents stall or fail, the platform creates a
  `ready_for_review` postmortem from bounded evidence and logs the synthesis.
- Postmortem agents no longer reopen the resolved ticket or replace the
  ticket's primary resolver agent.

### GitLab demo postmortem failure mode is now guarded

Problem:

- The GitLab demo postmortem agent first tried non-existent per-ticket notes and
  attachment endpoints.
- It then tried to read scanner artifacts outside its assigned work directory.
- The runner correctly failed the task when the agent exited without creating a
  postmortem row.
- Later retries showed a second local-model failure mode: even compact raw JSON
  can lead the model to chase persisted tool-output files instead of persisting
  the postmortem.

Resolution:

- Added `GET /api/postmortems/evidence/{ticket_id}` and reduced the default
  payload to an agent-safe summary.
- Added `POST /api/postmortems/synthesize/{ticket_id}` as the deterministic
  supervisor fallback for stalled/failed model postmortems.
- Postmortem `21` was created with status `ready_for_review` for ticket `83`.
- Postmortem `22` was created with status `ready_for_review` for ticket `88`
  after the real CI/CD flow completed and local-model postmortem attempts
  stalled.
- Ticket `83` evidence endpoint was verified with `6` notes, `2` attachments,
  `2` changes, `2` agent tasks, `2` CI/CD runs, `1` postmortem, and `28` audit
  entries.
- Ticket `88` completed the real CI/CD flow with final run `14` passed,
  changes `43` and `44` completed, ticket status `resolved`, postmortem `22`
  ready for review, and zero active agent processes.

### Fresh one-line installs exposed agent workdir ownership drift

Problem:

- The API container creates `agent_work/<agent_id>` on a bind mount.
- On a fresh side-by-side install, those workdirs can be owned by root on the
  host.
- `agentic_cicd_full_demo.py` then failed before it could seed the demo app for
  the local-model agent: `PermissionError: [Errno 13] Permission denied:
  '.../agent_work/<id>/demo-app'`.
- The previous repair code used a fixed container name, which does not work for
  one-line installs that use custom Compose project names.

Resolution:

- `agentic_cicd_full_demo.py` now repairs workdir ownership with
  `docker compose exec -T api` from the installed root rather than using a fixed
  container name.
- The runner writes a probe file before continuing, and fails clearly if the
  workdir is still not host-writable.
- Verified on fresh install
  `/home/cereal/SOC_TESTING/soc-dashboard-install-e2e-20260512` with real
  local-model ticket `13`; remediation agent `7` completed and produced the MR
  patch artifact.

### Postmortem fallback must stop stale model processes after synthesis

Problem:

- The compact postmortem evidence API is bounded, but slower local models can
  still stall or fail while producing the structured POST body.
- The supervisor can synthesize a `ready_for_review` postmortem, but the model
  process may still be alive if synthesis happens due to timeout rather than
  process exit.

Resolution:

- The full CI/CD demo runner now stops the postmortem agent after supervisor
  synthesis.
- The agent runner itself now attempts deterministic postmortem synthesis when
  a postmortem task exits without creating the required artifact.
- Verified on fresh install ticket `13`: postmortem `4` was
  `ready_for_review`, the stale postmortem process was stopped, and
  `/api/agents/processes` returned no active processes.

### One-line installer script mode can be lost during transfer

Problem:

- `./install.sh` failed with `Permission denied` in a fresh installer E2E run
  because the executable bit was not preserved.

Resolution:

- The repository index now marks `install.sh` executable.
- If a copied working tree still loses the bit, repair the source tree with:

```bash
chmod +x /home/cereal/SOC_TESTING/soc-dashboard/install.sh
```

### Ticket sorting/filtering failed when status filters were used

Problem:

- The ticket list API built `WHERE status = ...` and `WHERE priority = ...`
  clauses without table aliases.
- Once the tickets query joined `agents`, PostgreSQL treated `status` as
  ambiguous, causing HTTP 500 for filtered ticket lists.
- Restarting the API container alone did not load host-side route edits because
  the API code is baked into the image.

Fix:

- Ticket filters now qualify columns as `t.status`, `t.priority`,
  `t.assignee`, and `t.agent_id`.
- The count query now aliases `tickets t` to match the shared filter clause.
- Rebuild the API container with `docker compose up -d --build api` after API
  Python changes.

Verified:

- `GET /api/tickets?status=in_progress&sort_by=title&sort_dir=asc&limit=3`
  returns HTTP `200`.
- `platform_doctor.py` validates ascending and descending ticket sort order.

### SOC bridge daemon fails when launched from its package directory

Status: fixed during the 2026-05-12 real agentic bridge acceptance pass.

Problem:

- The documented SOC bridge health check was run from
  `/home/cereal/SOC_TESTING/soc_bridge` with:

```bash
python3 daemon.py --config production_config.json --check
```

- It failed before checking iTop/Mailcow with:

```text
ModuleNotFoundError: No module named 'soc_bridge'
```

Impact:

- This blocks reliable verification of the iTop-Mailcow notification bridge
  from the documented quick-operation command.
- It does not currently block the SIEM-ticket bridge; Wazuh-to-iTop bridge
  status and connection checks passed with `siem_connected=true` and
  `ticketing_connected=true`.

Next action:

- Completed.

Fix:

- Updated `/home/cereal/SOC_TESTING/soc_bridge/daemon.py` and `cli.py` so direct
  script execution adds the package parent directory to `sys.path` before
  importing `soc_bridge.*`.
- Kept module-style execution working; the change only applies when
  `__package__` is empty.

Verified:

- `python3 -m py_compile daemon.py cli.py`: PASS
- `python3 daemon.py --config production_config.json --check`: PASS,
  iTop and Mailcow both connected.
- `python3 cli.py --config production_config.json status`: PASS, iTop and
  Mailcow both connected.
- `python3 daemon.py --config production_config.json --poll-once`: PASS,
  completed a poll and delivered notifications.

### SOC bridge poll-once can catch up old tickets as new notifications

Status: fixed during the 2026-05-12 real agentic bridge acceptance pass.

Problem:

- After the direct-invocation import fix, the first successful
  `python3 daemon.py --config production_config.json --poll-once` loaded only
  one tracked ticket from state and then sent `created` notifications for 28
  existing iTop tickets.

Impact:

- This proves the Mailcow notification path works, but it also shows that a
  repaired/restarted bridge with stale or empty state can notify old tickets as
  if they were newly created.
- For customer demos and first production use, this can look noisy or
  unprofessional if baseline state is not initialized deliberately.

Next action:

- Completed.

Fix:

- Added `TicketNotificationEngine.baseline_state()` to record current watched
  tickets without sending notifications.
- Added daemon flag:

```bash
python3 daemon.py --config production_config.json --baseline-state
```

- Added CLI flag:

```bash
python3 cli.py --config production_config.json poll --baseline
```

Verified:

- With an empty temporary state file,
  `python3 daemon.py --config production_config.json --state-file "$TMP_STATE" --baseline-state`
  tracked 28 tickets and sent 0 notifications.
- A subsequent
  `python3 daemon.py --config production_config.json --state-file "$TMP_STATE" --poll-once`
  fetched 28 tickets, found 0 changes, and sent 0 notifications.
- `python3 cli.py --config production_config.json poll --baseline` completed
  successfully and sent 0 notifications.

### Incoming tickets can now auto-assign agents by RACI policy

Status: fixed during the 2026-05-12 real agentic bridge acceptance pass.

Problem:

- Bridge-created or provider-synced tickets currently require manual agent
  assignment from the dashboard or an explicit `/assign-agent` API call.
- A production control plane needs configurable assignment policy: some RACI
  groups, intents, severities, providers, or ticket classes should immediately
  spawn an agent, while other tickets should stay in a manual queue.

Impact:

- Real bridge flows can create and sync tickets but do not yet prove the
  intended hands-free path from incoming event to agent work.
- This weakens the customer pitch because the system appears to need an
  operator click at the exact point where automation should begin.

Fix:

- Added RACI rule fields `auto_assign_agent`, `auto_agent_model`, and
  `auto_agent_prompt`.
- Seeded the phishing RACI rule so Security Operations phishing incidents
  auto-spawn a ticket agent.
- Wired policy evaluation into direct ticket creation, service-desk intake after
  classification notes/approval gates are written, and iTop sync for newly
  discovered provider tickets.
- Kept manual routing as the default for rules where `auto_assign_agent=false`.

Verified:

- `python -m py_compile api/services/auto_assignment.py api/services/ticket_service.py api/services/itop_sync.py api/routes/intake.py api/routes/tickets.py`: PASS.
- `python -m unittest tests.test_auto_assignment tests.test_provider_registry tests.test_itop_outbound`: PASS.
- `python scripts/smoke_auto_assignment_policy.py`: PASS.

## Current Limitations

### Change completion can silently drop agent evidence

Status: fixed and deployed live on 2026-05-12.

Problem:

- During ticket `312`, agent `85` completed changes `83`, `84`, and `85` with
  request bodies containing `evidence`.
- The live `/api/changes/{id}/complete` route only reads `result`, so it marked
  each gate `completed` while storing a blank `change_requests.result`.
- The route also attributed those completions to `dashboard` because it ignored
  the submitted `agent_id`.

Impact:

- Change gates can look completed in the UI/API while losing the evidence needed
  for audit, demo explanation, and postmortem learning.

Fix:

- Accept `result`, `evidence`, or `output` as completion evidence and store the
  selected value in `change_requests.result`.
- Reject blank completion evidence instead of recording an empty result.
- Attribute completion to `completed_by`, `actor`, or `agent_<agent_id>` before
  falling back to `dashboard`.

Verification:

- Added unittest coverage for `evidence` alias handling and blank evidence
  rejection in `tests/test_change_approval_resume.py`.
- Live API rejected blank evidence for change completion.
- Live ticket `312` result rows for changes `83`, `84`, and `85` were repaired
  through the hardened API route using the evidence agent `85` already posted.

### iTop incident resolution requires lifecycle transition before resolve

Status: fixed and deployed live on 2026-05-12.

Problem:

- Ticket `312` was resolved by agent `85` in the dashboard, but iTop Incident
  `199` / `I-000208` remained in state `new`.
- A direct iTop `ev_resolve` stimulus failed with
  `Invalid stimulus: 'ev_resolve' on the object I-000208 in state 'new'`.
- The next iTop sync then pulled the provider's `new` status back into the
  dashboard, hiding the completed agent work from the ticket list.

Impact:

- Agent-completed work can be locally complete but provider-visible tickets
  stay open, which breaks demos and weakens the provider-sync audit trail.

Fix:

- Provider close now retries iTop resolution through the normal lifecycle:
  `ev_assign` first when direct `ev_resolve` is invalid, then `ev_resolve`.

Verification:

- Live repair succeeded for ticket `312`: iTop accepted `ev_assign`, then
  accepted `ev_resolve`, and the subsequent sync returned the dashboard ticket
  to `resolved`.
- API image was rebuilt with the iTop lifecycle fallback and passed health,
  compile, and focused remote unittest checks.

### Approval resume can fan out duplicate agents for one ticket

Status: fixed and deployed live on 2026-05-12.

Problem:

- Approving three pending lab-no-op changes for ticket `312` caused the
  approval resume handler to spawn continuation agents `86`, `87`, and queued
  `88` while agent `85` was already actively working the same ticket.
- The agent auditor correctly wrote `ticket_already_has_active_agent` audit
  events, but it only audited and did not prevent or consolidate the duplicate
  runners.
- Root cause: `_resume_agent_after_approval` checked active tasks only for the
  original change agent, not for active agents on the ticket as a whole.

Impact:

- Approval gates can create overlapping agents for the same ticket, causing
  duplicated notes, duplicated remediation actions, noisy demo evidence, and
  possible cross-agent confusion.

Fix:

- Make approval resume ticket-scoped: if any spawned/running/working agent or
  queued/running task exists for the ticket, return that active agent instead
  of spawning another continuation.
- Keep the auditor signal, but make the approval path prevent duplicates before
  the auditor has to notice them.

Verification:

- Added `tests/test_change_approval_resume.py` coverage proving
  `_resume_agent_after_approval` returns `already_active_ticket` when another
  agent/task is active on the same ticket.
- Live regression created approval change `86` on ticket `317`; approving it
  returned `resume.status=already_active_ticket` and did not create another
  agent.
- `/api/agents/active` was clean after removing the regression fixtures.

### Stopped queued agent can still start when semaphore opens

Status: fixed and deployed live on 2026-05-12.

Problem:

- Agent `88` was stopped while its task was still queued.
- When a semaphore slot opened, task `86` still started a Claude runner process
  after the stop request had already set the agent status/error.

Impact:

- Dashboard stop is not definitive for queued tasks. A queued duplicate or
  cancelled task can still become a real process later, which undermines agent
  supervision and demo reliability.

Fix:

- Before `_spawn_with_semaphore` launches a process, reload task and agent state
  and exit without spawning if either is `stopped`, `terminated`, `failed`, or
  otherwise no longer queued/runnable.
- Ensure `stop_agent_task` marks queued tasks as stopped in a way the semaphore
  worker honors before process launch.

Verification:

- Added `tests/test_agent_lifecycle_guards.py` coverage proving stopped queued
  tasks are skipped before `_run_agent` is called.
- Live process diagnostics after deployment showed no active Claude runner
  processes.

### Stopping a duplicate agent can leave ticket assigned to the stopped agent

Status: fixed and deployed live on 2026-05-12.

Problem:

- Duplicate agent `88` was stopped, but `tickets.agent_id` still pointed to
  `88` while the only real active worker was agent `85`.
- iTop/dashboard sync context then reported the wrong canonical agent for the
  ticket, which can confuse agents, operators, and audit demos.

Impact:

- The dashboard can show or pass stale ownership after duplicate cleanup,
  especially when a later duplicate spawn overwrites `tickets.agent_id`.

Fix:

- When stopping an agent, if that agent is the ticket's current `agent_id`,
  reassign the ticket to another active agent for the same ticket, or clear the
  assignment if none exists.
- Record the reassignment/clear in audit/event history.

Verification:

- Added `tests/test_agent_lifecycle_guards.py` coverage for ticket reassignment
  after stopping a duplicate agent.
- Live regression stopped duplicate queued agent `92` on ticket `318`; the
  ticket owner was restored to active agent `91`, then both regression fixtures
  were cleaned up.

### SOC Bridge phishing ticket creation is failing before dashboard sync

Status: fixed during the 2026-05-12 real bridge phishing agent flow.

Problem:

- `/tmp/bridge_phish_agent_flow.py` failed in `run_bridge_report`.
- SOC Bridge returned `ticket_creation.success=false` with
  `No ticket key in API response`.
- Root cause identified: phishing reports with `message_id` were mapped to
  iTop `Incident.externalid`, but the live iTop schema has no `externalid`
  attribute on `Incident`. iTop returned `code=100` with
  `Unknown attribute externalid from class Incident`; the bridge did not surface
  that response message.

Impact:

- The full Report Phish -> SOC Bridge -> iTop -> dashboard -> agent flow cannot
  start because the iTop ticket is not created.

Fix:

- Inspect SOC Bridge production config and iTop create response handling.
- Verify the configured security team/org/caller fields still match the live
  iTop instance.
- Fix the bridge connector or config, rerun the bridge phishing harness, then
  continue to agent/approval/postmortem validation.

Verification:

- Acceptance log `bridge-phish-agent-20260512-125257.log` shows SOC Bridge
  successfully created iTop Incident `198`.
- Acceptance log `bridge-phish-agent-20260512-130312.log` shows SOC Bridge
  successfully created iTop Incident `199` and sent the Mailcow notification.

### Dashboard iTop sync is not discovering the bridge-created phishing ticket

Status: fixed during the 2026-05-12 real bridge phishing agent flow.

Problem:

- SOC Bridge successfully created iTop Incident `198` titled
  `Phishing Report: Bridge Agentic Phish 1778611977`.
- The real bridge harness remained in the dashboard sync/find loop; dashboard
  `/api/tickets` did not show the new bridge ticket after `/api/tickets/sync-all`.

Impact:

- The Report Phish -> SOC Bridge -> iTop leg now works, but the full iTop ->
  dashboard -> agent auto-work leg is still blocked.

Fix:

- Inspect `/api/tickets/sync-all` behavior, iTop sync logs, and sync-state key
  tracking for newly created Incident keys above the current dashboard range.

Verification:

- Sparse iTop key listing now uses `SELECT <Class>` instead of assuming
  contiguous numeric IDs.
- Full sync imports historical rows passively while live discovery can still
  auto-assign genuinely new tickets.
- Ticket `312` synced from iTop Incident `199` and now has
  `provider_sync_status=synced`.

### Bulk iTop catch-up sync can auto-assign historical phishing tickets

Status: fixed and deployed live on 2026-05-12.

Problem:

- After switching discovery away from contiguous ID scanning, a full catch-up
  sync imported historical iTop phishing tickets and auto-started agents for
  old SOC Bridge smoke tickets (`agent_id` 78 and 79).

Impact:

- This is not the same broad matcher bug; the tickets are genuine phishing
  tickets, but they are historical catch-up rows and should not spawn live
  agents during repair, bootstrap, or bulk import.

Fix:

- Split sync behavior so live discovery and explicit single-ticket sync can
  auto-assign, while `full_sync`/bootstrap catch-up imports remain passive.

Verification:

- Added `tests/test_itop_outbound.py` coverage proving `full_sync()` calls
  `sync_ticket(..., auto_assign=False)` for historical/provider catch-up rows.
- Remote unittest suite passed after deployment.

### Auto-assigned bridge phishing agent stalls on broad default ticket prompt

Status: fixed and deployed live on 2026-05-12 for future auto-assigned
phishing tickets.

Problem:

- Live bridge run created iTop Incident `199`, dashboard ticket `312`, and
  auto-assigned agent `81`.
- Agent `81` remained alive with heartbeats for 10+ minutes at `45%` progress
  after reading full ticket context/workflow evidence, but it had not created
  triage notes or remediation approval gates.
- The active prompt is the broad default ticket-resolution prompt plus a short
  phishing instruction, not the tighter bridge phishing acceptance workflow.

Impact:

- The bridge, iTop sync, and auto-assignment chain works, but the intended
  hands-free agentic phishing flow is not yet completing reliably with the
  default auto-assignment prompt.

Fix:

- Tighten the phishing RACI `auto_agent_prompt`/prompt builder so auto-assigned
  phishing agents use bounded postmortem/ticket evidence and concrete required
  actions instead of broad context exploration.

Verification:

- Added `AUTO_ASSIGNMENT_PROMPT`, and `maybe_auto_assign()` now uses
  `build_auto_assignment_prompt()` instead of the broad default ticket prompt.
- Added migration `010_tighten_phishing_auto_agent_prompt.sql` and updated
  `init_db.sql` so fresh installs and existing deployments get the compact
  phishing instruction.
- Live database check confirmed the phishing RACI prompt begins with
  `Auto-work Security Operations phishing tickets end to end using compact evidence first`.

### Agent task can fail after useful work with output chunk separator error

Status: mitigated and deployed live on 2026-05-12.

Problem:

- Agent `81` wrote a meaningful phishing triage note for ticket `312`.
- The task then failed with
  `Separator is found, but chunk is longer than limit`.

Impact:

- The model can perform useful ticket work, but the runner/task-output handling
  can mark the task failed before approval gates and final notes are complete.
- This makes real-flow validation brittle even when the agent is taking correct
  actions.

Mitigation:

- Inspect agent runner stream/chunk handling for long tool output or persisted
  tool-result references, then bound or summarize oversized chunks before task
  persistence.

Verification:

- Ticket API and postmortem evidence responses now call
  `compact_ticket_payload()` so agents see provider payload summaries instead of
  the full iTop payload by default.
- The auto-assignment prompt instructs agents to use
  `/api/postmortems/evidence/{ticket_id}?task_log_lines=0` first and avoid full
  ticket context unless a specific fact is missing.
- The original ticket `312` was completed by the follow-up bounded flow; changes
  `83`, `84`, and `85` all have persisted completion evidence.

### RACI auto-assignment matched generic Incident tickets too broadly

Status: fixed during the 2026-05-12 full acceptance baseline.

Problem:

- A provider-adapter smoke ticket titled `Provider adapter smoke` received an
  active agent even though it did not contain phishing keywords and was not
  routed to Security Operations.
- Root cause: the auto-assignment scorer gave enough points for matching
  `ticket_class=Incident` alone, so the phishing RACI rule could match generic
  Incident tickets.

Impact:

- Agents can be assigned to tickets that should remain in a manual or unrelated
  queue.
- This matches the observed concern that agents may spill into tickets that
  already have a different purpose.

Fix:

- Auto-assignment now requires a strong signal such as assignment group or
  keyword match before an
  auto-assignment rule can fire.
- Ticket class is now a ranking boost only after a real intent/group signal is
  present.
- Added a unit/smoke case proving generic Incident tickets stay manual while
  phishing/Security Operations incidents auto-assign.

Verified:

- Local `python -m unittest tests.test_auto_assignment`: PASS.
- Local `python scripts/smoke_auto_assignment_policy.py`: PASS.
- Live rebuilt API `_score_rule` returned `{'class_only_score': 0}` for
  `Provider adapter smoke`.
- Live provider-adapter smoke created ticket `174` with no active agent spawned.

### Tool health inventory still has unprobeable deployed/reference modules

Status: active, found during the 2026-05-12 full acceptance baseline.

Problem:

- `POST /api/tools/check-all` reports `unknown` for Suricata IDS, SOC Bridge,
  SIEM-Ticket Bridge, and TheHive.
- The returned error is `No port configured for health check`.

Impact:

- The Tools page is not yet a clean demo surface for every deployed or reference
  integration.
- Operators can see Wazuh Dashboard, iTop, Mailcow, GitLab, SearXNG, Agent
  Memory, and other HTTP/port-backed tools as healthy, but bridge/daemon-style
  modules do not yet expose a dashboard health contract.

Next action:

- Add provider-aware health checks for daemon/file/container-backed tools, or
  mark optional/reference modules inactive when they are not part of the current
  setup profile.
- Reconcile the Tools page from the setup manifest so unused modules are hidden
  or explicitly labeled optional/not configured.

### Fresh Sysmon exact-marker alert intermittently misses Wazuh Indexer

Status: fixed in the reference lab profile during the 2026-05-12 EDR/Sysmon live rerun.

Problem:

- The EDR/Sysmon E2E test passed 15/16 after the neutral iTop harness fix.
- The remaining failure is `Fresh Sysmon exact-marker alert flow`: the test
  generated a harmless `CODEX_SYSMON_*` marker but did not find a matching
  Wazuh Indexer alert within the 90-second wait window.
- This is the same symptom as the earlier queue/logcollector delay, so the next
  diagnostic step is to trace the marker through Sysmon hot log, Wazuh
  logcollector, manager alerts, and Indexer ingestion before changing rules.

Impact:

- The provider health-check ticket no longer causes accidental RACI
  auto-assignment, but the real endpoint telemetry proof is not yet reliable
  enough for a clean demo.

Diagnostic path used:

- Capture the exact marker from the rerun, confirm whether it reached
  `/var/log/sysmon/sysmon.log`, inspect Wazuh manager/logcollector warnings, and
  rerun after correcting the ingestion path.

Update:

- Rerun marker `CODEX_SYSMON_E2E_1778632057` was present in
  `/var/log/sysmon/sysmon.log` as both the logger line and Sysmon file-create
  XML.
- No matching Wazuh archive/alert hits were found.
- `wazuh-manager` reported inactive and localhost Indexer connection refused
  during the trace, so the immediate blocker is Wazuh service availability, not
  Sysmon marker generation.
- Container inspection corrected the service read: Wazuh is Dockerized and the
  manager container is running. The manager sees `/var/log/sysmon/sysmon.log`,
  but `wazuh-analysisd` logged `Input queue is full`, and no marker was found in
  manager archives/alerts. The active blocker is noisy Sysmon ingestion
  overwhelming Wazuh analysis, so the reference Sysmon config needs to be
  tightened for the E2E marker path before rerun.

Fix:

- Removed broad `/bin/bash -c`, `/bin/sh -c`, `.sh`, and `.py` selectors from
  the lab Sysmon profile.
- Added an explicit match-nothing `ProcessTerminate` include rule because
  SysmonForLinux was otherwise emitting EventID 5 process-termination noise and
  filling the Wazuh analysis queue.
- Rotated the hot Sysmon log and restarted Sysmon plus Wazuh manager internals.

Verified:

- Hot Sysmon log stayed quiet after restart.
- EDR/Sysmon E2E rerun passed `16/16`.
- Exact marker `CODEX_SYSMON_E2E_1778632686` produced 2 Wazuh alerts.
- SIEM bridge remained healthy with `error_count=0` and processed the marker
  during the next poll.

### Agent Bash path validation rejects multiline inline Python

Status: active, found during real agent work on ticket `354` / agent `123`.

Problem:

- The agent correctly moved from compact evidence to deeper Wazuh context, but
  generated a multiline `python3 -c` shell snippet containing a `#` comment
  inside a quoted argument.
- The harness rejected it with `Newline followed by # inside a quoted argument
  can hide arguments from path validation`.

Impact:

- This is a good safety rejection, but local agents may waste cycles or stall if
  their prompts do not steer them toward simpler command shapes.

Fix:

- Add a harness instruction telling agents to avoid multiline inline
  `python -c`/shell comments and to use simple `curl` calls or write temporary
  scripts/files when parsing JSON is required.

Verified:

- Local `python -m py_compile api/services/task_prompts.py` passed.
- Current agent recovered from the rejected command by trying a simpler approach.
- Live API rebuild is deferred until active agent `123` completes, to avoid
  disrupting the running EDR/SIEM proof.

### Provider sync can overwrite local in-progress agent state

Status: fixed in source, live API rebuild deferred until agent `123` completes.

Problem:

- The compact evidence showed ticket `354` as `in_progress` immediately after
  auto-assignment.
- Later dashboard ticket detail showed `status: new` while agent `123` was still
  working because iTop sync mirrored the provider-side status back over the
  dashboard's local working state.

Impact:

- Operators may see an actively worked ticket as `new`, which makes the demo and
  audit story confusing.
- This can also make agent completion/closure verification harder because local
  and provider states are not clearly separated.

Fix:

- Preserve or derive an active local workflow state while an agent is assigned,
  and push/pull provider status transitions explicitly rather than letting
  provider sync hide active dashboard work.
- Existing iTop sync now derives an effective local status: active-agent tickets
  keep `in_progress`, `awaiting_user_response`, or `pending_approval` unless the
  provider reports a terminal status such as `resolved` or `closed`.

Verified:

- Local `python -m unittest tests.test_itop_sync_status tests.test_auto_assignment tests.test_itop_outbound`: PASS.
- Source synced to the remote tree; container rebuild waits for the active EDR
  proof agent to finish.

### iTop outbound creation needs environment-specific defaults

Incident/UserRequest creation requires iTop org/caller defaults. This is intentional. Configure:

- `ITOP_DEFAULT_ORG_ID`
- `ITOP_DEFAULT_CALLER_ID`

Until configured, outbound iTop create records `create_failed`.

### Notes are canonical-first

Agents write notes to dashboard canonical notes. Provider-side comment sync is not fully implemented yet. This is the next important provider-adapter expansion.

### Binary attachments are metadata-only

`ticket_attachments` stores filename/content-type/hash/storage reference/metadata. Actual binary upload/storage is not implemented yet.

### Access control is not production-ready

The dashboard does not yet enforce Keycloak/OIDC login or role-based approval. Current approval fields are ready for authenticated identities, but auth middleware is still future work.

### Workflow activation is manual/review-state only

Workflows can be drafted, tested, reviewed, and run records can be created. Automatic trigger routing from incoming tickets to approved workflows is not complete yet.

### ServiceNow/Jira providers are not implemented yet

The adapter boundary exists; concrete adapters still need to be written and tested.

### iTop sync scans by numeric key

The current iTop discovery strategy scans numeric keys. It works for the lab but a production provider should prefer provider-native updated-since queries where available.

### No database rollback system

Migrations are additive/idempotent. There is no first-class rollback tool yet.
