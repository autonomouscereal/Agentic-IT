# Service Desk Intake And RACI Routing

The dashboard now includes a provider-agnostic intake surface for users who do
not know whether they need an incident, service request, change, or workflow.
It classifies plain language, correlates related context, and creates a complete
canonical ticket for the next agent or human.

## What It Does

- Classifies the ask with seeded RACI rules.
- Selects ticket class, priority, and assignment group.
- Adds responsible/accountable/consulted/informed context.
- Searches existing tickets and knowledge articles for context.
- Stores attachment metadata.
- Creates a change request automatically when the route requires approval.
- Can stay local-only or sync through the active provider adapter.

The seeded groups and rules are examples. In a deployment, replace or extend
them with ServiceNow groups, iTop teams, Jira components, Keycloak groups, or
customer-specific RACI data.

## API

- `GET /api/intake/raci`
- `POST /api/intake/classify`
- `POST /api/intake/submit`
- `GET /api/intake/sessions`

Example:

```bash
curl -sS -X POST http://localhost:25480/api/intake/submit \
  -H "Content-Type: application/json" \
  -d '{
    "requester_name": "Demo User",
    "requester_email": "demo@example.local",
    "title": "Suspicious email",
    "message": "User reported a phishing email with a bad link.",
    "attachments": [{"filename": "reported-message.eml"}],
    "sync_provider": false
  }'
```

## Dashboard

Open `Intake` in the sidebar. Use `Classify` to preview routing or `Create
Ticket` to create the canonical ticket. `Create + Sync Provider` is available
for deployments where provider credentials and adapters are configured.

## Test

```bash
python3 scripts/smoke_service_desk_intake.py http://localhost:25480
```

Expected: the phishing fixture creates an Incident, an internal classification
note, attachment metadata, an intake session, and a pending approval gate.
