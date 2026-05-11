# Ticket Provider Adapter Guide

Last updated: 2026-05-11.

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
- supports guarded outbound create
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

- `provider`
- `provider_ref`
- `provider_class`
- `provider_sync_status`
- `provider_last_error` on failure
- `provider_payload` with raw result/context when useful
- `synced_at` when sync succeeds

If the provider has a direct browser URL, set `provider_url`. If not, `ticket_links.external_ticket_url()` may generate provider-specific links for supported providers.

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
  "dry_run": false
}
```

Expected response fields are flexible. The adapter prefers `provider_ref`, then `id`, then `key`; `provider_url` is optional.

## Outbound Create Policy

Provider outbound create must fail closed:

- If required provider defaults are missing, return `{"error": "..."}`
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
