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

## Adding ServiceNow

Recommended shape:

1. Create `api/services/servicenow_sync.py`.
2. Implement `TicketProvider`.
3. Read config from env only:
   - `SERVICENOW_INSTANCE_URL`
   - `SERVICENOW_USER`
   - `SERVICENOW_PASSWORD` or token reference from env
4. Add provider to `provider_registry.py`.
5. Map incidents/requests/changes to canonical fields.
6. Store raw provider payload in `provider_payload`.
7. Add docs and a smoke test using mocked/local-safe calls first.

Do not change the frontend to become ServiceNow-aware. The frontend should continue using canonical APIs.

## Adding Jira

Recommended shape:

1. Create `api/services/jira_sync.py`.
2. Implement `TicketProvider`.
3. Map project/issue type/status/priority/assignee to canonical ticket fields.
4. Store `provider_url` as the issue browse URL.
5. Use dashboard notes for agent notes, then optionally push comments to Jira through adapter update methods.

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
```

It creates a local ticket with `sync_provider=true`, then pushes it through `/api/tickets/{id}/push-provider`, expecting `local_only`.

