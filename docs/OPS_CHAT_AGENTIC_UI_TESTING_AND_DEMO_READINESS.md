# Ops Chat Agentic UI Testing And Demo Readiness

Last updated: 2026-05-21.

This document is the checkpoint for the current Ops Chat workstream: Element
UI, Matrix/Synapse, Keycloak login, chat-to-agent routing, ticket sync,
reassignment/escalation, and user-facing ticket updates. It exists so future
agents do not have to reconstruct the intended behavior from old smoke runs.

## Product Goal

Ops Chat is the human front door for Agentic Operations. It should feel like a
normal enterprise chat client while routing real operational work into the
governed control plane.

The user experience should be:

1. User opens Element.
2. User signs in through Keycloak.
3. User messages `Agentic Ops Agent`.
4. The chat agent answers harmless/general questions directly.
5. If the request needs tracking, the chat agent creates a new ticket or
   continues/cancels a specific existing ticket.
6. The ticket syncs to the active ticket provider, iTop in the lab.
7. A real Hermes/Claude ticket agent works the ticket when appropriate.
8. If the ticket agent needs more information, it asks through the ticket and
   the bridge posts the question back into the Matrix room.
9. The user's chat reply becomes a `user-response` ticket note.
10. If scope changes, the ticket can be reassigned or escalated without making
    a duplicate.
11. Risky work is blocked by real platform barriers: approval gates, access
    requests, provider permissions, credential leases, and workflow policy.

The user should not need to know iTop, Wazuh, Mailcow, GitLab, Keycloak,
Semgrep, or the dashboard API. They should just ask for help.

## Architecture

Reference services:

| Layer | Service | Purpose |
| --- | --- | --- |
| Browser chat client | `ops-chat` | Element Web UI on `https://<host>:3303` |
| Chat server | `ops-chat-synapse` | Matrix homeserver and OIDC login callbacks |
| Chat DB | `ops-chat-db` | PostgreSQL for Synapse only |
| Identity | Keycloak | OIDC provider for Element/Synapse |
| Bridge | `ops-chat-bridge` | Matrix appservice that forwards room events to dashboard |
| Control plane | `api` | `/api/ops-chat/message`, tickets, notes, agents, audit |
| Model gateway | `ai-proxy` | Local/on-prem/cloud model route abstraction on `4001` |
| Harness | Hermes or Claude Code | Real agent turn for chat intake and ticket execution |

Important URL contract:

- Dashboard UI: `https://192.168.50.222:25443`
- Element/Ops Chat UI: `https://192.168.50.222:3303`
- Same-origin Matrix client API through Element: `https://192.168.50.222:3303/_matrix/client/versions`
- Optional direct Synapse diagnostics: `https://192.168.50.222:3302`
- Dashboard internal API on AI server: `http://127.0.0.1:25480`
- AI proxy on AI server/LAN: `http://127.0.0.1:4001` and `http://192.168.50.222:4001`

Do not use `http://192.168.50.222:3301` for the demo except as a redirect
compatibility check. The real browser path is `https://192.168.50.222:3303`.

## Decision Contract

The chat endpoint is agent-first, not parser-first.

The dashboard gives the configured Hermes/Claude harness a small
`ops_chat_tool.py` toolbelt. The harness must finish with one final tool:

- `answer` for harmless/general chat
- optional `web-search`, then `answer`, for benign current-information
  questions
- `create-ticket` for tracked operational work
- `continue-ticket` for updates, requester replies, cancellations, or scope
  changes that clearly belong to one of the recent tickets in the room
- `validate-artifact` for one-off developer artifacts such as Python scripts,
  HTML snippets, Markdown runbooks, Bash scripts, JavaScript, JSON, or YAML

The application may recover side effects and enforce safety, but it should not
replace the agent's decision with a brittle custom JSON classifier.

Important room behavior:

- A Matrix room is a conversation, not a ticket container. One room can contain
  harmless chat, several tickets, cancellations, and replacement requests.
- The dashboard records recent linked tickets and passes them to the harness as
  context. The harness must decide per message whether to answer, create, or
  continue.
- Cancellation-like `continue-ticket` updates mark the selected ticket
  `cancelled`, record the requester note, and stop that ticket's active agent
  if one is present.
- The Matrix bridge sets typing state while the harness is working and sends a
  delayed "working on that" acknowledgement when the turn takes more than a few
  seconds, because Element may not visibly render typing in every browser state.

Allowed pre-ticket clarification:

- The chat agent may ask one concise follow-up before ticket creation when the
  answer materially changes routing, scope, urgency, or whether a ticket is
  needed.
- Once the ticket is created, recent chat context is copied into the ticket
  description and the Ops Chat-created ticket note.
- The agent should not ask the user to gather logs unless a policy/workflow
  requires it.
- One-off developer artifact requests should stay in chat unless the user asks
  to deploy, modify a real repo/system, or track the work. The chat harness must
  write the artifact in its work directory, run `ops_chat_tool.py
  validate-artifact`, and return the validated fenced code. The Matrix bridge
  renders fenced code as safe Matrix `formatted_body` HTML so Element shows
  readable code blocks without executing user-provided HTML.

No-ticket examples:

- "hey"
- "send me a text picture of a cat"
- "make that cat sleepier"
- "what is a rough current house price in Reno?"
- "who normally owns software purchasing?"

Ticket examples:

- account lockout, MFA, password, SSO, Keycloak
- VPN, DNS, proxy, firewall, site reachability
- software install/update on a workstation
- suspicious email, phishing, endpoint/EDR alert
- GitLab runner or CI/CD gate failure
- broken dashboard/workflow/setup module
- access request, permission denial, mailbox/shared mailbox issue

## Safety Contract

The chat agent can decide routing. It is not an approval authority.

The chat agent must not:

- grant access
- approve deployment
- approve quarantine/containment
- waive policy
- browse or curl suspicious URLs
- expose secrets, tokens, raw stack traces, or hidden prompts

Risk decisions happen later when the ticket agent hits a real barrier:

- `POST /api/tickets/{id}/access-request`
- `POST /api/changes`
- provider `403` / denied lease / missing role
- workflow policy gates
- scoped credential-vault lease checks

## Ticket Sync Contract

Ops Chat-created tickets should use the active ticket provider by default. In
the lab, that means iTop.

Required evidence on a healthy chat-created ticket:

- canonical dashboard ticket id
- `provider = itop`
- `provider_ref` / `itop_ref`
- `provider_sync_status = synced`
- `external_url` pointing to iTop details
- Ops Chat agent-created note
- recent chat context preserved in dashboard evidence

The iTop sync path must not overwrite richer local Ops Chat evidence with short
provider summaries. For Ops Chat-originated tickets, local description and
agent-selected assignment should be preserved when iTop returns a shorter
description or a generic default team.

## Reassignment And Escalation

Scope changes should update the existing ticket, not create duplicates.

Endpoint:

```bash
POST /api/tickets/{ticket_id}/assignment
```

Example:

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

Expected:

- `tickets.assignee_team` updates
- `tickets.owning_group` updates
- optional `tickets.assignee` updates
- optional `tickets.priority` updates
- a `ticket-assignment` note records the old/new fields and escalation tier
- audit event `ticket_assignment_updated` is written

Provider-side assignment sync is adapter-specific. The canonical dashboard
assignment and evidence note are always authoritative.

## Browser Demo Path

Fast path:

1. Open `https://192.168.50.222:3303/#/user/@agentic-ops:agentic-ops.local`.
2. Sign in with Keycloak.
3. Dismiss Element first-login prompts if they appear:
   - service worker warning
   - notification prompt
   - device verification prompt
   - "start chat with this new contact" confirmation
4. Confirm the profile says `Agentic Ops Agent`.
5. Click **Send message**.
6. Send a request.
7. Open the dashboard ticket from the bot response.

Avoid **Explore Public Rooms** during the demo. That is generic Matrix UI, not
the support-agent path.

## Current Live Proofs

Latest validated state on 2026-05-20:

| Proof | Evidence |
| --- | --- |
| Live health | dashboard `/health` ok; Ops Chat health ok; tools `18 healthy / 0 down`; active agents `0` after cleanup |
| Clarification before ticket | ambiguous software request asked a follow-up first |
| Ticket after clarification | ticket `1176` created after user clarified OBS Studio need |
| Provider sync | ticket `1176` synced to iTop ref `595` |
| Context preservation | ticket `1176` preserved both ambiguous and clarified chat context |
| Reassignment/escalation | ticket `1176` reassigned to `Tier 2 Endpoint Support`, owning group `Endpoint Support`, priority `P2`, with escalation note |
| Element browser send | Playwright marker `ops-chat-playwright-1779301274503` created ticket `1177` from Element UI |
| Real agent account case | marker `ops-chat-scenarios-1779301430`, ticket `1185`, Hermes agent `326`, user-facing login next-step note |
| Real agent software case | marker `ops-chat-scenarios-1779301734`, ticket `1191`, Hermes agent `327`, minimum-details note |
| No-spawn broad smoke | marker `ops-chat-scenarios-1779302571`, tickets `1192`-`1196`, general chat, web lookup, cat memory, account, software, VPN, phishing, CI/CD |
| Browser UI retest | marker `ops-chat-ui-exec-1779283445`, ticket `1197`, iTop ref `616`, outbound Matrix question delivered, chat reply recorded as ticket note |
| Broad enterprise retest | marker `ops-chat-enterprise-matrix-1779305167`, tickets `1198`-`1248`, 50/50 passed, global search found marker |
| Real agent prompt guard | marker `ops-chat-scenarios-1779307368`, ticket `1255`, Hermes agent `333`, spawned prompt included canonical-ticket no-duplicate guardrail |
| One-room Element marathon | marker `ops-chat-marathon-1779299559`, user `demo_chat_marathon5`, 16 mixed turns, tickets `1276`-`1280`, 15 working acks, passed |
| Developer artifact chat | marker `ops-chat-dev-artifact-1780000005`, user `demo_chat_marathon5`, Python/HTML/Markdown/Bash validated and rendered as Element code blocks with zero tickets |

Smoke-owned agents `327` and `328` were stopped after collecting evidence so
the demo queue was left clean. Final active-agent and process checks were
empty.

Additional smoke-owned agents `330`, `331`, `332`, and `333` were stopped after
collecting evidence during the later UI retest. Active agents ended at `0`.

Latest one-room Element marathon:

- Ran through the real Element UI and Keycloak as `demo_chat_marathon5`.
- Used one Matrix DM with `@agentic-ops:agentic-ops.local` for harmless chat,
  current-info questions, multiple operational tickets, cancellations,
  replacement work, scope updates, and a room-scoped ticket summary.
- Marker `ops-chat-marathon-1779299559` passed with 16 chat turns and 15 visible
  working acknowledgements.
- Created Figma install ticket `1276`, synced to iTop ref `695`, then cancelled
  it when the requester said Jeff already had Figma.
- Created urgent GitLab/account ticket `1277`, synced to iTop ref `696`, routed
  to `Identity & Access`, priority `P1`, and spawned real agent `350`.
- Created mailbox-check ticket `1278`, synced to iTop ref `697`, routed to
  `Email Operations`, and spawned real agent `351`.
- Created Adobe Acrobat Pro replacement ticket `1279`, synced to iTop ref
  `698`, routed to `Procurement & Vendor Management`, and spawned real agent
  `352`. This intentionally proved replacement work did not reuse cancelled
  ticket `1276`.
- Created VPN ticket `1280`, synced to iTop ref `699`, routed to `Network
  Operations`, then cancelled it when the requester clarified they were on guest
  Wi-Fi.
- Backend verification after the run showed ticket `1276` and `1280` cancelled,
  tickets `1277`-`1279` in progress, all five tickets provider-synced to iTop,
  and no active agents/processes after stopping only the smoke-owned agents
  `346`, `348`, `350`, `351`, and `352`.

Rerun findings:

- Element may show digital-identity verification/reset prompts on first login.
  The Playwright smoke now handles the demo-account reset path explicitly with
  `OPS_CHAT_ALLOW_IDENTITY_RESET=true`, then confirms the real Matrix path.
- The account-lockout real-agent rerun exposed a duplicate-ticket risk in the
  ticket-agent prompt. Both chat-agent spawn paths now tell the agent that the
  existing ticket is canonical and that child work must use explicit
  access/change/setup/follow-up endpoints only.
- The VPN real-agent case correctly asked a pre-ticket clarification. That is
  expected behavior when the missing answer changes route/scope/urgency.
- The marathon exposed two chat-intake reliability bugs. First, a long general
  chat history could make the harness miss the required final tool call on a
  later operational turn; retries now use a compact tool-decision prompt.
  Second, model text that merely claimed an old ticket id could resurrect a
  cancelled ticket during side-effect recovery; recovery now trusts a ticket id
  only when the user's current message explicitly referenced that ticket.
- Developer artifact testing exposed the same class of issue for code: the
  harness could claim it had validated a script while using the general answer
  path. Dev artifact asks now require `validate-artifact`; if the harness calls
  `answer` instead, the turn is rejected and retried with an artifact-only
  prompt.

## Required Smoke Commands

Local source checks:

```powershell
python -m py_compile api\routes\ops_chat.py api\routes\tickets.py api\routes\tools.py api\services\agent_runner.py api\services\itop_sync.py
node --check scripts\smoke_ops_chat_playwright.js
node --check scripts\smoke_ops_chat_workspace_marathon.js
node --check scripts\smoke_ops_chat_dev_artifacts.js
python scripts\text_hygiene.py
python -m pytest tests -q
```

Live health:

```bash
cd /home/cereal/SOC_TESTING/soc-dashboard
TOKEN=$(grep -E '^DASHBOARD_SERVICE_TOKEN=' .env | tail -n1 | cut -d= -f2- | sed 's/^"//; s/"$//')
curl -sS -H "X-Dashboard-Service-Token: $TOKEN" http://127.0.0.1:25480/health
curl -sS -H "X-Dashboard-Service-Token: $TOKEN" http://127.0.0.1:25480/api/ops-chat/matrix/health
curl -sS -H "X-Dashboard-Service-Token: $TOKEN" http://127.0.0.1:25480/api/tools/status
curl -sS -H "X-Dashboard-Service-Token: $TOKEN" http://127.0.0.1:25480/api/agents/active
curl -sS -H "X-Dashboard-Service-Token: $TOKEN" http://127.0.0.1:25480/api/agents/processes
```

Live API-level chat matrix:

```bash
export DASHBOARD_SERVICE_TOKEN=<runtime secret>
python3 scripts/smoke_ops_chat_scenarios.py http://127.0.0.1:25480
```

Real agent cases:

```bash
export DASHBOARD_SERVICE_TOKEN=<runtime secret>
python3 scripts/smoke_ops_chat_scenarios.py http://127.0.0.1:25480 --spawn-agent --agent-case account-lockout --agent-timeout 420
python3 scripts/smoke_ops_chat_scenarios.py http://127.0.0.1:25480 --spawn-agent --agent-case software-request --agent-timeout 420
```

Browser proof from a host/container with Playwright:

```bash
DASHBOARD_URL=https://192.168.50.222:25443 \
DASHBOARD_USER=demo_account_1 \
DASHBOARD_PASSWORD=<from vault> \
OPS_CHAT_URL=https://192.168.50.222:3303 \
OPS_CHAT_USER=demo_chat_alice \
OPS_CHAT_PASSWORD=<from vault> \
OPS_CHAT_SEND_MESSAGE=true \
PLAYWRIGHT_IGNORE_HTTPS_ERRORS=true \
OPS_CHAT_ALLOW_IDENTITY_RESET=true \
node scripts/smoke_ops_chat_playwright.js
```

One-room user-experience marathon:

```powershell
$env:OPS_CHAT_URL="https://192.168.50.222:3303"
$env:OPS_CHAT_USER="demo_chat_marathon5"
$env:OPS_CHAT_PASSWORD="<from vault: demo_chat_marathon5>"
$env:PLAYWRIGHT_IGNORE_HTTPS_ERRORS="true"
$env:OPS_CHAT_MARATHON_MARKER="ops-chat-marathon-<unique>"
node scripts\smoke_ops_chat_workspace_marathon.js
```

The marathon should create several provider-synced tickets from the same Matrix
room, cancel the correct old tickets, create distinct replacement tickets,
answer harmless chat without tickets, keep visible working acknowledgements,
and leave no active smoke agents after cleanup.

Developer artifact UI proof:

```powershell
$env:OPS_CHAT_URL="https://192.168.50.222:3303"
$env:OPS_CHAT_USER="demo_chat_marathon5"
$env:OPS_CHAT_PASSWORD="<from vault: demo_chat_marathon5>"
$env:PLAYWRIGHT_IGNORE_HTTPS_ERRORS="true"
$env:OPS_CHAT_DEV_ARTIFACT_MARKER="ops-chat-dev-artifact-<unique>"
node scripts\smoke_ops_chat_dev_artifacts.js
```

The artifact proof must return validated code blocks for Python, HTML,
Markdown, and Bash in the real Element UI. It should not create tickets unless
the user asks for tracked operational work.

## Broad UI Use-Case Matrix

The next phase should run these through the real Element UI where practical.
For live demo safety, keep destructive actions behind gates and prefer
synthetic/lab targets.

General no-ticket requests:

- greeting
- cat text picture
- cat follow-up with memory
- current price / market question
- "who owns software purchasing?"
- "summarize what this platform can do"
- "what is the difference between phishing and spam?"
- "write a short status note I can send my manager"

Service desk:

- account lockout
- password reset
- MFA device changed
- Keycloak cannot log in
- GitLab cannot log in
- Wazuh dashboard cannot log in
- software install request
- software update request
- workstation slow
- printer issue
- laptop Wi-Fi issue

IAM/access:

- request GitLab project access
- request Mailcow shared mailbox access
- request Wazuh/SIEM read access
- request iTop admin access
- offboard user
- onboard contractor
- privileged access review

Network:

- VPN broken
- site unreachable
- DNS issue
- proxy block
- firewall change request
- slow file share

Security/SOC:

- suspicious email
- suspicious URL
- endpoint alert
- Wazuh false positive
- internal email flagged as phish
- mailbox quarantine request
- endpoint isolation request
- threat hunt request

Dev/CI/CD:

- GitLab runner stuck
- Semgrep finding
- Trivy finding
- ZAP finding
- Nuclei exposure finding
- release gate blocked
- request deployment approval
- fix broken web page in demo app

Platform self-repair:

- dashboard page blank
- tools dashboard red
- workflow stuck in approval state
- agent notes messy
- setup module needs redeploy
- proxy route needs local/external switch
- global search missing record

Audit/compliance:

- export evidence for ticket
- explain who approved a change
- show SLA breach reason
- summarize agent actions
- produce access review evidence

## Acceptance Bar

For a demo-ready UI scenario:

- The user can start in Element with a normal sentence.
- The bot response is human-readable and not a raw stack trace/transcript.
- General chat does not create unnecessary tickets.
- One-off developer scripts, HTML, Markdown, Bash, JavaScript, JSON, and similar
  artifacts are validated before being returned and render as code blocks in
  Element without mangled shell, currency, or code characters.
- Operational work creates a ticket only when enough context exists.
- Ticket sync status is visible and `synced` when provider integration is on.
- Ticket notes tell a chronological story without requiring raw logs.
- Follow-up chat appears as a ticket note.
- Reassignment/escalation updates the same ticket.
- Real agents either make visible progress, hit a real gate, or ask for a user
  response.
- No active smoke agents are left behind after the test.

## Known Rough Edge

Element first-login and first-contact prompts are stateful and can make browser
automation flaky even when the real system is working. The smoke script handles
the common prompts, but if a prompt blocks a run, inspect the body text and add
a narrow dismissal for that prompt. Do not replace Element with a shim to make
testing easier; the point is to prove the real client path.
