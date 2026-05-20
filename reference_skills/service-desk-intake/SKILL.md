---
name: service-desk-intake
description: >
  Provider-agnostic request intake and RACI routing workflow. Turns a
  plain-language user ask into a correctly classified incident, request, or
  change with assignment group, RACI context, related tickets, knowledge
  references, attachment metadata, and approval gates.
---

# Request Intake And RACI Routing

Use this skill when a user asks the platform to create or route enterprise work
from plain language. The request may be service desk, IAM, DevOps, SOC,
infrastructure, compliance, or business operations work. The goal is to make
intake easy for the requester while giving the next agent or human a complete,
routed work item.

## Flow

1. Gather requester name/email, title, message, and optional attachment metadata.
2. Classify with `POST /api/intake/classify`.
3. Review assignment group, ticket class, priority, RACI, approval requirement,
   related tickets, and knowledge articles.
4. Submit with `POST /api/intake/submit`.
5. If the response has `change_id`, wait for approval before any environment
   changing work.
6. Assignment is policy-driven. If the matching RACI rule has
   `auto_assign_agent=true`, the dashboard auto-spawns exactly one agent using
   the configured model/prompt. Otherwise leave it for a human queue or assign
   manually.

## API

Classify:

```bash
curl -sS -X POST "$SOC_DASHBOARD_URL/api/intake/classify" \
  -H "Content-Type: application/json" \
  -d '{"title":"Suspicious email","message":"User reported a phishing email with a bad link."}'
```

Submit:

```bash
curl -sS -X POST "$SOC_DASHBOARD_URL/api/intake/submit" \
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

List RACI:

```bash
curl -sS "$SOC_DASHBOARD_URL/api/intake/raci"
```

RACI rules are CRUD-managed through `/api/intake/raci/rules`. The important
auto-assignment fields are:

- `auto_assign_agent`: enables automatic agent pickup for matching tickets.
- `auto_agent_model`: local/provider model alias to use.
- `auto_agent_prompt`: extra scoped policy prompt appended to the standard
  ticket-resolution prompt.

The dashboard RACI UI exposes these fields so demo/customer routing can choose
which queues are human-owned and which queues are automatically handled.

Access-request RACI is also rule-driven. Rules whose intent starts with
`access-` are used when an agent hits a permission wall and omits an explicit
assignment group. Seeded examples route Mailcow to Email Operations, Wazuh/SIEM
to Security Operations, GitLab to DevSecOps, Keycloak/IAM to Identity & Access,
iTop to Business Applications, the Agentic Operations platform to Platform
Operations, and network controls to Network Operations.

When an agent hits a permission wall while working a different ticket, use the
access-request path instead of a generic note:

```bash
curl -sS -X POST "$SOC_DASHBOARD_URL/api/tickets/$TICKET_ID/access-request" \
  -H "Content-Type: application/json" \
  -d '{"agent_id":123,"resource":"GitLab project demo/private-infra","permission":"Developer repository read access","assignment_group":"DevSecOps","reason":"Repository API returned 403; least-privilege access is required."}'
```

This creates a child access ticket, approval gate, and resume hook for the
original ticket. Seeded examples include `GitLab repository access` and
`SIEM analyst access`.

## Default RACI Groups

The fresh install seeds ten sample groups:

- Security Operations
- Identity & Access
- Infrastructure Operations
- Network Operations
- Endpoint Support
- Email Operations
- DevSecOps
- Business Applications
- Compliance & Audit
- Change Advisory Board

These are samples, not a hardcoded product boundary. Replace or extend them for
the customer's organization, ServiceNow groups, Jira components, iTop teams, or
Keycloak roles.

## Demo Routing Notes

The Ops Chat demo uses RACI as the source of truth for intake routing. Current
high-signal examples:

- Account lockout or MFA help routes to `Identity & Access`.
- Software install requests route to `Endpoint Support`.
- VPN tunnel failures such as "VPN stopped connecting after reboot" route to
  `Network Operations` through intent `vpn-connectivity`.
- Repository, pipeline, and delivery-gate requests route to `DevSecOps`.
- Phishing and EDR/security alerts route to `Security Operations` and open
  approval gates before mailbox, SIEM, containment, URL block, or endpoint
  response work.

When a message mixes concepts, prefer the operational blocker. For example,
"I cannot reach the finance file share because VPN stopped connecting" should
start as `vpn-connectivity` / `Network Operations`, not as an entitlement
request, unless the user clarifies that VPN works and the share permission
itself is missing.

## Guardrails

- Do not ask the requester to gather logs manually unless policy requires it.
- Put missing technical detail into the ticket as a follow-up question or agent
  investigation task.
- Use approval gates for access grants, mailbox remediation, endpoint isolation,
  restarts, firewall, DNS, routing, and production deployments.
- Store attachment metadata and evidence references, not raw secrets.
- Keep product-specific routing inside provider adapters.

## Test

```bash
python scripts/smoke_service_desk_intake.py http://localhost:25480
```

Access routing smoke:

```bash
python scripts/smoke_access_raci_routing.py http://localhost:25480
```

Expected result: a phishing intake is classified as an Incident, routed to
Security Operations, linked to a change approval gate, and visible in ticket
context with notes and attachment metadata.

Latest Ops Chat routing proof, 2026-05-20:

- Ticket `781`: VPN report classified as `vpn-connectivity` and routed to
  `Network Operations`.
- Ticket `772`: software request collected workstation, standard OBS Studio,
  and training date through a chat follow-up, then continuation agent `291`
  completed routing to Endpoint Support.
- Ticket `784`: phishing/EDR request opened approval gate `223`, bound that
  gate to agent `293`, and approval spawned continuation agent `294`.
