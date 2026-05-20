---
name: ticket-provider-adapters
description: Manage and test provider-agnostic ticketing adapters for the agentic IT/SOC platform, including local tickets, iTop, ServiceNow, Jira, and generic webhook bridges. Use when configuring external ITSM providers, validating fail-closed provider sync, pushing dashboard tickets to ticketing systems, or documenting ticket provider integration behavior.
---

# Ticket Provider Adapters

Use the dashboard API as the canonical contract. Do not make agents call ServiceNow, Jira, iTop, or local ticket tables directly unless a provider-specific skill explicitly requires it.

## Quick Checks

```bash
python3 scripts/platform_doctor.py --base http://localhost:25480
python3 scripts/smoke_provider_adapters.py http://localhost:25480
curl -sS http://localhost:25480/api/providers
```

Expected providers:

- `local`
- `itop`
- `servicenow`
- `jira`
- `generic-webhook`

## Provider Rules

- Keep `local` always available for isolated demos and tests.
- Keep iTop as the current reference ITSM, but treat it as one provider behind the canonical contract.
- Ops Chat-created tickets should use the active provider by default. In the
  current lab that means iTop, and a healthy chat-created ticket should have
  `provider=itop`, a provider reference, `provider_sync_status=synced`, and a
  usable provider URL.
- Provider sync must not overwrite richer local evidence from Ops Chat. Keep
  recent chat context, agent-selected assignment, and human-readable Ops Chat
  notes even if the provider returns a short summary or generic assignment.
- Configure ServiceNow/Jira/webhook only through environment variables or vault-injected env. Never hardcode API tokens, passwords, or instance URLs containing secrets.
- Fail closed when external provider config is missing. The canonical ticket should record `provider_sync_status=create_failed` and `provider_last_error`.
- Do not claim provider sync succeeded unless the provider returns a usable external reference.
- Store provider browser links in `provider_url` when available.

## Outbound Create

Create a canonical ticket:

```bash
curl -sS -X POST "$SOC_DASHBOARD_URL/api/tickets" \
  -H "Content-Type: application/json" \
  -d '{"title":"Adapter test","description":"safe test","ticket_class":"Incident","provider":"local"}'
```

Push to a provider:

```bash
curl -sS -X POST "$SOC_DASHBOARD_URL/api/tickets/123/push-provider" \
  -H "Content-Type: application/json" \
  -d '{"provider":"servicenow"}'
```

## Config Knobs

ServiceNow:

```text
SERVICENOW_INSTANCE_URL
SERVICENOW_TOKEN
SERVICENOW_USER
SERVICENOW_PASSWORD
SERVICENOW_ASSIGNMENT_GROUP
SERVICENOW_REQUEST_TABLE
```

Jira:

```text
JIRA_BASE_URL
JIRA_EMAIL
JIRA_API_TOKEN
JIRA_PROJECT_KEY
JIRA_ISSUE_TYPE
```

Generic webhook:

```text
GENERIC_TICKETING_WEBHOOK_URL
GENERIC_TICKETING_WEBHOOK_TOKEN
GENERIC_TICKETING_DRY_RUN
```

## Files

- `api/services/provider_registry.py`: provider registration and dispatch.
- `api/services/external_ticket_adapters.py`: ServiceNow, Jira, and generic webhook adapters.
- `api/services/ticket_service.py`: canonical ticket create/push/update persistence.
- `docs/PROVIDER_ADAPTERS.md`: detailed integration guide.
- `docs/OPS_CHAT_AGENTIC_UI_TESTING_AND_DEMO_READINESS.md`: current Ops Chat
  provider-sync and demo-readiness checkpoint.
- `scripts/smoke_provider_adapters.py`: safe live smoke test.
