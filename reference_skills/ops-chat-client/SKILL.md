---
name: ops-chat-client
description: >
  Deploy, validate, and manage the Matrix/Element Ops Chat client, Keycloak OIDC
  identity path, Matrix application-service bridge, and dashboard agent-harness
  chat intake workflow. Use when configuring chat-based user intake, demoing
  conversational ticket creation, testing agent-selected routing from chat, or
  troubleshooting chat-to-agent handoff.
---

# Ops Chat Client

Ops Chat gives users a real collaboration client while keeping operational work
in the Agentic Operations control plane.

Reference stack:

- Element Web service: `ops-chat`, default HTTPS port `${OPS_CHAT_HTTPS_PORT:-3303}`
- Matrix Synapse service: `ops-chat-synapse`, proxied through Element on
  `${OPS_CHAT_HTTPS_PORT:-3303}` with optional direct diagnostics on
  `${OPS_CHAT_SYNAPSE_PORT:-3302}`
- Matrix application-service bridge: `ops-chat-bridge`
- Identity provider: Keycloak OIDC
- Dashboard endpoint: `/api/ops-chat/message`
- Agent execution: dashboard `agent_runner.spawn_agent()` using Hermes or
  Claude Code through the configured AI proxy

## Contract

- Matrix/Element is the user-facing chat surface.
- Synapse owns rooms, events, and OIDC login.
- The bridge receives Matrix room messages and calls the dashboard Ops Chat API.
- The dashboard hands each new chat message to the configured Hermes/Claude
  harness with an `ops_chat_tool.py` toolbelt.
- General harmless chat can be answered without a ticket.
- The chat agent may ask one concise pre-ticket clarification when the answer
  changes routing, scope, urgency, or whether a ticket is needed.
- Operational chat creates or continues a canonical ticket, intake session,
  internal note, audit event, and real agent-harness queue task.
- When a ticket is created after clarification, recent chat context is copied
  into the ticket description and the Ops Chat-created note.
- The chat agent decides whether to answer directly or use the tool to create a
  ticket. Do not reintroduce app-side JSON parsing as the decision-maker.
- During the chat-intake turn, the agent must finish with exactly one final
  dashboard tool: `python ops_chat_tool.py answer ...` for general chat or
  `python ops_chat_tool.py create-ticket ...` for tracked work. For benign
  current-information questions it may first use
  `python ops_chat_tool.py web-search ...`, then finish with `answer`. It must
  not run arbitrary curl, inline Python, external image generators, package
  installs, or suspicious URL fetches in this lightweight chat turn.
- The chat agent may decide routing and assignment, but it is not an approval
  authority. Approval, access, credential, and change gates must come from real
  downstream barriers: scoped vault leases, provider permissions, workflow
  policy, and platform approval gates when the ticket agent attempts work.
- Follow-up room messages on an existing session become `user-response` notes,
  which are delivered to active agents through the steering inbox.
- Never perform hidden work outside tickets. If the user asks for account,
  system, email, deployment, security, access, change, research, or repair work,
  create or continue a ticket.

## Compose

```bash
docker compose up -d ops-chat-db ops-chat-bridge ops-chat-synapse ops-chat
```

Important environment:

- `OPS_CHAT_PORT=3301` (HTTP compatibility redirect)
- `OPS_CHAT_HTTPS_PORT=3303`
- `OPS_CHAT_SYNAPSE_PORT=3302`
- `MATRIX_SERVER_NAME=agentic-ops.local`
- `MATRIX_PUBLIC_BASEURL=https://localhost:3303`
- `MATRIX_ELEMENT_PUBLIC_URL=https://localhost:3303`
- `MATRIX_DB_PASSWORD=<vault/runtime secret>`
- `MATRIX_REGISTRATION_SHARED_SECRET=<vault/runtime secret>`
- `MATRIX_AS_TOKEN=<vault/runtime secret>`
- `MATRIX_HS_TOKEN=<vault/runtime secret>`
- `MATRIX_OIDC_ISSUER=<Keycloak realm issuer>`
- `MATRIX_OIDC_BACKCHANNEL_BASEURL=<optional same-host/private Keycloak realm URL>`
- `MATRIX_OIDC_CLIENT_ID=agentic-ops-chat`
- `MATRIX_OIDC_CLIENT_SECRET=<vault/runtime secret>`
- `MATRIX_OIDC_CA_CERT_PATH=<trusted CA certificate for OIDC issuer HTTPS>`
- `MATRIX_SYNAPSE_TLS_ENABLED=true`
- `MATRIX_SYNAPSE_TLS_CERT_PATH=./runtime/tls/dashboard.crt`
- `MATRIX_SYNAPSE_TLS_KEY_PATH=./runtime/tls/dashboard.key`
- `MATRIX_ELEMENT_TLS_CERT_PATH=./runtime/tls/dashboard.crt`
- `MATRIX_ELEMENT_TLS_KEY_PATH=./runtime/tls/dashboard.key`
- `MATRIX_BOT_LOCALPART=agentic-ops`
- `MATRIX_BOT_DISPLAY_NAME=Agentic Ops Agent`
- `OPS_CHAT_AGENT_MODEL=<active chat handoff model>`
- `OPS_CHAT_SEARCH_URL=<private SearXNG base URL, default http://host.docker.internal:7999>`
- `OPS_CHAT_OUTBOUND_ENABLED=true`
- `OPS_CHAT_OUTBOUND_POLL_SECONDS=5`
- `DASHBOARD_SERVICE_TOKEN=<vault/runtime secret>`

`OPS_CHAT_AGENT_MODEL` must follow the active route profile. Use:

```bash
python3 scripts/switch_model_route.py --route local --restart
python3 scripts/switch_model_route.py --route external --restart
```

The switcher updates both `AGENT_DEFAULT_MODEL` and `OPS_CHAT_AGENT_MODEL`.
Do not manually leave Ops Chat on `local/agent-default` while the demo proxy is
set to the external route.

The browser-facing Synapse URL must be HTTPS when Keycloak OIDC is enabled.
The reference deployment sets `MATRIX_PUBLIC_BASEURL` and
`MATRIX_ELEMENT_PUBLIC_URL` to the same `https://<host>:3303` origin, then lets
Element nginx proxy `/_matrix/` and `/_synapse/` to Synapse. This avoids
browser homeserver certificate/CORS failures and Synapse canonical redirect
loops. Using an HTTP `MATRIX_PUBLIC_BASEURL` can produce a missing-session
callback failure after successful Keycloak login.

Synapse is strict about PostgreSQL locale. The reference `ops-chat-db` service
must initialize with `POSTGRES_INITDB_ARGS="--locale=C --encoding=UTF8"`. If a
new deployment starts Synapse against an `en_US.utf8` Matrix database, recreate
only the `ops-chat-db-data` volume; do not touch the dashboard PostgreSQL
volume.

When the Keycloak issuer uses a private-enterprise CA, set
`MATRIX_OIDC_CA_CERT_PATH` to that CA certificate. Synapse installs that CA into
the container trust bundle before OIDC discovery and token exchange. For lab
deployments with a legacy CA that modern Python rejects, set
`MATRIX_OIDC_BACKCHANNEL_BASEURL` to a private same-host Keycloak HTTPS realm
URL signed by the mounted CA.

## Smoke Test

```bash
export DASHBOARD_SERVICE_TOKEN=<from approved runtime secret source>
python3 scripts/smoke_ops_chat.py http://localhost:25480
```

Expected:

- `/api/ops-chat/matrix/health` reports Matrix Synapse + Element.
- direct `/api/ops-chat/message` creates a ticket.
- the ticket contains `Ops Chat agent-created ticket`.
- operational chat queues a real dashboard agent task unless
  `OPS_CHAT_SMOKE_SPAWN_AGENT=false` is set.
- follow-up chat on the same session is recorded as a `user-response` note.
- a ticket `/request-info` note appears in `/api/ops-chat/outbound/pending`,
  can be acked by the bridge, and does not duplicate after ack.

Scenario smoke:

```bash
python3 scripts/smoke_ops_chat_scenarios.py http://localhost:25480
python3 scripts/smoke_ops_chat_scenarios.py http://localhost:25480 --spawn-agent --agent-timeout 600
python3 scripts/smoke_ops_chat_scenarios.py http://localhost:25480 --spawn-agent --all-agent-cases --agent-timeout 600
```

Broad routing matrix:

```bash
python3 scripts/smoke_ops_chat_enterprise_matrix.py http://localhost:25480
```

This creates 50 no-spawn chat-intake tickets across executive support, IAM,
email, phishing/EDR, network, endpoint, procurement, onboarding/offboarding,
infrastructure, cloud, database, UI support, CI/CD, audit/compliance, and
platform self-repair. By default it verifies ticket creation and nonempty
agent-selected assignment; add `--strict-routing` to fail when an assignment
does not match the expected demo hint.

This proves general chat no-ticket behavior, private-web-search assisted
answers when the search provider is configured, account lockout, software
request, VPN connectivity routing, phishing and CI/CD routing without
intake-time approval gates, follow-up notes, outbound ticket updates back to
chat, global search visibility, and optional real agent handoff. The
risky-action gates must appear only during downstream ticket execution.

Browser Playwright smoke:

```bash
DASHBOARD_URL=https://<host>:25443 \
DASHBOARD_USER=demo_account_1 \
DASHBOARD_PASSWORD=<from vault> \
OPS_CHAT_URL=https://<host>:3303 \
OPS_CHAT_USER=<keycloak chat user> \
OPS_CHAT_PASSWORD=<from vault> \
OPS_CHAT_SEND_MESSAGE=true \
node scripts/smoke_ops_chat_playwright.js
```

This proves dashboard login, Element login through Keycloak, same-origin Matrix
health from inside the browser, DM creation to `@agentic-ops:agentic-ops.local`,
ticket creation, and real agent handoff.

## Demo Prompt

Fastest browser path:

1. Open `https://<host>:3303/#/user/@agentic-ops:agentic-ops.local`.
2. Sign in with Keycloak.
3. If Element asks about notifications or chat backup, dismiss it.
4. Confirm the profile says `Agentic Ops Agent`.
5. Click **Send message**.
6. Send the operational request.

Do not use **Explore Public Rooms** for the demo path; that is Element's
generic Matrix UI and can lead operators away from the local support bot.

```text
I cannot log into my account and I have a customer call in 20 minutes.
```

Expected demo answer: ticket number, assignment group, priority, and real agent
harness queue status. If the ticket agent asks the requester a question or
resolves the ticket, the bridge posts that user-facing status back into the
Matrix room. Open the dashboard ticket afterward to show the agent-created
ticket note, user-response notes, agent assignment, and any approval/access
gates created later by real execution barriers.

Ticket reassignment/escalation:

```bash
curl -sS -X POST "$SOC_DASHBOARD_URL/api/tickets/$TICKET_ID/assignment" \
  -H "Content-Type: application/json" \
  -d '{"assignee_team":"Tier 2 Endpoint Support","owning_group":"Endpoint Support","escalation_tier":"Tier 2","priority":"P2","reason":"Scope requires tier 2 endpoint packaging."}'
```

Use this when the agent or operator learns the request belongs to a different
queue or tier. It writes a `ticket-assignment` note for auditability.

## Latest Lab Proof

2026-05-20:

- Clarification/reassignment proof passed on ticket `1176`: the chat agent
  asked a pre-ticket software clarification, created the ticket after the user
  answered, synced to iTop ref `595`, preserved prior chat context, and was
  reassigned/escalated to `Tier 2 Endpoint Support` with a ticket-assignment
  note.
- Playwright browser proof now handles Element device verification,
  service-worker, notification, and new-contact confirmation prompts. Marker
  `ops-chat-playwright-1779301274503` created ticket `1177` from the Element UI.
- Real-agent proofs passed with markers `ops-chat-scenarios-1779301430` and
  `ops-chat-scenarios-1779301734`, spawning Hermes agents `326` and `327` on
  tickets `1185` and `1191`. The account-lockout case wrote user-facing login
  next steps; the software-request case asked for the minimum missing details.

- Harness-required chat toolbelt proof:
  - Marker `harness-answer-tool-1779286572` used the Hermes chat harness and
    `ops_chat_tool.py answer` to answer a general cat request with no ticket.
  - Marker `spawn-flag-enforced-1779286517` used the Hermes chat harness and
    `ops_chat_tool.py create-ticket` to create ticket `930`, assign
    `Identity & Access`, priority `P2`, with no intake-time approval gate.
  - `spawn_agent=false` was enforced by the tool, returning
    `spawn_agent_disabled_by_caller` and leaving zero active agents.
- Do not replace this with app-side JSON parsing. If the model fails to call
  the tool, fix the harness prompt/tool contract and retry through the harness.
- Element Web is served on `https://192.168.50.222:3303`; the old
  `http://192.168.50.222:3301` URL redirects there. Matrix client and OIDC
  callback traffic also work same-origin under `https://192.168.50.222:3303`;
  `https://192.168.50.222:3302` remains available for direct Synapse
  diagnostics.
- Playwright no-bypass browser proof passed as `demo_chat_live11`, including
  dashboard login, Element/Keycloak login, browser Matrix health, and Matrix DM
  marker `ops-chat-same-origin-playwright-1779261056`.
- That DM created ticket `908`, spawned Hermes agent `307` / task `304`, wrote
  model-turn audit evidence, asked the user which account/system was affected,
  and stopped cleanly in `awaiting_user_response` with no active process left.
- The direct bot-profile flow passed with marker
  `element-direct-agent-ui-1779283071`: open
  `https://192.168.50.222:3303/#/user/@agentic-ops:agentic-ops.local`, click
  **Send message**, send the request, receive ticket `909`, and spawn Hermes
  agent `308` / task `305`.
- Playwright login proof passed as `demo_chat_alice`, landing at `#/home`.
  Use `demo_chat_alice`, `demo_chat_jeff`, or `demo_chat_exec` for the chat
  demo; passwords are stored in same-named server-manager vault keys.
- The Matrix appservice auto-joins DM invites for
  `@agentic-ops:agentic-ops.local`, then sends a connected message before
  routing user requests into the dashboard.
- Browser-created Matrix DM marker `matrix-ui-live-chat-1779258900` created
  ticket `907`, spawned Hermes agent `306` / task `303`, and settled in
  `awaiting_user_response`.
- Enterprise matrix marker `ops-chat-enterprise-matrix-1779257312` passed 50/50
  RACI routing checks on tickets `846`-`895`.
- Real-agent scenario marker `ops-chat-scenarios-1779257332` passed on tickets
  `896`-`906`, including account, software, VPN, phishing, CI/CD, and approval
  gate handoffs.

- Scenario smoke with real handoff passed on tickets `750`-`754`.
- Ticket `754` routed account lockout to Identity & Access, spawned Hermes
  agent `284`, wrote live agent notes, and ended cleanly in
  `awaiting_user_response` with no active process left behind.
- Ticket `749` proves the follow-up loop: first agent `282` asked which system
  the user could not access, the user replied through Ops Chat, continuation
  agent `283` wrote Keycloak/SSO troubleshooting guidance, and the ticket
  remained waiting for the requester instead of showing a failed-agent badge.
- A broader all-agent-cases run passed with marker
  `ops-chat-scenarios-1779250846`: account lockout ticket `769`, delivery gate
  ticket `770`, phishing/EDR ticket `771`, software request ticket `772`, and
  VPN request ticket `773`. Software and VPN follow-ups spawned continuation
  agents `291` and `292`.
- VPN routing was corrected and verified on ticket `781`, which classified as
  `vpn-connectivity` and routed to `Network Operations`.
- Approval gates created during downstream ticket execution are now rebound to
  the spawned agent id. Ticket `784` proved the full path: change `223` was
  bound to agent `293`, approval spawned continuation agent `294`, the change
  completed with lab-safe evidence, and the ticket closed with no active
  processes.
- Agent note-quality guardrails now explicitly forbid placeholder/debug notes
  such as "test note"; the rerun on ticket `778` proved the complex
  phishing/EDR path stopped at approval without placeholder notes.

If a live provider is slow, inspect `/api/agents/processes`, the ticket notes,
and the latest checkpoint rather than relying on a percentage field alone.
Durable wait checkpoints should render as `awaiting_user_response`,
`pending_approval`, or `awaiting_access`, not as failures.
