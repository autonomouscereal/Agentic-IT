# Known Issues And Fix Log

Last updated: 2026-05-12.

## Fixed In Current Pass

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
- The agent auditor is the supervision path and defaults to `AGENT_AUDITOR_AUTO_RECOVER=false` so recovery is auditable before being made automatic.
- Existing deployments can run `python3 scripts/repair_agent_supervision_env.py --env-file .env`, then recreate the API container.

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

## Current Limitations

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
