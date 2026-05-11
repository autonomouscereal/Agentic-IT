# SOC Dashboard API Reference

Last updated: 2026-05-11.

Base URL in the current lab:

```text
http://192.168.50.222:25480
```

Agent workspaces inside the API container should use:

```text
http://localhost:8000
```

All request/response bodies are JSON unless noted. The API uses raw PostgreSQL through `asyncpg`; no application ORM/Pydantic/SQLAlchemy models are used.

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
  "provider": "local",
  "sync_provider": false,
  "created_by": "dashboard"
}
```

Set `sync_provider=true` to attempt provider-side creation. For iTop Incident/UserRequest creation, configure `ITOP_DEFAULT_ORG_ID` and `ITOP_DEFAULT_CALLER_ID`.

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

`POST /api/tickets/{ticket_id}/attachments`

Stores attachment metadata only. Binary storage should be external.

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

- Claude Code availability
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
{"approved_by": "operator"}
```

`POST /api/changes/{change_id}/reject`

```json
{"rejected_by": "operator", "reason": "Insufficient evidence"}
```

`POST /api/changes/{change_id}/complete`

```json
{"result": "URL block applied in test environment."}
```

## Learning

Postmortems:

- `GET /api/postmortems`
- `GET /api/postmortems/{id}`
- `POST /api/postmortems`
- `PUT /api/postmortems/{id}`
- `POST /api/postmortems/{id}/review`

Workflows:

- `GET /api/workflows`
- `GET /api/workflows/{id}`
- `POST /api/workflows`
- `PUT /api/workflows/{id}`
- `POST /api/workflows/{id}/review`
- `POST /api/workflows/{id}/runs`
- `POST /api/workflows/runs/{run_id}/complete`

Service desk intake:

- `GET /api/intake/raci`
- `POST /api/intake/classify`
- `POST /api/intake/submit`
- `GET /api/intake/sessions`

CI/CD security:

- `GET /api/cicd/gitlab/template`
- `GET /api/cicd/runs`
- `GET /api/cicd/runs/{run_id}`
- `POST /api/cicd/runs`

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

Overview counts, trends, activity, pending changes.

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

Merges `audit_log` and `event_log`.

## Tools

- `GET /api/tools`
- `GET /api/tools/status`
- `GET /api/tools/{id}`
- `GET /api/tools/{id}/history`
- `POST /api/tools/{id}/check`
- `POST /api/tools/check-all`
