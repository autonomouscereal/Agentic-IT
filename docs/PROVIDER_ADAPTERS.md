# Ticket Provider Adapter Guide

Last updated: 2026-05-20.

## Goal

The dashboard must work with iTop now and ServiceNow/Jira/other ticket systems later. Provider-specific code belongs behind a small adapter boundary so the frontend, agent prompts, and canonical ticket context stay stable.

## Current Providers

`local`

- always available
- no external system
- used for tests, demos, and local-only tasks
- returns `local_only` for outbound create/push

`itop`

- current lab provider
- supports inbound discovery/full sync
- supports single ticket sync
- supports guarded outbound create for `Incident`, `UserRequest`, and concrete Change classes
- resolves `Organization`, `Person` caller, and optional team defaults from iTop when `ITOP_DEFAULT_ORG_ID` / `ITOP_DEFAULT_CALLER_ID` are unset
- maps dashboard priority to iTop `Incident` `impact`/`urgency`
- supports basic update/close methods already present in adapter

`servicenow`

- env-driven outbound create adapter
- supports incidents, requests, and changes through ServiceNow table API
- fails closed with a clear `not configured` error until `SERVICENOW_INSTANCE_URL` and an auth method are provided
- sets `provider_ref`, `provider_class`, `provider_url`, `provider_payload`, and `provider_sync_status=synced` after a successful provider response

`jira`

- env-driven outbound create adapter for Jira Cloud REST API v3
- requires `JIRA_BASE_URL`, `JIRA_EMAIL`, `JIRA_API_TOKEN`, and `JIRA_PROJECT_KEY`
- fails closed when unset
- stores the Jira issue key as `provider_ref` and the browse URL as `provider_url`

`generic-webhook`

- env-driven outbound webhook adapter for products that can receive a normalized JSON ticket payload
- requires `GENERIC_TICKETING_WEBHOOK_URL`
- optional `GENERIC_TICKETING_WEBHOOK_TOKEN` is sent as `X-Webhook-Token`
- useful for early integrations with Jira Service Management, custom portals, SOAR tools, or a customer's middleware before a dedicated adapter exists

## Provider Interface

File:

```text
api/services/ticket_provider.py
```

Methods:

- `connect()`
- `is_connected()`
- `discover_new()`
- `sync_ticket(ticket_class, ticket_key)`
- `create_ticket(ticket_id, fields)`
- `full_sync()`
- `get_ticket(ticket_id)`
- `update_ticket(ticket_id, fields)`
- `close_ticket(ticket_id, notes)`
- `sync_loop(broadcast_fn=None)`

## Registry

File:

```text
api/services/provider_registry.py
```

The registry exposes:

- `list_providers()`
- `get_provider(name)`
- `sync_ticket(provider_name, ticket_class, ticket_ref)`
- `create_ticket(provider_name, ticket_id, fields)`
- `full_sync(provider_name)`

Routes should call the registry or `ticket_service`, not provider-specific modules.

## Canonical Ticket Requirements

A provider adapter should always populate:

- `opened_by_name` / `opened_by_email` when work was opened by an agent,
  operator, chat bridge, or automation on behalf of a user
- `requester_name` / `requester_email` for the person asking for the work
- `affected_user_name` / `affected_user_email` for the impacted user, account,
  mailbox, device, service, or app
- `provider`
- `provider_ref`
- `provider_class`
- `provider_sync_status`
- `provider_last_error` on failure
- `provider_payload` with raw result/context when useful
- `synced_at` when sync succeeds

If the provider has a direct browser URL, set `provider_url`. If not, `ticket_links.external_ticket_url()` may generate provider-specific links for supported providers.

Provider descriptions should preserve the canonical contact block. Use
`Name (email)` formatting instead of angle brackets because several ITSM UIs,
including iTop, treat `<...>` as HTML and may strip the affected-user line.
Never invent email addresses for affected users; blank is better than wrong.

## Ops Chat Ticket Sync

Ops Chat-created tickets are canonical dashboard tickets and should follow the
same provider contract as tickets created from the dashboard UI or API. In the
current lab, the active provider is iTop, so a healthy chat-created ticket
should show:

- `provider=itop`
- a numeric `provider_ref` / `itop_ref`
- `provider_sync_status=synced`
- a usable `external_url` to the iTop ticket
- preserved Ops Chat evidence and recent chat context in the dashboard ticket

Provider sync must not erase the richer local Ops Chat record. When iTop or
another provider returns a shorter description, generic team, or partial payload,
keep the dashboard's full chat context, agent-created note, requester follow-up,
and agent-selected assignment as the canonical evidence trail.

Ops Chat `create-ticket` and `continue-ticket` can set or correct requester and
affected-user metadata. A follow-up such as "actually this is for Bob, not
Alice" should update the existing ticket through `/api/tickets/{id}/contacts`
and a `ticket-contact` note, not create a duplicate ticket.

Use `POST /api/tickets/{id}/assignment` when the agent or operator learns that
the scope belongs to another group or tier. Provider-side assignment push is
adapter-specific, but the canonical dashboard assignment and
`ticket-assignment` note are always written.

## Configuring ServiceNow

Environment:

```text
SERVICENOW_INSTANCE_URL=https://example.service-now.com
SERVICENOW_TOKEN=<from vault>
SERVICENOW_USER=
SERVICENOW_PASSWORD=<from vault, only if token is not used>
SERVICENOW_ASSIGNMENT_GROUP=<optional sys_id/name accepted by customer instance>
SERVICENOW_REQUEST_TABLE=sc_request
```

Do not change the frontend to become ServiceNow-aware. The frontend should continue using canonical APIs.

## Configuring Jira

Environment:

```text
JIRA_BASE_URL=https://example.atlassian.net
JIRA_EMAIL=<service-account-email>
JIRA_API_TOKEN=<from vault>
JIRA_PROJECT_KEY=SOC
JIRA_ISSUE_TYPE=Task
```

Use dashboard notes for agent notes, then optionally add provider-specific comment push in a dedicated adapter method once the customer's Jira workflow is known.

## Configuring Generic Webhook

Environment:

```text
GENERIC_TICKETING_WEBHOOK_URL=https://customer-middleware.example/tickets
GENERIC_TICKETING_WEBHOOK_TOKEN=<from vault>
GENERIC_TICKETING_DRY_RUN=false
```

Payload shape:

```json
{
  "ticket_id": 123,
  "title": "Suspicious email",
  "description": "...",
  "ticket_class": "Incident",
  "priority": "P2",
  "created_by": "service-desk-intake",
  "contacts": {
    "opened_by_name": "Ops Chat Agent",
    "requester_name": "Demo Account 1 Demo",
    "requester_email": "demo_account_1@example.local",
    "affected_user_name": "Alice Example",
    "affected_user_email": null
  },
  "dry_run": false
}
```

Expected response fields are flexible. The adapter prefers `provider_ref`, then `id`, then `key`; `provider_url` is optional.

## Outbound Create Policy

Provider outbound create must fail closed:

- If required provider ownership/caller/org fields cannot be configured or resolved, return `{"error": "..."}`
- Do not create partial provider tickets without required ownership/caller/org fields.
- Do not claim `synced` unless the provider returned a usable external reference.

The dashboard records failed outbound create attempts as:

```text
provider_sync_status=create_failed
provider_last_error=<reason>
provider_payload=<raw adapter result>
```

## Local Provider Smoke

The smoke test verifies the provider contract without external dependencies:

```bash
python3 scripts/smoke_agentic_system.py http://localhost:25480
python3 scripts/smoke_provider_adapters.py http://localhost:25480
```

It creates a local ticket with `sync_provider=true`, then pushes it through `/api/tickets/{id}/push-provider`, expecting `local_only`.

`smoke_provider_adapters.py` also verifies that ServiceNow and Jira are registered and fail closed when not configured, recording `provider_sync_status=create_failed` and `provider_last_error` on the canonical ticket.

For a live iTop outbound create smoke:

```bash
python3 scripts/smoke_provider_adapters.py http://localhost:25480 --itop-create
```

That optional mode creates one `UserRequest` and one `Incident` through the dashboard provider adapter and requires both to return `provider_sync_status=synced` with numeric iTop refs.

## iTop Outbound Create Defaults

The iTop adapter prefers explicit environment defaults:

```text
ITOP_DEFAULT_ORG_ID=1
ITOP_DEFAULT_CALLER_ID=94
ITOP_SECURITY_TEAM_ID=65
```

When the org/caller defaults are absent, the adapter asks iTop for safe defaults:

- `Organization`: use configured ID, then Organization `1`, then first query result.
- `Person`: use configured ID, then first person in the selected org, then first person.
- `Team`: prefer the canonical dashboard `assignee_team` / `owning_group`.
  If iTop does not already have a matching Team, the adapter creates a reference
  Team in the selected Organization so provider-side tickets do not all appear
  under the legacy Security Team. `ITOP_SECURITY_TEAM_ID` remains a fallback
  only when no assignment group is supplied or iTop cannot create/resolve the
  group-specific Team.

`Incident` creates include `org_id`, `caller_id`, optional `team_id`, and mapped `impact`/`urgency`. `UserRequest` creates include `org_id`, `caller_id`, and optional `team_id`. If those defaults cannot be resolved from iTop, the canonical ticket records `create_failed`; otherwise demos should show `synced`, not an avoidable provider-create failure.

When requester metadata matches an iTop `Person` by email or name, the adapter
uses that person as the native `caller_id`. If no exact match exists, it uses
the configured/default caller and still writes requester and affected-user
metadata into the provider description so the iTop UI can show who requested
the work and who is impacted.
