---
name: soc-dashboard
description: >
  SOC Dashboard / autonomous enterprise operations control plane - FastAPI + PostgreSQL + vanilla JS
  platform for the AI Server (192.168.50.222). The current SOC dashboard is the seed proof
  for a broader one-line installed agentic enterprise operations layer that can route IT,
  SOC, DevOps, service desk, IAM, cloud, network, compliance, maintenance, and self-repair
  work to governed agents.
allowed-tools:
  - Read
  - Bash(python *)
  - Bash(docker *)
  - Bash(find *)
---

# SOC Dashboard / Enterprise Operations Control Plane

Unified SOC/IT proof deployment for the autonomous enterprise operations control
plane on the AI Server. Mirrors iTop tickets, orchestrates AI agents, manages
approvals and access requests, monitors tool health, and provides real-time
updates. The current SOC scope is the seed; the platform goal is a governed
agentic layer that can eventually operate or replace broad enterprise IT,
security, DevOps, service desk, IAM, cloud, network, compliance, maintenance,
and internal tooling work.

## Project Mental Model

This is the control plane for a provider-agnostic autonomous enterprise
operations platform, not merely a monitoring dashboard. The dashboard owns
canonical operational state: tickets, alerts, requests, notes, attachments,
agent tasks, prompts, checkpoints, logs, model selection, change approvals,
access requests, scoped credential leases, workflows, postmortems, skills,
knowledge articles, tool health, setup plans, and audit/event history.

The north star is a one-line installed, local/private, governed agentic
operations layer that can replace or radically reduce human labor across
enterprise IT, SOC/security, DevOps, service desk, IAM, infrastructure, network,
cloud, compliance, maintenance, and internal tooling. SOC is the first proof
domain because it exercises tickets, alerts, logs, identity, approvals,
remediation, evidence, and postmortems.

All concrete products are replaceable providers or reference modules. iTop, Wazuh, Zeek, Suricata, Mailcow, Keycloak, GitLab, SearXNG, and the AI proxy are the current lab/reference stack on `192.168.50.222`; ServiceNow, Jira, Splunk, Sentinel, Defender, CrowdStrike, Exchange, Gmail, Proofpoint, Okta, GitHub, Azure DevOps, Jenkins, and similar tools should be integrated through provider adapters without changing the canonical dashboard contract.

Claude Code is the first working harness, not the permanent architecture boundary. Keep harness-specific command building isolated in `api/services/agent_harness.py` and preserve the dashboard task/checkpoint/API contract for future harnesses.

Default ticket agents should complete assigned work quickly and safely. They should not create reusable workflows unless explicitly asked. Postmortems and workflow-builds are separate learning tasks that convert completed work into reviewed knowledge, skills, tests, guardrails, and draft workflows.

## Workflow / Postmortem Reuse Rules

Workflows are reusable operational procedures. `workflow_key` is the reuse
identity; `name` is only a display label.

Agents performing postmortems or workflow-building must:

1. Call `GET /api/workflows?limit=100` before creating a workflow.
2. Read likely matches with `GET /api/workflows/{id}`.
3. Compare by ticket class, workflow key, description, blueprint, trigger type,
   approval policy, test plan, and run history.
4. Update a substantially similar workflow with `PUT /api/workflows/{id}`
   instead of creating a near-duplicate.
5. Create a new workflow only when the operational behavior is genuinely
   different, not because the ticket title, marker, or postmortem id differs.
6. Keep new or changed workflows in `draft`, `ready_for_review`, or `tested`
   until a human/operator approval calls `POST /api/workflows/{id}/review`.
7. Use `superseded` for obsolete duplicates only after explicit operator
   consolidation approval.
8. Include workflow key/action evidence in postmortem promotion notes and audit
   trails so operators can prove whether an asset was created or updated.

## Approval Timing And Wait Recovery

Approval gates may be approved while a local model is already generating. Use
`agent_model_turn_started` / `agent_model_turn_finished` audit and event rows
to explain whether stale "waiting" text came from a model turn that began before
the approval landed.

When approval lands for an already-running task, `/api/changes/{id}/approve`
delivers a non-interrupting dashboard steering update into the agent workspace.
If the agent still writes a stale durable wait checkpoint after the gate is
approved/completed, the runner either keeps the active task running with a
correction or queues a continuation agent after the owned harness is stopped.
True waits must use `awaiting_access`, `pending_approval`,
`awaiting_user_response`, or `blocked` instead of generic `working`.

## Wazuh Lease-Gated Provider Access

Wazuh/SIEM reads must be performed through dashboard-gated endpoints after an
agent has a scoped lease. Agents request
`{"system":"wazuh","resource_type":"api","resource_id":"wazuh.manager","action":"read"}`
through `/api/agents/{agent_id}/vault/lease`; if denied, create an access
request. Access requests should include `lease_request`, but the dashboard also
infers leases for known resources such as `wazuh.manager API` and records
`lease_request_inferred` evidence.

After approval/completion, use:

- `GET /api/agents/{agent_id}/wazuh/manager/status`
- `GET /api/agents/{agent_id}/wazuh/rules/{rule_id}`
- `GET /api/agents/{agent_id}/wazuh/alerts/search?rule_id=...&source_ip=...`

These routes validate `agent_vault_leases`, return no secret values, and write
provider-access audit events.

Additional reconstructed context for future Codex sessions lives at:

- `C:/Users/cereal/Documents/Codex/2026-05-12/you-don-t-seem-to-properly/AGENTS.md`
- `C:/Users/cereal/Documents/Codex/2026-05-12/you-don-t-seem-to-properly/docs/AGENTIC_IT_REPLACEMENT_CONTEXT.md`
- `C:/Users/cereal/Documents/Codex/2026-05-12/you-don-t-seem-to-properly/docs/REFERENCE_MAP.md`
- `C:/Users/cereal/Documents/Codex/2026-05-12/you-don-t-seem-to-properly/docs/REMOTE_INVENTORY_2026-05-12.md`

## Quick Access

| Service | URL | Port |
|---------|-----|------|
| Dashboard UI | http://192.168.50.222:25480 | 25480 |
| API (programmatic) | http://192.168.50.222:25480/api | 25480 |
| Health endpoint | http://192.168.50.222:25480/health | 25480 |
| PostgreSQL DB | 192.168.50.222:5433 | 5433 |

## Docker Containers

| Container | Image | Internal Port | Status |
|-----------|-------|---------------|--------|
| `soc-dashboard-api` | built from `./api/Dockerfile` (Python 3.11-slim + FastAPI) | 8000 | Running |
| `soc-dashboard-db` | `postgres:16-alpine` | 5432 | Running (healthy) |

Both containers use `restart: unless-stopped`. The API waits for `db` to be healthy before starting.

## Project Location

- **Compose file**: `/home/cereal/SOC_TESTING/soc-dashboard/docker-compose.yml`
- **Environment**: `/home/cereal/SOC_TESTING/soc-dashboard/.env` (contains DB credentials, iTop credentials, intervals)
- **Source code**: inside `soc-dashboard-api` container at `/app/`
- **Frontend**: mounted read-only from `./frontend/` to `/frontend/` in container
- **Data volume**: `db-data` named volume for PostgreSQL persistence
- **Sync state**: `/app/data/.itop_max_keys.json` (inside container, tracks last-known iTop keys per class)

## Python Dependencies

```
fastapi==0.115.0
uvicorn[standard]==0.32.0
asyncpg==0.30.0
jinja2==3.1.4
python-multipart==0.0.18
uvloop==0.21.0
aiohttp==3.10.0
```

## API Endpoints (Verified from Source)

### Tickets — `/api/tickets`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/tickets` | List all tickets with filters: `status`, `priority`, `assignee`, `agent_only`, `limit`, `offset` |
| GET | `/api/tickets/{id}` | Ticket detail with agent info + change requests |
| POST | `/api/tickets/{id}/sync` | Force sync single ticket from iTop |
| POST | `/api/tickets/sync-all` | Force full sync of all tickets from iTop |
| POST | `/api/tickets/{id}/assign-agent` | Spawn AI agent for ticket (body: `model` string, default `qwen/qwen3.6-27b`) |
| POST | `/api/tickets/{id}/unassign-agent` | Remove agent from ticket (sets agent status to 'terminated') |

### Agents — `/api/agents`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/agents` | List all agents with filters: `status`, `ticket_id` |
| GET | `/api/agents/active` | List only active agents (spawned/running/working) |
| GET | `/api/agents/stats` | Agent statistics (total/active/finished/failed/avg duration) |
| GET | `/api/agents/{id}` | Agent detail with change requests + audit trail |
| POST | `/api/agents/spawn` | Spawn new agent (body: `ticket_id`, `model`) |
| POST | `/api/agents/heartbeat/{id}` | Agent heartbeat endpoint (called by agents) |
| POST | `/api/agents/{id}/wake` | Reset heartbeat, set status to 'running' (rejects stopped/finished/failed/terminated) |
| POST | `/api/agents/{id}/restart` | Terminate current agent, spawn new one for same ticket with same model |
| POST | `/api/agents/{id}/stop` | Stop agent with reason |
| POST | `/api/agents/{id}/update` | Update agent status + error message (body: `status`, `error_message`) |
| GET | `/api/agents/ws` | WebSocket endpoint for real-time agent events |

### Changes — `/api/changes`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/changes` | List all changes with filters: `status`, `agent_id`, `ticket_id` |
| GET | `/api/changes/pending` | Pending changes only with waiting_seconds and expiry check |
| GET | `/api/changes/stats` | Change statistics (pending/approved/rejected/completed counts) |
| GET | `/api/changes/{id}` | Single change request detail |
| POST | `/api/changes/request` | Submit new change request (body: `agent_id`, `ticket_id`, `action`, `target`, `reason`) |
| POST | `/api/changes/{id}/approve` | Approve change (body: `approved_by`) |
| POST | `/api/changes/{id}/reject` | Reject change (body: `rejected_by`, `reason`) |
| POST | `/api/changes/{id}/complete` | Mark change as completed (body: `result`) |

### Dashboard — `/api/dashboard`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/dashboard/stats` | Overview stats: tickets, agents, changes, tools, recent activity, trends |
| GET | `/api/dashboard/ops-metrics` | Operational metrics: agent working time, ticket SLA, postmortem SLA, approval gates, workflow runs, CI/CD runs, auto-assignment, and tool health |
| GET | `/api/dashboard/audit` | Audit log with filters: `actor`, `action`, `limit` |
| GET | `/api/dashboard/ticket-chart` | Ticket chart data for last N days (default 30), grouped by date and status |
| GET | `/api/dashboard/agent-performance` | Last 50 finished agents with duration |
| GET | `/api/dashboard/tool-uptime` | Tool uptime percentages for last N days (default 7) |

### Access Control - `/api/access`

The 2026-05-14 access-control layer supports audit-only and enforcement modes.
It uses role capabilities, ticket group/classification scopes, spawn-time agent
permission snapshots, and per-agent vault leases.

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/access/policies` | Shows auth mode, enforcement mode, route permission requirements, role capability map, classification order, and agent permission/vault boundary text |
| GET | `/api/access/users/{id}/scopes` | Lists user group/classification/provider scopes |
| POST | `/api/access/users/{id}/scopes` | Upserts user scopes and optional per-system vault lease metadata |

Current behavior:

- `DASHBOARD_AUTH_MODE=disabled`: local lab default, equivalent to
  platform-admin.
- `DASHBOARD_AUTH_MODE=header` plus `DASHBOARD_AUTH_ENFORCEMENT=enforce`:
  trusted auth proxy/header identities are checked and denied with HTTP 403.
- Ticket list/detail/note/assignment paths enforce group and classification
  scopes in enforce mode.
- Agents are allowed to spawn, but requested permissions beyond the spawner are
  trimmed from the effective snapshot and audited. They should hit permission
  walls at use time and create access requests rather than being blocked from
  spawning.
- Each spawned agent gets an `agent_vault.json` workdir manifest and
  `agent_vault_leases` rows. `/api/agents/{id}/vault/lease` evaluates one
  system/resource/action at a time, returns a scoped vault reference on allow,
  returns HTTP 403 on deny, and never returns secret values.
- Permission proof smoke:
  `python scripts/smoke_permission_vault_e2e.py --print-seed-sql`, seed the SQL,
  then run `python scripts/smoke_permission_vault_e2e.py http://127.0.0.1:25480`
  during an enforcement test window.
- Latest live proof, 2026-05-14: marker
  `PERMISSION_VAULT_E2E_1778761664`, tickets `480` and `481`, agent `170`,
  Dev Y blocked from Dev Z ticket/lease, Dev Z scoped to both queues, GitLab
  `dev-y/*` lease allowed, GitLab `dev-z/app` lease denied with HTTP 403, no
  secret values returned, final active agent count `0`.
- Latest local+iTop provider permission matrix, 2026-05-14: marker
  `PERMISSION_PROVIDER_MATRIX_1778768984`, Dev Y local ticket `509`, Dev Z
  restricted ticket `510`, iTop parent `511` / provider ref `299`, access child
  `512` / provider ref `300`, agent `181`, GitLab Dev Y lease allowed, GitLab
  Dev Z lease denied, iTop Team Y lease allowed, iTop Team Z lease denied then
  granted as lease id `64`, and the iTop access child resolved in the provider.
- Latest fully agentic first-alias permission/vault proof, 2026-05-14: marker
  `AGENTIC_PERMISSION_VAULT_1778778629`, parent ticket `525`, initial agent
  `190`, resumed agent `191`, access request `12`, iTop access child `527`
  / provider ref `304`, and change gate `154`. Agent `190` spawned under
  Dev Team Y, got GitLab `dev-y/*` read lease `93`, was denied GitLab
  `dev-z/app` read with `missing_agent_vault_lease`, wrote the permission wall
  note, created the iTop-synced access request, and stopped at
  `awaiting_access`. After approval, agent `191` completed change `154`,
  minted scoped Dev Z leases `98`/`99` for the original and resumed agents,
  re-requested its own Dev Z lease and received only
  `<vault:gitlab_dev_z_read_after_approval>` with `credential_value: null`,
  resolved parent ticket `525`, resolved access child `527` in iTop, wrote
  final checkpoint `vault-access-complete-AGENTIC_PERMISSION_VAULT_1778778629`,
  and exited cleanly. Wrapper result: `status: passed`, `task_status:
  completed`, `task_progress: 100`, final active agent count `0`.
- Runner hardening from that proof: `_terminate_after_blocking_checkpoint`
  watches owned harness workdirs for durable wait checkpoints such as
  `waiting_for_access` and stops only that owned harness process so approval
  and resume can continue. `/api/agents/processes` reconciles active task IDs
  from stored DB PIDs as well as the in-memory process map.

### Live Note Steering

Active ticket agents receive human/provider note updates without being stopped.
`POST /api/tickets/{ticket_id}/notes` creates `agent_steering_events` for
currently running ticket agents when the note source is `dashboard`, `itop`,
`servicenow`, `jira`, `provider`, `requester`, or `user-response`. The runner
mirrors those events into the agent work directory as
`agent_steering_inbox.json` and `AGENT_STEERING.md`.

Agents must read the steering inbox before major actions and checkpoints. They
should treat updates as additional context, keep the original ticket objective,
record any changed decision in a note, and continue unless the new note creates
an access, approval, safety, or requester wait gate. Agent-authored and
control-plane notes are ignored for steering to prevent self-steering loops.

Provider note sync: iTop `public_log` / `private_log` diffs are mirrored into
canonical ticket notes with source `itop`, which then steer active agents the
same way dashboard notes do.

Real active-agent proof:

```bash
python scripts/agentic_note_steering_demo.py http://127.0.0.1:25480 qwen/qwen3.6-27b
```

Expected evidence: one active agent observes both `DASHBOARD_STEER` and
`ITOP_STEER` updates, writes `STEERING_OBSERVED_DASHBOARD`,
`STEERING_OBSERVED_ITOP`, and `STEERING_COMPLETE` notes, and completes the
ticket with a 100% checkpoint without being restarted.

Latest verified proof: ticket `530`, iTop `UserRequest::307`, agent `193`,
task `190`, marker `NOTE_STEERING_1778787230`. Steering event `3` delivered
dashboard note `1075`; steering event `4` delivered iTop note `1079`; the agent
completed at 100%, and a forced iTop sync preserved local status `resolved`
while the provider payload still reported `new`.

`/api/dashboard/ops-metrics` includes two separate SLA views:

- `sla`: ticket create-to-resolution compliance by priority.
- `postmortem_sla`: resolved tickets that require learning follow-up, first
  postmortem latency, missing/late postmortems, at-risk postmortems,
  `total_postmortems`, and compliance against the 24-hour postmortem target.
  Use this field when checking whether the agentic loop actually completed
  postmortem artifacts after resolving tickets.

The Overview `Agent Task Runtime` cards are task-run metrics, not artifact
inventory. `Postmortem agent task` means postmortem-agent runs, while the
actual postmortem artifact count is shown in the SLA / Tool Snapshot
`Postmortems` row from `postmortem_sla.total_postmortems`. `95% under` is the
95th percentile working time: 95% of completed task runs of that type finished
at or below that time.

### Tools — `/api/tools`

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/tools` | List all tools with last health check status |
| GET | `/api/tools/status` | Health summary (healthy/degraded/down/unknown counts) |
| GET | `/api/tools/{id}` | Tool detail with last 50 health checks |
| GET | `/api/tools/{id}/history` | Check history for last N hours (default 24) |
| POST | `/api/tools/{id}/check` | Trigger single tool health check |
| POST | `/api/tools/check-all` | Trigger health check for all tools |

### Root

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Serve frontend index.html |
| GET | `/health` | Health check returns `{"status": "ok", "version": "1.0.0"}` |

## Background Services

Three background tasks start on app startup via the FastAPI lifespan:

1. **iTop Sync Loop** (`itop_sync.sync_loop`) — Runs every 2 seconds (configurable via `ITOP_DISCOVERY_INTERVAL`). Performs fast discovery for new tickets, full sync every 60 seconds. Broadcasts sync events over WebSocket.

2. **Health Check Loop** (`health_check.health_loop`) — Runs every 60 seconds (configurable via `HEALTH_CHECK_INTERVAL`). Checks all registered tools via port scan or HTTP request. Records results to `tool_checks` table.

3. **Agent Monitor Loop** (`agent_monitor.monitor_loop`) — Runs every 15 seconds (configurable via `AGENT_HEARTBEAT_INTERVAL`). Detects stalled agents (no heartbeat for 120+ seconds), marks them as 'stalled', writes audit entries, broadcasts over WebSocket.

### Local Model Runner Policy

The reference AI server currently runs slow local models. Do not use short wall-clock process timeouts for agent work.

- `AGENT_TIMEOUT_MINUTES=0`: no fixed wall-clock kill for valid local-model work.
- `MAX_CONCURRENT_AGENTS=1`: one active dashboard agent in the current lab so queued tasks do not saturate the local model.
- Agent launch is priority-queued inside the runner. Lower rank runs first:
  P1/critical/emergency, then P2/high, then P3/medium/normal, then P4/low.
  Postmortem/workflow-build/rerun tasks are ranked after same-priority ticket
  resolution work, so high-priority tickets can overtake lower-priority queued
  work when the local model lane is capped.
- `AGENT_NO_OUTPUT_STALL_SECONDS=3600`: configurable no-output stall guard. This is a last-resort harness-hang guard, not a progress timer; streaming or tool-using agents should continue.
- The agent auditor is the primary supervision path. Judge status from task logs, checkpoints, notes, audit entries, and process state, not from percent alone.
- Before rebuilding the API container, check `/api/agents/active` and `/api/agents/processes`. Stop only agents in your current test swim lane, with an explicit audit reason.
- The auditor can recover terminal bookkeeping when persisted evidence proves a
  running ticket-resolution task is already complete. Required evidence:
  ticket closed/resolved, no open change gates, final agent evidence notes, and
  completed change or postmortem evidence. Latest proof: agent `166` / task
  `163` on ticket `472` was finalized from terminal evidence.
- Per-agent curl guards block broad dashboard schema/tool endpoints (`/openapi.json`, `/api/tools`, `/docs`, `/redoc`) and cap oversized curl output so local agents stay on bounded ticket/evidence context.
- Task/checkpoint completion is intentionally strict: `done` / `completed`
  checkpoints below `100%` are ignored. Agents must use `running` for
  intermediate checkpoints, then final `done` at `100%` only after approval
  gates, ticket notes, and required evidence are complete.
- Agent/task completion does not automatically resolve the parent ticket.
  Closure is an explicit workflow/deployment decision. Default ticket workflows
  have the agent call `POST /api/tickets/{ticket_id}/status` after final
  evidence and verification. Human-review, requester-wait, access-gated, or
  manual-provider-handoff deployments can leave the ticket open with an
  explanatory note; use `close_provider: true` only when the external ITSM
  record should also close.
- Source-code and CI/CD agents require git in the runtime. If a prompt asks for
  `git diff`, `git status`, patch artifacts, merge request evidence, or GitLab
  remediation, verify `git --version` inside the agent/API container before the
  run. Missing git is a harness defect, not a model limitation.

### Agentic Source Self-Repair Smoke

Use this pattern when proving that the dashboard can repair its own source code
or a customer-local customization:

1. Create an isolated source copy under `/app/agent_work/<agent_id>/source-repo`.
2. Seed a failing unit test first; do not hand the model a patch.
3. Require every source command to use
   `cd /app/agent_work/<agent_id>/source-repo && <command>` because Bash calls
   do not preserve cwd between tool uses.
4. Require a low-risk approval gate before the agent edits source.
5. After approval, require compile/unit verification plus `git status --short`
   and `git diff -- <changed-files>` evidence.
6. Reconcile the agent-created patch back into the product repo only after an
   operator verifies the isolated workspace output.

Latest proof, 2026-05-13:

- First attempt ticket `441` / agent `158` found the stateless-cwd prompt
  defect and was stopped in-lane after repeating the same verification error.
- Hardened retry ticket `442` / agent `159` / task `156` / change `128`
  succeeded: the local model diagnosed the failing test, requested approval,
  wrote `scripts/agentic_self_repair_marker.py`, passed compile and unit tests,
  completed the gate, wrote note `770`, and finished with checkpoint `done` at
  `100%`.
- The run also exposed missing `git` in the API image. `api/Dockerfile` now
  installs git so source, CI/CD, GitLab, and patch-evidence flows have the tool
  they are already allowed to call.

### 2026-05-14 Agentic Proofs

- Phishing lifecycle ticket `472`: agent `166` wrote triage note `882`,
  no-containment note `883`, final resolution note `884`, closed the ticket
  with note `885`, and the auditor finalized task `163` from terminal evidence.
- Core smoke ticket `474`: agent `167` completed approval-gated URL block
  change `143`, wrote triage note `894`, approval evidence note `895`,
  resolution note `896`, resolved the ticket with note `897`, and created
  postmortem `81`.
- Permission-wall resume ticket `476`: first agent `168` stopped at
  `awaiting_access`, created access request `4`, iTop access ticket `477`
  / provider ref `289`, and change `144`. Approval by
  `access-demo-approver` spawned resumed agent `169`, which completed the
  access grant evidence, wrote final `ACCESS RESUME COMPLETE` notes, and
  resolved the parent ticket.

### Current Real-Flow Proofs

Latest live report-phish proof, verified 2026-05-13 UTC:

- Marker `CODEX_PHISH_E2E_1778637511`.
- iTop Incident `236` / `I-000245`, dashboard ticket `364`.
- Local-model agent `127`, task `124`.
- Agent wrote triage note `491`, created approval gates `100`, `101`, and
  `102`, resumed after `codex-e2e-lab-approver` approval, completed the three
  gates with lab-safe evidence, wrote resolution note `502`, created postmortem
  `47`, and finished at `100%`.
- Direct iTop read confirmed Incident `236` status `resolved`, solution populated
  from the agent completion summary.

Latest live EDR/Sysmon proof, verified 2026-05-12:

- Marker `CODEX_SYSMON_E2E_1778632686`.
- EDR/Sysmon E2E passed `16/16`, produced two Wazuh alerts, bridged to dashboard
  ticket `354`, and local-model agent `123` resolved the ticket.
- Provider close and forced single-ticket sync kept dashboard and iTop status
  `resolved`.

## Database Schema

Raw PostgreSQL — **NO ORM, NO Pydantic, NO SQLAlchemy**. All queries use parameterized raw SQL via asyncpg.

### Tables

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `tools` | SOC tools inventory | name, type, host, port, status, description |
| `tool_checks` | Health check history | tool_id FK, timestamp, status, response_time_ms, error |
| `tickets` | Mirrored iTop tickets | itop_ref, itop_class, title, status, priority, impact, urgency, assignee, agent_id FK |
| `agents` | AI agent instances | ticket_id FK, model, status, heartbeat, started_at, finished_at, error_message |
| `change_requests` | Change approval workflow | agent_id FK, ticket_id FK, action, target, status, requested_at, expires_at, approved_by |
| `audit_log` | All system actions | actor, action, target, details (JSONB), created_at |
| `dashboard_settings` | Runtime configuration | key, value (JSONB) |

### Indexes

- `idx_tickets_status`, `idx_tickets_itop_ref`
- `idx_agents_status`, `idx_agents_ticket_id`
- `idx_change_requests_status`, `idx_change_requests_agent_id`
- `idx_audit_log_created_at`
- `idx_tool_checks_tool_id`, `idx_tool_checks_timestamp`

### Default Tools

iTop ITSM, Wazuh SIEM, Wazuh Indexer, Wazuh Dashboard, Zeek IDS, Suricata IDS, Mailcow, Keycloak, SOC Bridge, SIEM-Ticket Bridge, SearXNG, GitLab, and TheHive.

ComfyUI, torrenting, and media tooling are intentionally excluded from the IT/SOC platform inventory.

### Default Settings

- `theme`: dark mode with cyan primary
- `sync_enabled`: iTop sync enabled, 30s interval
- `health_check_enabled`: enabled, 60s interval
- `agent_config`: qwen/qwen3.6-27b model, 15s heartbeat, 120s stalled threshold, 3 max retries

## Frontend Pages

Six pages accessible via sidebar navigation:

| Page | Description |
|------|-------------|
| **Overview** | Stat cards (tickets, agents, changes), 3 charts (ticket trend, agent distribution, tool uptime), activity feed, pending changes section |
| **Tickets** | Table with status filter, assign agent button, detail modal with agent info + change requests + activity log |
| **Agents** | Grid view grouped by status (active/stalled/history), Wake/Restart/Stop buttons, auto-refresh every 10 seconds |
| **Changes** | Table with status filter, approve/reject buttons for pending changes |
| **Tools** | Grid of tool cards with health status dots, check-all button |
| **Audit** | Timeline of all system actions with actor/action/target |

### Frontend File Structure

```
/frontend/
├── index.html           # Main SPA with all 6 page sections
├── css/
│   └── dashboard.css   # Dark operations theme, all styles
├── js/
│   ├── dashboard.js    # Navigation, stats, tickets, changes, tools, audit, ticket modal
│   ├── charts.js       # Chart.js integration (3 charts: trend, distribution, uptime)
│   ├── agents.js       # Agent grid, stalled detection UI, wake/restart/stop
│   └── websocket.js    # WebSocket client with auto-reconnect, notifications
```

### Charts (Chart.js 4.4.7)

1. **Ticket Volume (7 Days)** — Line chart with cyan fill, shows daily ticket creation
2. **Agent Status Distribution** — Doughnut chart, color-coded by status
3. **Tool Uptime** — Horizontal bar chart, green/yellow/red by percentage

### Real-Time Updates

- WebSocket connects to `/api/agents/ws` on page load
- Auto-reconnect with 5-second delay on disconnect
- Handles events: `agent_spawned`, `agent_stalled`, `agent_finished`, `agent_stopped`, `change_pending`, `ticket_synced`, `ticket_updated`, `sync_complete`, `tool_status_changed`
- Shows toast notifications for significant events
- Auto-refreshes the active page on events
- Connection status indicator in sidebar footer (Live/Offline)
- Heartbeat ping every 30 seconds to keep connection alive

### Auto-Refresh

- Overview/Tickets/Agents/Changes pages auto-refresh every 30 seconds
- Agents page has an additional 10-second refresh interval

## Configuration

All configuration is via environment variables in `.env`:

| Variable | Default | Description |
|----------|---------|-------------|
| `SOC_DB_USER` | `soc_user` | PostgreSQL username |
| `SOC_DB_PASSWORD` | generated or vault-backed | PostgreSQL password |
| `ITOP_HOST` | `localhost` | iTop server hostname |
| `ITOP_PORT` | `25432` | iTop REST API port |
| `ITOP_USER` | `admin` | iTop API username |
| `ITOP_PASSWORD` | vault-backed | iTop API password |
| `ITOP_SECURITY_TEAM_ID` | `65` | iTop security team ID |
| `ITOP_DEFAULT_ORG_ID` | auto-resolved | Optional iTop Organization ID for outbound creates |
| `ITOP_DEFAULT_CALLER_ID` | auto-resolved | Optional iTop Person ID for Incident/UserRequest caller |
| `ITOP_DISCOVERY_INTERVAL` | `2` | Seconds between iTop discovery scans |
| `ITOP_FULL_SYNC_INTERVAL` | `60` | Seconds between full iTop syncs |
| `HEALTH_CHECK_INTERVAL` | `60` | Seconds between tool health checks |
| `AGENT_HEARTBEAT_INTERVAL` | `15` | Seconds between agent monitor checks |
| `AGENT_STALLED_THRESHOLD` | `120` | Seconds before agent marked as stalled |

### iTop Ticket Classes Synced

Incident, RoutineChange, NormalChange, EmergencyChange, UserRequest

### iTop Outbound Create

The dashboard uses `api/services/itop_sync.py` for outbound provider create. It now syncs to iTop when possible and falls back only for real provider failures:

- `Incident` and `UserRequest` creates include `org_id`, `caller_id`, and optional `team_id`.
- `Incident` priority is mapped to iTop `impact` and `urgency`.
- `ITOP_DEFAULT_ORG_ID` and `ITOP_DEFAULT_CALLER_ID` are preferred when set.
- If those defaults are absent, the adapter resolves Organization `1` or the first Organization, then a Person in that org or the first Person.
- If iTop cannot provide org/caller context, the canonical ticket records `provider_sync_status=create_failed` with `provider_last_error`.

Verified on 2026-05-12: direct dashboard creates produced `UserRequest::169` and `Incident::170` with `provider_sync_status=synced`, `org_id=1`, `caller_id=94`, and `team_id=65`.

## Latest Stability Proof

Verified on 2026-05-13:

- Bridge logrotate installed at `/etc/logrotate.d/siem-ticket-bridge`.
- Sysmon hot directory cleaned so the 16 GB historical archive lives under
  `/var/log/sysmon/archive`, with active log rotation tightened to 32 MB.
- `reference_skills/wazuh-edr-sysmon/tests/test_edr_sysmon_e2e.py` passed
  16/16 using fresh marker `CODEX_SYSMON_E2E_1778680907`.
- Bridge created iTop Incident `275`; dashboard imported ticket `431`; RACI
  auto-assigned local-model agent `151`; agent classified the diagnostic marker
  as false positive, wrote notes `708`, `709`, `711`, postmortem `64`, and
  resolved dashboard + iTop `I-000284`.

## Management Commands

```bash
# Check container status
python "C:/Users/cereal/.agents/skills/server-manager/ssh_client.py" --server ai --execute "docker ps --filter name=soc-dashboard"

# View API logs
python "C:/Users/cereal/.agents/skills/server-manager/ssh_client.py" --server ai --execute "docker logs soc-dashboard-api-1 --tail 50"

# Restart API container (no rebuild needed for frontend changes)
python "C:/Users/cereal/.agents/skills/server-manager/ssh_client.py" --server ai --execute "docker restart soc-dashboard-api"

# Access PostgreSQL
python "C:/Users/cereal/.agents/skills/server-manager/ssh_client.py" --server ai --execute "docker exec -it soc-dashboard-db psql -U soc_admin -d soc_dashboard"

# Rebuild API container (after Python code changes)
python "C:/Users/cereal/.agents/skills/server-manager/ssh_client.py" --server ai --execute "cd /home/cereal/SOC_TESTING/soc-dashboard && docker compose up -d --build api"

# Check sync state
python "C:/Users/cereal/.agents/skills/server-manager/ssh_client.py" --server ai --execute "docker exec soc-dashboard-api cat /app/data/.itop_max_keys.json"
```

## Architecture Details

For full architecture, data flow diagrams, service layer details, and deployment blueprint, see [architecture.md](architecture.md).
