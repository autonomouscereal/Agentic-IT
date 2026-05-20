# Ops Chat Deployment Blueprint

Ops Chat is the reference conversational intake surface for Agentic Operations.
It uses a real Matrix/Element stack, not a chat shim:

- `ops-chat`: Element Web browser client.
- `ops-chat-synapse`: Matrix Synapse homeserver.
- `ops-chat-db`: PostgreSQL database for Synapse.
- `ops-chat-bridge`: Matrix application-service bridge into the dashboard.
- Keycloak: OIDC identity provider.
- Dashboard Ops Chat API: canonical chat intake, tickets, audit, and real
  Hermes/Claude Code agent handoff through the AI proxy.

## Network Contract

Default reference ports:

- `https://<host>:3303`: Element Web and same-origin Matrix client API.
- `http://<host>:3301`: compatibility redirect to `https://<host>:3303`.
- `https://<host>:3302`: optional direct Synapse client API for diagnostics.
- `http://ops-chat-synapse:8008`: internal Synapse listener for Element proxy and
  appservice traffic.
- `http://ops-chat-bridge:29318`: internal appservice health endpoint.

The browser path should use `3303`. Element nginx proxies `/_matrix/` and
`/_synapse/` to Synapse while preserving the full `Host` header, including the
port. That avoids browser-side homeserver certificate/cross-origin failures and
prevents Synapse OIDC canonical redirect loops.

## TLS And OIDC

Element and Synapse reuse the dashboard runtime certificate by default:

- `MATRIX_ELEMENT_TLS_CERT_PATH=./runtime/tls/dashboard.crt`
- `MATRIX_ELEMENT_TLS_KEY_PATH=./runtime/tls/dashboard.key`
- `MATRIX_SYNAPSE_TLS_CERT_PATH=./runtime/tls/dashboard.crt`
- `MATRIX_SYNAPSE_TLS_KEY_PATH=./runtime/tls/dashboard.key`
- `MATRIX_OIDC_CA_CERT_PATH=./runtime/tls/dashboard-ca.crt`

When Keycloak is exposed with the same Agentic Operations runtime CA, Synapse
installs that CA into its container trust bundle at startup before loading the
homeserver. Do not disable TLS verification for convenience. If a customer uses
an enterprise CA, point `MATRIX_OIDC_CA_CERT_PATH` at that CA file.

Key OIDC values:

- `MATRIX_PUBLIC_BASEURL=https://<host>:3303`
- `MATRIX_ELEMENT_PUBLIC_URL=https://<host>:3303`
- `MATRIX_OIDC_ISSUER=https://<host>:8443/realms/<realm>`
- `MATRIX_OIDC_CLIENT_ID=agentic-ops-chat`
- `MATRIX_OIDC_CLIENT_SECRET=<vault/runtime secret>`

The Keycloak client must allow redirects and web origins for the Element URL.
Use:

```bash
python3 scripts/setup_ops_chat_keycloak.py
```

## Deploy

```bash
docker compose up -d --build ops-chat-db ops-chat-bridge ops-chat-synapse ops-chat
```

Health checks:

```bash
curl -sk https://<host>:3303/config.json
curl -sk https://<host>:3303/_matrix/client/versions
curl -sk https://<host>:3302/_matrix/client/versions
curl -sS http://127.0.0.1:25480/api/ops-chat/matrix/health \
  -H "X-Dashboard-Service-Token: $DASHBOARD_SERVICE_TOKEN"
```

## Browser Proof

Recommended human demo path:

1. Open `https://<host>:3303/#/user/@agentic-ops:agentic-ops.local`.
2. Sign in with Keycloak.
3. Dismiss Element's notification/chat-backup prompts if they appear.
4. Confirm the profile says `Agentic Ops Agent`.
5. Click **Send message**.
6. Type the user's request and press Enter.

Avoid **Explore Public Rooms** during the demo. That is Element's general
Matrix room-directory feature and is not the support-agent intake path.

Run the Playwright proof from an operator workstation:

```powershell
$env:DASHBOARD_URL="https://192.168.50.222:25443"
$env:DASHBOARD_USER="demo_account_1"
$env:DASHBOARD_PASSWORD="<from vault>"
$env:OPS_CHAT_URL="https://192.168.50.222:3303"
$env:OPS_CHAT_USER="demo_chat_live11"
$env:OPS_CHAT_PASSWORD="<from vault>"
$env:OPS_CHAT_SEND_MESSAGE="true"
node scripts/smoke_ops_chat_playwright.js
```

Expected:

- dashboard login succeeds;
- Element redirects through Keycloak and lands at `#/home`;
- browser `fetch("/_matrix/client/versions")` returns `200`;
- a direct message to `@agentic-ops:agentic-ops.local` creates a dashboard
  ticket when the chat agent chooses to call the dashboard ticket tool;
- policy-eligible work queues a real agent task.
- chat intake itself does not open approval gates; approval/access/change gates
  appear only when the ticket agent hits enforced platform, credential,
  workflow, or provider barriers.

Implementation note: Ops Chat does not rely on application-side structured
parsing to classify the user message. The Matrix bridge hands the message to
the configured Hermes/Claude harness. That chat agent receives
`ops_chat_tool.py`; it either answers directly or uses the tool to create the
ticket and spawn the ticket-resolution agent.

Latest live proof: marker `ops-chat-same-origin-playwright-1779261056` created
ticket `908`, spawned Hermes agent `307` / task `304`, recorded model-turn audit
events, asked the requester which account/system they meant, and stopped in the
durable `awaiting_user_response` state with no active process left behind.

Latest direct-profile proof: marker `element-direct-agent-ui-1779283071`
created ticket `909` from the Element UI, spawned Hermes agent `308` / task
`305`, and showed the bot reply in the Matrix room.

## Troubleshooting

`Cannot reach homeserver` in Element:

- Verify `https://<host>:3303/_matrix/client/versions` works in the same browser.
- Confirm Element config uses `https://<host>:3303` as the homeserver URL.
- Confirm Element nginx preserves `Host: <host>:3303` when proxying Matrix paths.
- Confirm the runtime CA is trusted by the browser if using self-signed TLS.

`login provider is unavailable`:

- Check Synapse logs for OIDC discovery errors.
- Verify `MATRIX_OIDC_ISSUER` is browser-routable HTTPS.
- Verify Keycloak client redirect URIs include `https://<host>:3303/*`.

OIDC callback returns `500`:

- Check Synapse logs for `certificate verify failed`.
- Ensure Keycloak presents a certificate chained to `MATRIX_OIDC_CA_CERT_PATH`.
- Recreate `ops-chat-synapse` after changing the CA so
  `update-ca-certificates` runs.

Synapse collation/startup error:

- Recreate only `ops-chat-db-data`; Synapse requires PostgreSQL locale `C`.
- Do not touch the dashboard PostgreSQL volume.

Bot does not respond to a DM:

- Check `ops-chat-bridge` logs and `/health`.
- Ensure the bot localpart matches `MATRIX_BOT_LOCALPART`.
- Confirm the appservice tokens in Synapse and the bridge match.

Chat creates tickets but opens approval gates too early:

- This is not expected. Ops Chat intake may choose ticket class, priority, and
  assignment group only.
- Approval gates belong to downstream ticket execution, access requests,
  provider permission failures, and workflow policy barriers.
- Check `/api/ops-chat/message` responses for `change_id`; it should be empty
  during initial chat intake.
