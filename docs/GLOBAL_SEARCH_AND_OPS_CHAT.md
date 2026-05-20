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

On 2026-05-20 the live smoke proved Element/Synapse/Keycloak health, ticket
creation, follow-up note capture, and real Hermes queue handoff. The local model
lane then stalled without note/checkpoint movement, so the live demo should keep
chat actions small and use completed proof tickets for longer agent narratives
until the provider/harness reliability work is completed.

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
