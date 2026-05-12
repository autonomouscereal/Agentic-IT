# SOC Dashboard Architecture

Last updated: 2026-05-11.

## Purpose

SOC Dashboard is the control plane for the agentic SOC system. It is designed to be:

- ticketing-system agnostic
- agent-harness agnostic
- local-model or cloud-model compatible
- approval-gated for risky work
- auditable enough for demos, troubleshooting, and future compliance review
- modular enough to deploy into a new environment without rewriting the dashboard

The current implementation uses iTop and Claude Code because those are the active lab systems. Neither is treated as the permanent center of the architecture.

## Runtime Components

| Component | Current implementation | Replaceable boundary |
| --- | --- | --- |
| Dashboard API | FastAPI, raw `asyncpg`, PostgreSQL | API routes should stay stable |
| Database | PostgreSQL 16 | PostgreSQL is mandatory |
| Frontend | Vanilla HTML/CSS/JS | Can be rebuilt as long as API contract remains |
| Ticket provider | iTop plus local provider | `services/ticket_provider.py` and `services/provider_registry.py` |
| Agent harness | Claude Code | `services/agent_harness.py` |
| Model access | LAN proxy at `AGENT_LLM_BASE_URL` | Any OpenAI/Anthropic-compatible proxy/harness bridge |
| Approval system | Dashboard `change_requests` table/API | Can later sync to external CAB/change platforms |
| Memory/learning | Skills, KB, workflows, postmortems | Can later ingest external KB/tickets/docs |
| Email provider | Mailcow reference stack plus optional API shim | Exchange, Gmail, Proofpoint, Mimecast, or another email/security adapter |

## Canonical Data Model

The dashboard owns canonical records. External systems mirror into or out of those records.

Core tables:

- `tickets`: canonical ticket record plus provider metadata.
- `ticket_notes`: internal/user-visible notes from dashboard, agents, sync jobs, and future providers.
- `ticket_attachments`: metadata for attachments; binary storage is intentionally external.
- `agents`: agent instance lifecycle.
- `agent_tasks`: runnable unit of work, prompt, status, checkpoints, output, PID, work directory.
- `change_requests`: approval gate for potentially destructive actions.
- `postmortems`: structured learning after ticket completion.
- `agent_workflows`: reusable automation/workflow blueprint records.
- `workflow_runs`: execution records for reusable workflows.
- `knowledge_articles`: local reusable documentation.
- `agent_skills`: prompt-level reusable capabilities.
- `audit_log` and `event_log`: durable action/event history.
- `tools` and `tool_checks`: tool inventory and health checks.

Provider metadata on `tickets`:

- `provider`: `local`, `itop`, later `servicenow`, `jira`, etc.
- `provider_ref`: external ticket id/reference.
- `provider_class`: external ticket class/type.
- `provider_url`: external ticket URL when known.
- `provider_sync_status`: `synced`, `local_only`, `pending_create`, `create_failed`, `unknown`.
- `provider_last_error`: last provider sync/create failure.
- `provider_payload`: raw provider payload or result for debugging.

## Ticket Sync Flow

Inbound provider flow:

1. Provider adapter discovers or fetches a ticket.
2. Provider adapter upserts `tickets`.
3. Provider metadata is recorded.
4. Dashboard frontend shows the same canonical ticket shape regardless of provider.
5. Agent context reads from `/api/tickets/{id}/context`.

Outbound dashboard flow:

1. Dashboard creates a canonical ticket through `POST /api/tickets`.
2. If `sync_provider=false`, ticket remains local-only.
3. If `sync_provider=true`, `ticket_service.create_ticket()` calls `provider_registry.create_ticket()`.
4. Provider returns success, `local_only`, or `error`.
5. Dashboard updates `provider_sync_status`, `provider_last_error`, and `provider_payload`.
6. Existing tickets can be pushed manually with `POST /api/tickets/{id}/push-provider`.

iTop outbound creation is intentionally guarded. Incident/UserRequest creation requires:

- `ITOP_DEFAULT_ORG_ID`
- `ITOP_DEFAULT_CALLER_ID`

Without those values, the dashboard records `create_failed` instead of claiming a false sync.

## Agent Harness Flow

1. Operator assigns an agent or creates one from a prompt.
2. API inserts an `agents` row.
3. API inserts an `agent_tasks` row.
4. Runner creates `/app/agent_work/<agent_id>`.
5. Runner writes `.claude/CLAUDE.md`, `.claude/settings.json`, `checkpoint.json`, and `output.log`.
6. Runner invokes the configured harness through `services/agent_harness.py`.
7. Claude Code currently runs with:

```bash
claude --allowedTools "Read,Write,Bash(curl *)" -p --settings <settings> --model <model> --permission-mode acceptEdits --no-session-persistence --output-format stream-json --verbose "<prompt>"
```

8. Runner streams stdout/stderr into `output.log` and mirrors tails into `agent_tasks.output`.
9. `task_tracker` polls `checkpoint.json` and process state.
10. If checkpoint status is `done` or `completed`, the task is completed and the harness process is terminated so local GPU work does not continue unnecessarily.

## Wake, Restart, Stop

`Wake`:

- If a queued/running task exists, refresh heartbeat and return that task.
- If no active task exists, spawn a replacement using the latest stored prompt and task type.
- It does not blindly toggle UI state.

`Restart`:

- Stop active task if present.
- Terminate old agent row.
- Spawn a replacement for the same ticket/model/prompt.

`Stop`:

- Terminate tracked subprocess when possible.
- Mark task and agent stopped.
- Record audit/event entries.

## Approval Guardrail

Agents are instructed to request approval before any action that can alter an environment, data, accounts, mailboxes, firewall rules, blocklists, services, repositories, or production state.

The approval API:

- `POST /api/changes/request`
- `GET /api/changes/{id}/status`
- `POST /api/changes/{id}/approve`
- `POST /api/changes/{id}/reject`
- `POST /api/changes/{id}/complete`

The current lab can manually approve from the dashboard. Future deployments can attach this to iTop change workflows, ServiceNow change tasks, CAB rules, Keycloak roles, or external approval systems.

## Learning Loop

Ticket work is intentionally separated from workflow creation.

Fast ticket path:

1. Read full context.
2. Resolve the task as quickly and safely as possible.
3. Use approvals when required.
4. Write notes/checkpoints.
5. Finish.

Postmortem path:

1. Review ticket, notes, logs, checkpoints, approvals, failures, and final result.
2. Record what worked and what should improve.
3. Propose skills/workflows/tests/guardrails.
4. Mark for human review.
5. Promote reviewed learning into reusable assets when appropriate:
   knowledge article, draft workflow, candidate skills, ticket note, and audit
   record. Promotion is idempotent per postmortem so repeated review updates the
   same assets rather than duplicating them.

Workflow-build path:

1. Build reusable workflow blueprint.
2. Define approval boundaries.
3. Define tests and safe test environment assumptions.
4. Persist workflow in draft/tested state.
5. Stop before production activation until reviewed.

## Fresh Deploy Versus Developed Environment

Fresh environment:

- PostgreSQL starts from `api/init_db.sql`.
- iTop can be disabled with `ITOP_SYNC_ENABLED=false`.
- Local provider allows dashboard/agent workflows without any external ticketing system.
- Agents can run if `AGENT_LLM_BASE_URL` and Claude Code credentials/proxy are configured.

Developed environment:

- Apply migrations in order.
- Keep provider credentials in environment/vault only.
- Sync provider tickets into canonical records.
- Add provider-specific skills and KB articles.
- Review and approve workflows before activation.

## Email Provider Boundary

The dashboard should treat email as a provider capability, not as a hard dependency on Mailcow. The reference lab currently uses:

- Mailcow for the open-source email stack.
- Keycloak-Mailcow bridge scripts for provisioning and sync through direct MySQL.
- Optional Mailcow HTTP API shim for read-only compatibility checks and future adapter-style reads.

The Mailcow HTTP shim is documented in `docs/MAILCOW_API_SHIM.md`. It exposes only domain, mailbox, and alias inventory and intentionally omits password hashes. It should not be used as a generic write API. In production-style deployments, a customer email product should satisfy the same provider contract through its own adapter while tickets, approvals, audit logs, and agent context remain canonical in the dashboard.
