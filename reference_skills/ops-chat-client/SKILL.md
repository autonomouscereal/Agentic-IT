---
name: ops-chat-client
description: >
  Deploy, validate, and manage the Matrix/Element Ops Chat client, Keycloak OIDC
  identity path, Matrix application-service bridge, and dashboard agent-harness
  chat intake workflow. Use when configuring chat-based user intake, demoing
  conversational ticket creation, testing RACI routing from chat, or
  troubleshooting chat-to-agent handoff.
---

# Ops Chat Client

Ops Chat gives users a real collaboration client while keeping operational work
in the Agentic Operations control plane.

Reference stack:

- Element Web service: `ops-chat`, default port `${OPS_CHAT_PORT:-3301}`
- Matrix Synapse service: `ops-chat-synapse`, default port `${OPS_CHAT_SYNAPSE_PORT:-3302}`
- Matrix application-service bridge: `ops-chat-bridge`
- Identity provider: Keycloak OIDC
- Dashboard endpoint: `/api/ops-chat/message`
- Agent execution: dashboard `agent_runner.spawn_agent()` using Hermes or
  Claude Code through the configured AI proxy

## Contract

- Matrix/Element is the user-facing chat surface.
- Synapse owns rooms, events, and OIDC login.
- The bridge receives Matrix room messages and calls the dashboard Ops Chat API.
- General harmless chat can be answered without a ticket.
- Operational chat creates or continues a canonical ticket, intake session,
  internal note, audit event, optional approval gate, and real agent-harness
  queue task.
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

- `OPS_CHAT_PORT=3301`
- `OPS_CHAT_SYNAPSE_PORT=3302`
- `MATRIX_SERVER_NAME=agentic-ops.local`
- `MATRIX_PUBLIC_BASEURL=http://localhost:3302`
- `MATRIX_ELEMENT_PUBLIC_URL=http://localhost:3301`
- `MATRIX_DB_PASSWORD=<vault/runtime secret>`
- `MATRIX_REGISTRATION_SHARED_SECRET=<vault/runtime secret>`
- `MATRIX_AS_TOKEN=<vault/runtime secret>`
- `MATRIX_HS_TOKEN=<vault/runtime secret>`
- `MATRIX_OIDC_ISSUER=<Keycloak realm issuer>`
- `MATRIX_OIDC_BACKCHANNEL_BASEURL=<optional same-host/private Keycloak realm URL>`
- `MATRIX_OIDC_CLIENT_ID=agentic-ops-chat`
- `MATRIX_OIDC_CLIENT_SECRET=<vault/runtime secret>`
- `MATRIX_OIDC_CA_CERT_PATH=<trusted CA certificate for OIDC issuer HTTPS>`
- `OPS_CHAT_AGENT_MODEL=<active chat handoff model>`
- `DASHBOARD_SERVICE_TOKEN=<vault/runtime secret>`

`OPS_CHAT_AGENT_MODEL` must follow the active route profile. Use:

```bash
python3 scripts/switch_model_route.py --route local --restart
python3 scripts/switch_model_route.py --route external --restart
```

The switcher updates both `AGENT_DEFAULT_MODEL` and `OPS_CHAT_AGENT_MODEL`.
Do not manually leave Ops Chat on `local/agent-default` while the demo proxy is
set to the external route.

Synapse is strict about PostgreSQL locale. The reference `ops-chat-db` service
must initialize with `POSTGRES_INITDB_ARGS="--locale=C --encoding=UTF8"`. If a
new deployment starts Synapse against an `en_US.utf8` Matrix database, recreate
only the `ops-chat-db-data` volume; do not touch the dashboard PostgreSQL
volume.

When the Keycloak issuer uses a private-enterprise CA, set
`MATRIX_OIDC_CA_CERT_PATH` to that CA certificate. For lab deployments with a
legacy CA that modern Python rejects, set `MATRIX_OIDC_BACKCHANNEL_BASEURL` to a
private same-host Keycloak HTTP realm URL. Synapse keeps the public HTTPS issuer
and browser authorization URL, then uses the private backchannel only for
server-side token, userinfo, and JWKS calls.

## Smoke Test

```bash
export DASHBOARD_SERVICE_TOKEN=<from approved runtime secret source>
python3 scripts/smoke_ops_chat.py http://localhost:25480
```

Expected:

- `/api/ops-chat/matrix/health` reports Matrix Synapse + Element.
- direct `/api/ops-chat/message` creates a ticket.
- the ticket contains `Ops Chat intake classification`.
- operational chat queues a real dashboard agent task unless
  `OPS_CHAT_SMOKE_SPAWN_AGENT=false` is set.
- follow-up chat on the same session is recorded as a `user-response` note.

Scenario smoke:

```bash
python3 scripts/smoke_ops_chat_scenarios.py http://localhost:25480
python3 scripts/smoke_ops_chat_scenarios.py http://localhost:25480 --spawn-agent --agent-timeout 600
```

This proves general chat no-ticket behavior, account lockout, software request,
phishing approval gate, CI/CD approval gate, follow-up notes, global search
visibility, and optional real agent handoff.

## Demo Prompt

```text
I cannot log into my account and I have a customer call in 20 minutes.
```

Expected demo answer: ticket number, assignment group, priority, approval gate
when applicable, and real agent harness queue status. Open the dashboard ticket
afterward to show classification, notes, agent assignment, approval gates, and
audit trail.

## Latest Lab Proof

2026-05-20:

- Scenario smoke with real handoff passed on tickets `750`-`754`.
- Ticket `754` routed account lockout to Identity & Access, spawned Hermes
  agent `284`, wrote live agent notes, and ended cleanly in
  `awaiting_user_response` with no active process left behind.
- Ticket `749` proves the follow-up loop: first agent `282` asked which system
  the user could not access, the user replied through Ops Chat, continuation
  agent `283` wrote Keycloak/SSO troubleshooting guidance, and the ticket
  remained waiting for the requester instead of showing a failed-agent badge.

If a live provider is slow, inspect `/api/agents/processes`, the ticket notes,
and the latest checkpoint rather than relying on a percentage field alone.
Durable wait checkpoints should render as `awaiting_user_response`,
`pending_approval`, or `awaiting_access`, not as failures.
