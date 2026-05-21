# Agentic Operations API Reference

Last updated: 2026-05-20.

Base URL in the current lab:

```text
http://192.168.50.222:25480
```

Agent workspaces inside the API container should use:

```text
http://localhost:8000
```

All request/response bodies are JSON unless noted. The API is the canonical
contract for tickets, agents, approvals, workflows, setup, tools, learning, and
audit across provider-backed enterprise work. It uses raw PostgreSQL through
`asyncpg`; no application ORM/Pydantic/SQLAlchemy models are used.

External product APIs are documented separately from this dashboard API. The reference Mailcow HTTP compatibility shim is documented in `docs/MAILCOW_API_SHIM.md`; it exposes read-only Mailcow-style domain, mailbox, and alias endpoints on the Mailcow host and is not part of the dashboard API namespace.

## Health

`GET /health`

Returns API status and version.

## Tickets

`GET /api/tickets`

Query parameters:

- `status`
- `priority`
- `assignee`
- `agent_only`
- `limit`
- `offset`

Returns canonical ticket rows with provider metadata and `external_url` when available.

`POST /api/tickets`

Creates a canonical ticket.

Example:

```json
{
  "title": "Investigate phishing report",
  "description": "User reported suspicious email.",
  "ticket_class": "Incident",
  "status": "new",
  "priority": "2",
  "created_by": "dashboard",
  "auto_assign": true
}
```

Ticket creation syncs to the active external provider automatically when one is
configured, and falls back to `provider_sync_status=local_only` otherwise. For
iTop Incident/UserRequest creation, configure `ITOP_DEFAULT_ORG_ID` and
`ITOP_DEFAULT_CALLER_ID`. When `auto_assign` is true, the dashboard evaluates
enabled RACI rules with `auto_assign_agent=true` and spawns an agent only when
one of those rules matches.

`GET /api/tickets/{ticket_id}`

Returns ticket detail, current agent fields, change requests, and `external_url`.

`GET /api/tickets/{ticket_id}/context`

Returns the full agent context bundle:

- ticket
- notes
- attachments
- change requests
- recent tasks
- postmortems
- related tickets
- knowledge articles
- matching workflows
- global skills
- access requests linked to the ticket or created from the ticket

`POST /api/tickets/{ticket_id}/notes`

Example:

```json
{
  "body": "Scoped recipients and found no additional delivery.",
  "author": "agent_26",
  "source": "agent",
  "visibility": "internal"
}
```

When the note source is a human or ticketing provider source such as
`dashboard`, `itop`, `servicenow`, `jira`, `provider`, `requester`, or
`user-response`, the dashboard creates non-interrupting steering events for any
currently active ticket agents. The runner mirrors those updates into the
agent's work directory as `agent_steering_inbox.json` and `AGENT_STEERING.md`.
Agent-authored and control-plane notes are ignored for steering so agents do
not steer themselves from their own progress notes.

`GET /api/agents/{agent_id}/steering`

Lists recent steering events delivered or pending for an agent.

`POST /api/agents/{agent_id}/steering/{event_id}/ack`

Marks a steering event acknowledged after the agent incorporates it.

`POST /api/tickets/{ticket_id}/attachments`

Stores attachment metadata only. Binary storage should be external.

`GET /api/tickets/{ticket_id}/access-requests`

Lists permission-wall access requests linked to this ticket, including the child
access ticket, approval gate, and grant status.

`POST /api/tickets/{ticket_id}/access-request`

Creates a child access request ticket assigned to the owning RACI group and a
change approval gate linked to the original ticket/agent. Approval of that gate
resumes the original ticket when no active task is already running.

Example:

```json
{
  "agent_id": 123,
  "resource": "GitLab project demo/private-infra",
  "permission": "Developer repository read access",
  "account_ref": "agent-123",
  "assignment_group": "DevSecOps",
  "risk_level": "medium",
  "sync_provider": false,
  "reason": "Repository API returned 403; least-privilege read access is required before evidence can be reviewed."
}
```

`POST /api/tickets/{ticket_id}/request-info`

Adds a user-visible clarification request note and sets ticket status to
`awaiting_user_response`.

`POST /api/tickets/{ticket_id}/user-response`

Records the requester answer, restores the previous ticket status, and can
resume the assigned agent when no active task is already running.

`POST /api/tickets/{ticket_id}/sync`

Pulls a provider ticket into the canonical record.

`POST /api/tickets/sync-all`

Body can be omitted, a raw provider string, or:

```json
{"provider": "itop"}
```

`POST /api/tickets/{ticket_id}/push-provider`

Pushes an existing canonical ticket to a provider.

Example:

```json
{"provider": "itop"}
```

`POST /api/tickets/{ticket_id}/status`

Explicit ticket status update. Agent completion does not close tickets
automatically; default ticket workflows make the agent call this endpoint after
final evidence and verification. Human-review deployments can skip the call or
set `close_provider: false` when the external record should remain open.

Example:

```json
{
  "status": "resolved",
  "actor": "agent-159",
  "reason": "All approved containment steps completed, tests passed, residual risk documented.",
  "close_provider": true
}
```

Use `close_provider: false` when the dashboard status should change but the
external ITSM record should remain open for human review.

Compatibility: `POST`, `PUT`, and `PATCH /api/tickets/{ticket_id}` accept the
same explicit status payload. This exists for local agents that infer a REST
update on the ticket resource itself. The compatibility path uses the same
access checks, status validation, audit note, and provider-close opt-in behavior
as `/status`; new code should still prefer `/status`.

`POST /api/tickets/{ticket_id}/assign-agent`

Body:

```json
{
  "model": "qwen/qwen3.6-27b",
  "prompt": "Optional override prompt"
}
```

`POST /api/tickets/{ticket_id}/postmortem`

Spawns a postmortem agent.

`POST /api/tickets/{ticket_id}/workflow`

Spawns a workflow-build agent.

`POST /api/tickets/{ticket_id}/unassign-agent`

Terminates and unassigns the ticket's current agent.

## Providers

`GET /api/providers`

Lists registered providers. Current providers:

- `local`
- `itop`

`POST /api/providers/{provider}/sync-all`

Pull sync for one provider.

`POST /api/providers/{provider}/sync-ticket`

Body:

```json
{
  "ticket_class": "Incident",
  "ticket_ref": "123"
}
```

## Agents

`GET /api/agents`

Filters:

- `status`
- `ticket_id`

`GET /api/agents/active`

Returns active agent records.

`GET /api/agents/stats`

Returns aggregate counts and average duration.

`GET /api/agents/models`

Returns models from `agent_models.json`.

`GET /api/agents/runner-health`

Returns:

- selected harness availability
- Hermes, Claude Code, and Codex diagnostics when configured
- Codex `codex_auth_mode` and `codex_login_status`; OAuth/subscription
  deployments should show `codex_login_status.status=logged_in` after the
  device-auth enrollment gate completes
- credentials mount status
- configured harness
- default model
- effective model API/proxy URL
- model API reachability
- permission mode and allowed tools

`GET /api/agents/processes`

Returns process diagnostics from inside the API container, including `ps_path`, process list, and tracked active processes.

`POST /api/agents/spawn`

Spawns an agent for an existing ticket.

`POST /api/agents/create-from-prompt`

Creates a local ticket and spawns an ad hoc agent.

`GET /api/agents/tasks`

Filters:

- `status`
- `agent_id`
- `ticket_id`

`GET /api/agents/tasks/{task_id}/logs`

Returns `output.log` tail or DB output fallback.

`GET /api/agents/{agent_id}`

Returns agent detail, latest task, changes, and audit records.

`GET /api/agents/{agent_id}/logs`

Returns latest task logs for an agent.

`GET /api/agents/{agent_id}/wazuh/manager/status`

Returns Wazuh manager status only after the agent has an active scoped
`wazuh/api/wazuh.manager/read` vault lease. Response includes `lease_id`,
`credential_ref`, `secret_values_returned: false`, and Wazuh status data.

`GET /api/agents/{agent_id}/wazuh/rules/{rule_id}`

Returns Wazuh rule metadata after validating the same scoped Wazuh lease.

`GET /api/agents/{agent_id}/wazuh/alerts/search`

Query params:

- `rule_id`
- `source_ip`
- `limit`

Searches Wazuh indexer alerts after validating the scoped Wazuh lease. Requires
runtime `WAZUH_INDEXER_*` configuration. Secret values are never returned.

`POST /api/agents/{agent_id}/wake`

Refreshes active task heartbeat or spawns a replacement from latest task prompt.

`POST /api/agents/{agent_id}/restart`

Stops active task, terminates old agent row, and spawns replacement.

`POST /api/agents/{agent_id}/stop`

Body:

```json
{"reason": "operator_stop"}
```

`POST /api/agents/{agent_id}/update`

Legacy/manual status update endpoint.

`GET /api/agents/ws`

WebSocket for real-time agent events.

## Change Requests

`GET /api/changes`

Filters:

- `status`
- `agent_id`
- `ticket_id`

`GET /api/changes/pending`

Returns pending non-expired changes.

`GET /api/changes/stats`

Aggregate counts.

`GET /api/changes/{change_id}`

Full change detail.

`GET /api/changes/{change_id}/status`

Compact polling endpoint for agents.

`POST /api/changes/request`

Example:

```json
{
  "agent_id": 26,
  "ticket_id": 28,
  "action": "block_url",
  "target": "https://example.invalid/phish",
  "reason": "Confirmed phishing URL.",
  "command": "no-op in lab",
  "risk_level": "medium",
  "approval_policy": {"requires_human": true}
}
```

`POST /api/changes/{change_id}/approve`

```json
{"approved_by": "operator", "reason": "Reviewed evidence and approved scoped action."}
```

Demo/lab auto-approvers can use an identity such as
`demo-auto-approver`. The audit payload then includes
`approval_gate=true`, `approval_mode=demo_auto_approval`, and
`auto_approved=true`.

`POST /api/changes/{change_id}/reject`

```json
{"rejected_by": "operator", "reason": "Insufficient evidence"}
```

`POST /api/changes/{change_id}/complete`

```json
{"completed_by": "agent_26", "result": "URL block applied in test environment with verification evidence."}
```

Completed changes write both event and audit records. The agent supervisor can
also auto-complete approved agent-linked changes after a completed task, unless
the approval policy sets `auto_complete=false` or
`manual_completion_required=true`.

Change request, approval, rejection, and completion transitions also write
canonical ticket notes so the ticket timeline shows the approval chain during
demos and audits.

## Learning

Postmortems:

- `GET /api/postmortems`
- `GET /api/postmortems/evidence/{ticket_id}` - compact postmortem evidence for agents, including notes, attachment metadata, change requests, task summaries with bounded log tails, CI/CD runs, prior postmortems, and audit/event entries
- `GET /api/postmortems/{id}` - includes `promotion_assets` with promoted knowledge articles, skills, `workflow_key`, and the promoted workflow resolved by promotion audit details or by key fallback.
- `POST /api/postmortems/synthesize/{ticket_id}` - supervisor fallback that creates a `ready_for_review` postmortem from bounded evidence when a model postmortem fails or stalls
- `POST /api/postmortems`
- `PUT /api/postmortems/{id}`
- `POST /api/postmortems/{id}/review`
- `POST /api/postmortems/{id}/promote` - turns an approved/reviewed postmortem into reusable assets: a knowledge article, draft workflow, candidate skills, a ticket note, and audit/event records. The workflow is draft by default and includes an approval policy requiring human review before production activation. Promotion derives `workflow_key` from the ticket class and postmortem lesson. Similar postmortems update/version the same non-superseded workflow and return `workflow_action` plus `workflow_key` instead of creating postmortem-id/name duplicates.

Workflows:

- `GET /api/workflows`
- `GET /api/workflows/{id}`
- `POST /api/workflows` - derives or honors `approval_policy.workflow_key`. If a non-superseded workflow with that key already exists, the route updates/versions that workflow; names are display labels, not identity. Create/update paths keep workflow status review-gated and do not silently activate automation.
- `PUT /api/workflows/{id}` - updates workflow content, recomputes/stores `workflow_key`, writes it into `approval_policy`, and versions the workflow.
- `POST /api/workflows/{id}/review`
- `POST /api/workflows/{id}/runs`
- `POST /api/workflows/runs/{run_id}/complete`

Service desk intake:

- `GET /api/intake/raci`
- `POST /api/intake/raci/groups`
- `PUT /api/intake/raci/groups/{id}`
- `DELETE /api/intake/raci/groups/{id}`
- `POST /api/intake/raci/rules`
- `PUT /api/intake/raci/rules/{id}`
- `DELETE /api/intake/raci/rules/{id}`
- `POST /api/intake/clarify`
- `POST /api/intake/classify`
- `POST /api/intake/submit`
- `GET /api/intake/sessions`

RACI rules may include `auto_assign_agent`, `auto_agent_model`, and
`auto_agent_prompt`. The seeded phishing rule enables auto-assignment for
Security Operations phishing incidents; other rules remain manual unless this
flag is set. `POST /api/intake/submit` accepts `auto_assign=false` for smoke
tests or manual-only submissions.

CI/CD security:

- `GET /api/cicd/gitlab/template`
- `GET /api/cicd/runs`
- `GET /api/cicd/runs/{run_id}` - includes `repo_url`, internal dashboard scanner report links, external provider artifact links parsed from `tool_results`, and related before/after runs for the same ticket or repository
- `GET /api/cicd/runs/{run_id}/reports/{tool}` - returns the auth-protected dashboard report for `semgrep`, `trivy`, `owasp_zap`, or `nuclei` from the stored canonical run record so operators do not need CI provider credentials to read findings
- `POST /api/cicd/runs`

Global search:

- `GET /api/search/global?q=<query>&limit=60` - RBAC-aware search across tickets, notes, agents, approval gates, postmortems, workflows, CI/CD runs, tools, and audit records. Ticket results are row-level scoped and the endpoint does not return raw secrets.

Ops Chat:

- `GET /api/ops-chat/sessions`
- `GET /api/ops-chat/sessions/{session_id}/messages`
- `POST /api/ops-chat/message` - Matrix/Element chat intake that creates or continues traceable tickets for operational work and queues real Hermes/Claude Code/Codex agent harness tasks. Optional `attachments` entries can include `filename`, `content_type`, `size_bytes`, `storage_ref`, and bounded `data_base64` for Matrix-uploaded files. Optional `harness` / `agent_harness` and `model` / `agent_model` fields can override the chat-intake harness for a targeted room, smoke, or demo request; otherwise the endpoint follows `OPS_CHAT_AGENT_HARNESS` / `AGENT_HARNESS` and `OPS_CHAT_AGENT_MODEL` / `AGENT_DEFAULT_MODEL`.
- `GET /api/ops-chat/outbound/pending` - Matrix bridge poll endpoint for user-facing ticket questions/status updates created by ticket agents
- `POST /api/ops-chat/outbound/ack` - idempotently acknowledges outbound Matrix delivery so bridge restarts do not duplicate ticket updates
- `GET /api/ops-chat/matrix/health` - Matrix/Element/Keycloak bridge readiness metadata
- `GET /api/ops-chat/openai/v1/models` - legacy compatibility model list; Matrix/Element is the supported chat client
- `POST /api/ops-chat/openai/v1/chat/completions` - legacy compatibility endpoint that still routes operational work into tickets and real agents

`POST /api/ops-chat/message` is agent-intake-first. The dashboard invokes the
configured Hermes/Claude/Codex harness with `ops_chat_tool.py`; the harness must
finish with an `answer` tool call for harmless chat or a `create-ticket` tool
call for tracked work. It may ask one concise clarification before ticket
creation when the answer changes routing/scope/urgency. Approval gates are not
created by the chat intake turn; they are created later by real ticket execution
barriers such as access requests, scoped vault leases, workflow policy, or
provider permission failures.

The harness override is validation-only and modular. The endpoint rejects
unknown harness names and accepts only the names registered in
`services.agent_harness` (`hermes`, `claude-code`, `codex` in the current
deployment). Codex does not bypass the bridge; it is invoked through the same
toolbelt and dashboard runner contract as Hermes and Claude Code.

Claude Code uses the proxy's Anthropic Messages route. Runtime env must provide
the proxy token as `ANTHROPIC_API_KEY` as well as `ANTHROPIC_AUTH_TOKEN`, because
newer Claude Code builds report `apiKeySource: none` and retry indefinitely
when only the legacy token variable is present.

Ops Chat harness calls default to one-hour local-agent windows. The endpoint
cleans up child processes on server-side timeout or client cancellation, but
operators should not use short HTTP client timeouts for local model tests.

For chat uploads, the dashboard stores bounded file payloads under
`OPS_CHAT_UPLOAD_DIR`, links them to operational tickets as attachment metadata,
and copies them into the chat harness workspace under `attachments/`. Agent
artifacts returned through `validate-artifact` are stored under
`OPS_CHAT_ARTIFACT_DIR`; small artifacts may be returned to Matrix as
downloadable files.

## Ticket Reassignment And Escalation

`POST /api/tickets/{ticket_id}/assignment`

Updates the canonical dashboard assignment fields and writes a
`ticket-assignment` note for auditability. Use this when a chat/ticket agent or
operator discovers that the scope belongs to another queue or must move to Tier
2/Tier 3.

Request body:

```json
{
  "assignee_team": "Tier 2 Endpoint Support",
  "owning_group": "Endpoint Support",
  "assignee": "endpoint.tier2.demo",
  "escalation_tier": "Tier 2",
  "priority": "P2",
  "actor": "ops-chat-reassignment-smoke",
  "reason": "Requester clarified that endpoint packaging is required."
}
```

Notes:

- `priority` accepts `P1`-`P4` or numeric `1`-`4`.
- `escalation_tier` is audit evidence in the note trail; it is not a separate
  database column.
- Provider-side assignment sync is adapter-specific. The canonical dashboard
  assignment and note are always updated.

Knowledge:

- `GET /api/knowledge`
- `GET /api/knowledge/{id}`
- `POST /api/knowledge`
- `PUT /api/knowledge/{id}`

Skills:

- `GET /api/skills`
- `GET /api/skills/{id}`
- `POST /api/skills`
- `PUT /api/skills/{id}`
- `DELETE /api/skills/{id}`
- `POST /api/skills/{id}/render`
- `GET /api/skills/agent/{agent_id}`

## Dashboard And Audit

`GET /api/dashboard/stats`

Overview counts, trends, pending changes, and recent activity. Recent activity
includes `audit`, `event`, and `note` sources so the overview feed can show
human-readable ticket notes during agent work.

`GET /api/dashboard/audit`

Filters:

- `actor`
- `action`
- `source`
- `category`
- `level`
- `target`
- `q`
- `ticket_id`
- `agent_id`
- `limit`

Merges `audit_log`, `event_log`, and canonical `ticket_notes`.

`source` values:

- `audit`: durable audit rows.
- `event`: operational events.
- `note`: ticket notes, including agent progress notes and agent-authored notes.

`ticket_id` and `agent_id` are normalized from JSON details when available so
the frontend can deep-link from a ticket detail modal into the full trail.

## Tools

- `GET /api/tools`
- `GET /api/tools/status`
- `GET /api/tools/{id}`
- `GET /api/tools/{id}/history`
- `POST /api/tools/{id}/check`
- `POST /api/tools/check-all`
