# Known Issues And Fix Log

Last updated: 2026-05-11.

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
