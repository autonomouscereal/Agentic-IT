# Global Search And Ops Chat

## Global Search

The dashboard exposes a bounded, RBAC-aware global search at:

- `GET /api/search/global?q=<query>&limit=60`

The endpoint searches across the operator's allowed scope:

- tickets and ticket notes
- agents
- approval gates / changes
- postmortems
- workflows
- CI/CD runs
- tools
- audit records

Ticket and ticket-note results are filtered through the same row-level ticket
scope logic used by the ticket APIs. Other result families are included only
when the authenticated subject has the matching read capability. The endpoint
does not return credential values or raw audit details.

The dashboard shell includes a search box above every page. Results open the
native record where possible: tickets open the ticket modal, CI/CD opens the run
modal, workflows and postmortems open their detail views, and audit/tool/agent
results navigate to the matching page.

Smoke:

```bash
python3 scripts/smoke_global_search.py http://localhost:25480
```

When dashboard auth is enforced, set `DASHBOARD_SERVICE_TOKEN` in the execution
environment. The smoke creates a local ticket and note with a unique marker,
then proves both are discoverable through global search.

## Ops Chat

Ops Chat is the demo-friendly collaboration intake path. It is intentionally not
a dashboard widget and not an OpenAI chat shim. The reference deployment uses:

- Element Web as the browser chat client
- Matrix Synapse as the homeserver
- Keycloak OIDC for identity
- a Matrix application-service bridge for room events
- the dashboard Ops Chat API as the canonical control-plane intake endpoint
- Hermes or Claude Code agent harnesses through the configured AI proxy

Operational path:

1. A user signs in through Element / Synapse / Keycloak.
2. The user sends a room message.
3. Synapse delivers the message to `ops-chat-bridge`.
4. The bridge calls `POST /api/ops-chat/message` with Matrix room/event metadata.
5. The dashboard classifies the request through service-desk intake and RACI.
6. Operational work creates or continues a canonical ticket.
7. The dashboard queues a real `agent_runner.spawn_agent()` task using Hermes or
   Claude Code through the AI proxy.
8. Follow-up room messages become `user-response` notes and are delivered to
   active agents through the steering inbox.

Compose services:

- `ops-chat-db`: PostgreSQL for Synapse
- `ops-chat-synapse`: Matrix homeserver
- `ops-chat`: Element Web
- `ops-chat-bridge`: Matrix appservice to dashboard bridge

Default reference ports:

- `https://<host>:3303`: Element Web UI.
- `http://<host>:3301`: compatibility redirect to the HTTPS Element UI.
- `https://<host>:3302`: public Matrix/Synapse client API and OIDC callback.
- `http://ops-chat-synapse:8008`: internal bridge-to-Synapse API.

The Element and Synapse public listeners reuse the dashboard runtime TLS
certificate by default. Set `MATRIX_ELEMENT_PUBLIC_URL` and
`MATRIX_PUBLIC_BASEURL` to browser-routable HTTPS URLs before configuring the
Keycloak OIDC client. Synapse OIDC login uses `Secure` cookies; an HTTP Matrix
public base URL can cause the OIDC callback to fail with a missing-session
error.

Synapse requires a PostgreSQL database initialized with locale `C`. The
reference Compose service sets `POSTGRES_INITDB_ARGS="--locale=C --encoding=UTF8"`.
If Synapse logs an incorrect-collation error, recreate only the
`ops-chat-db-data` volume and leave the dashboard database untouched.

When the Keycloak issuer uses a self-signed or private-enterprise certificate,
set `MATRIX_OIDC_CA_CERT_PATH` to the CA certificate path on the deployment host.
The Synapse container mounts that file as its Python TLS trust bundle for OIDC
discovery. Do not disable TLS verification for demo convenience.

For lab deployments with an older Keycloak CA that lacks modern X.509 key-usage
extensions, set `MATRIX_OIDC_BACKCHANNEL_BASEURL` to a private same-host
Keycloak HTTP realm URL. Synapse keeps the public HTTPS issuer and authorization
URL for users, then uses the private backchannel only for server-side token,
userinfo, and JWKS calls.

Smoke:

```bash
python3 scripts/smoke_ops_chat.py http://localhost:25480
```

The smoke proves dashboard chat intake creates a real ticket, records the Ops
Chat classification note, checks Matrix health metadata, and verifies follow-up
messages continue the same ticket. By default it also expects a real agent
harness task to be queued; set `OPS_CHAT_SMOKE_SPAWN_AGENT=false` only for
unit-style checks where the live model lane must not be used.

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

This no-spawn matrix covers 50 enterprise request types across executive
support, IAM, email, phishing/EDR, network, endpoint, procurement,
onboarding/offboarding, infrastructure, cloud, database, UI support, CI/CD,
audit/compliance, and platform self-repair. It proves each chat-style request
creates a ticket and lands in the expected RACI group without spending model
capacity on all 50 cases.

This covers:

- harmless general chat without ticket creation
- account-lockout intake routed to Identity & Access
- software-install intake routed to Endpoint Support
- VPN connectivity routed to Network Operations
- phishing intake routed to Security Operations with an approval gate
- CI/CD delivery-gate intake routed to DevSecOps with an approval gate
- follow-up chat recorded as `user-response`
- global search visibility for the scenario marker
- optional real Hermes/Claude harness handoff through the AI proxy

Latest live proof on 2026-05-20:

- Playwright Element login passed through Keycloak as `demo_chat_alice` and
  landed at `https://192.168.50.222:3303/#/home`.
- The Matrix bridge now auto-joins direct-message invites for
  `@agentic-ops:agentic-ops.local`. A browser-created Element DM with marker
  `matrix-ui-live-chat-1779258900` created ticket `907`, spawned Hermes agent
  `306` / task `303`, and ended in `awaiting_user_response`.
- The 50-case enterprise Ops Chat matrix passed with marker
  `ops-chat-enterprise-matrix-1779257312`; tickets `846`-`895` all routed to
  their expected RACI groups.
- The real-agent scenario suite passed with marker
  `ops-chat-scenarios-1779257332`; tickets `896`-`906` covered general chat,
  account lockout, software request, VPN, phishing approval, CI/CD approval,
  and five Hermes-backed agent handoffs.

- `scripts/smoke_ops_chat_scenarios.py --spawn-agent` created tickets `750`
  through `754` and passed.
- Ticket `754` came from Ops Chat, routed to Identity & Access, spawned Hermes
  agent `284`, wrote live agent notes, and landed cleanly in
  `awaiting_user_response` with no active agent process left behind.
- Ticket `749` proves the follow-up path: the first agent asked for the target
  login system, the user replied via Ops Chat, and continuation agent `283`
  wrote Keycloak/SSO troubleshooting guidance.
- A broader real-agent run passed with marker `ops-chat-scenarios-1779250846`:
  account lockout ticket `769`, delivery gate ticket `770`, phishing/EDR ticket
  `771`, software request ticket `772`, and VPN request ticket `773`. The
  software and VPN tickets then received requester follow-ups via Ops Chat and
  spawned continuation agents `291` and `292`.
- VPN routing was corrected and verified with marker
  `ops-chat-scenarios-1779251833`: ticket `781` classified as
  `vpn-connectivity` and routed to `Network Operations`.
- Chat-created approval gates are now bound to the spawned agent so approval can
  resume the waiting agent path. Ticket `784` / change `223` proved this:
  initial agent `293` stopped at the approval gate, approval spawned
  continuation agent `294`, the change completed with lab-safe evidence, and
  the ticket closed with no active processes left behind.

The 2026-05-20 hardening pass also fixed three demo-readiness issues:

- `scripts/switch_model_route.py --route external` now updates
  `OPS_CHAT_AGENT_MODEL` so chat-originated agents follow the active model
  route.
- The API Compose service now passes `OPS_CHAT_AGENT_MODEL` into the container.
- Durable wait statuses such as `awaiting_user_response` fit the database
  schema and are rendered as wait states instead of failed agents.
- Agents are instructed not to write placeholder/debug notes such as
  "test note"; notes must contain real operational context.
- Chat approval gates created before agent execution are rebound to the spawned
  agent id, which allows approval-gate resume to work for chat-originated work.
- A dedicated `VPN connectivity issue` RACI rule prevents VPN tunnel failures
  from being treated as generic IAM entitlement requests.

## Security Notes

- Matrix/Element does not bypass dashboard authentication. The bridge uses the
  dashboard service token as a runtime secret.
- Synapse user login is delegated to Keycloak OIDC.
- Matrix appservice tokens, database passwords, OIDC client secrets, and
  dashboard service tokens are runtime/vault secrets only.
- Work-worthy chat is logged as tickets so operational action remains traceable.
- The chat endpoint uses existing RACI, approval, provider sync,
  auto-assignment, agent queue, steering, and audit paths rather than a hidden
  workflow.
- Chat follow-ups on a waiting ticket spawn a continuation agent; follow-ups on
  a currently running agent are delivered as steering context.
