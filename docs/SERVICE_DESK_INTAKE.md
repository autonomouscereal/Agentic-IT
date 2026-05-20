# Service Desk Intake And RACI Routing

Last updated: 2026-05-20.

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

Ops Chat is different from the dashboard Intake form. Ops Chat uses the real
agent harness to decide whether a message is general chat or traceable
operational work, then to select ticket class, priority, and assignment group.
That chat intake decision is not allowed to approve risky action or grant
access. The service-desk/RACI tables still define organization queues, access
request owners, and optional auto-assignment policy, while approval gates are
created only by downstream workflow, vault lease, provider permission, or
change-policy barriers.

The distinction matters for demos and for production hardening:

- The dashboard Intake form can still use deterministic RACI preview/submit
  behavior because the operator is intentionally creating a structured ticket.
- Ops Chat should feel like Teams/Slack-style help. The Matrix bridge sends the
  message to the configured Hermes/Claude harness, and the chat agent either
  answers directly, asks one focused clarification, or calls
  `ops_chat_tool.py create-ticket`.
- The app may enforce safety and recover side effects, but it should not become
  a custom parser that decides the user's intent before the agent sees it.
- General harmless requests do not need a ticket. Operational work must become
  traceable once enough context exists.
- Once a ticket exists, follow-up chat becomes `user-response` notes and is
  delivered into the active ticket agent's steering inbox.

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

If the request changes scope after creation, agents and operators should update
the existing ticket instead of making a second ticket:

```bash
curl -sS -X POST http://localhost:25480/api/tickets/<ticket_id>/assignment \
  -H "Content-Type: application/json" \
  -d '{
    "assignee_team": "Tier 2 Endpoint Support",
    "owning_group": "Endpoint Support",
    "assignee": "endpoint.tier2.demo",
    "escalation_tier": "Tier 2",
    "priority": "P2",
    "reason": "Requester clarified that endpoint packaging is required."
  }'
```

Expected evidence: the canonical assignment fields update, a
`ticket-assignment` note records the old/new values, and audit event
`ticket_assignment_updated` is written. Provider-side assignment sync is
adapter-specific; the dashboard assignment and note are canonical.

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

For Ops Chat deployment, browser proof, and the current demo-readiness
checkpoint, see `docs/OPS_CHAT_AGENTIC_UI_TESTING_AND_DEMO_READINESS.md`.

For permission-wall access escalation and resume behavior, run:

```bash
python3 scripts/smoke_access_request_control_plane.py http://localhost:25480
python3 scripts/agentic_access_request_resume_demo.py http://localhost:25480 qwen/qwen3.6-27b
```
