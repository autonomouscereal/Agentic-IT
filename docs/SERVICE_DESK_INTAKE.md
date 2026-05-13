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
- Can auto-assign an agent when the matching RACI rule explicitly enables it.
- Automatically syncs through the active provider adapter when one is
  configured; otherwise it falls back to local-only tickets.
- Supports CRUD for RACI groups and rules.
- Can suggest concise clarifying questions before ticket creation.

The seeded groups and rules are examples. In a deployment, replace or extend
them with ServiceNow groups, iTop teams, Jira components, Keycloak groups, or
customer-specific RACI data.

Auto-agent assignment is a RACI rule setting, not a hardcoded phishing shortcut:

- `auto_assign_agent`: enables automatic agent spawn for matching tickets.
- `auto_agent_model`: model to use for that assignment.
- `auto_agent_prompt`: extra instruction appended to the standard fast ticket
  resolution prompt.

The seeded phishing rule auto-assigns Security Operations phishing incidents.
Most other seeded rules stay manual until an operator enables them.

Access request routes are seeded for common permission walls:

- `GitLab repository access`: repository/project role requests route to
  DevSecOps, consult Identity & Access and Compliance, and require owner
  approval before membership changes.
- `SIEM analyst access`: Wazuh/SIEM read-role or alert-index access routes to
  Identity & Access, consults Security Operations and Compliance, and requires
  approval before access is granted.

Agents should use `POST /api/tickets/{ticket_id}/access-request` when they hit
an access denied condition during another ticket. That creates the child access
ticket and the approval gate that resumes the original work after approval.

## API

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

Example:

```bash
curl -sS -X POST http://localhost:25480/api/intake/submit \
  -H "Content-Type: application/json" \
  -d '{
    "requester_name": "Demo User",
    "requester_email": "demo@example.local",
    "title": "Suspicious email",
    "message": "User reported a phishing email with a bad link.",
    "attachments": [{"filename": "reported-message.eml"}]
  }'
```

The API chooses the active external provider automatically when configured. If
no provider is ready, the ticket remains local with `provider_sync_status` set
to `local_only`.

Clarifying questions:

```bash
curl -sS -X POST http://localhost:25480/api/intake/clarify \
  -H "Content-Type: application/json" \
  -d '{"title":"Suspicious email","message":"A user saw a weird email."}'
```

## Dashboard

Open `Intake` in the sidebar. Use `Preview` to see routing and clarifying
questions, or `Create Ticket` to classify, create locally, and sync the provider
when possible. Use the RACI actions on the same page to add, edit, or disable
groups and routing rules.

## Test

```bash
python3 scripts/smoke_service_desk_intake.py http://localhost:25480
```

Expected: the phishing fixture creates an Incident, an internal classification
note, attachment metadata, an intake session, and a pending approval gate. The
smoke fixture disables auto-assignment for the created ticket to avoid spending
model time, but still verifies that the phishing RACI rule advertises
`auto_assign_agent=true`.

For post-creation clarification and resume behavior, see
`docs/USER_RESPONSE_WORKFLOW.md`.

For permission-wall access escalation and resume behavior, run:

```bash
python3 scripts/smoke_access_request_control_plane.py http://localhost:25480
python3 scripts/agentic_access_request_resume_demo.py http://localhost:25480 qwen/qwen3.6-27b
```
