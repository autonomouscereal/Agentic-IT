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
- Agent execution: dashboard `agent_runner.spawn_agent()` using Hermes,
  Claude Code, or Codex through the configured AI proxy
- Harness selector: leave `OPS_CHAT_AGENT_HARNESS` and `OPS_CHAT_AGENT_MODEL`
  blank to follow the active dashboard Settings profile, or set/pass `hermes`,
  `claude-code`, or `codex` for a bridge-wide or per-request smoke/demo
  override.

## Contract

- Matrix/Element is the user-facing chat surface.
- Synapse owns rooms, events, and OIDC login.
- The bridge receives Matrix room messages and calls the dashboard Ops Chat API.
- The dashboard hands each new chat message to the configured Hermes/Claude/Codex
  harness with an `ops_chat_tool.py` toolbelt.
- Codex is a peer harness, not a bridge redesign. Ops Chat must call the same
  dashboard harness abstraction for Hermes, Claude Code, and Codex.
- General harmless chat can be answered without a ticket.
- The chat agent may ask one concise pre-ticket clarification when the answer
  changes routing, scope, urgency, or whether a ticket is needed.
- Operational chat creates or continues a canonical ticket, intake session,
  internal note, audit event, and real agent-harness queue task.
- When a ticket is created after clarification, recent chat context is copied
  into the ticket description and the Ops Chat-created note.
- Chat-created tickets must preserve canonical contact metadata:
  `opened_by_*` for the platform/agent/operator opening the ticket,
  `requester_*` for the person asking for work, and `affected_user_*` for the
  impacted person/account/mailbox/device/service/app. Requester and affected
  user may differ. Do not invent affected-user emails.
- The chat agent decides whether to answer directly, create a new ticket, or
  continue/cancel an existing ticket from the same room. Do not assume one
  Matrix room equals one ticket; the room can contain several unrelated asks.
  Do not reintroduce app-side JSON parsing as the decision-maker.
- During the chat-intake turn, the agent must finish with exactly one final
  dashboard tool: `python ops_chat_tool.py answer --reply-file answer.md` for
  general chat, `python ops_chat_tool.py create-ticket ...` for new tracked
  work, or `python ops_chat_tool.py continue-ticket ...` for updates to an
  existing room ticket. It can also use `python ops_chat_tool.py list-tickets`
  and `python ops_chat_tool.py ticket-status --ticket-id N` before answering
  room-scoped status questions. For benign current-information questions it may
  first use `python ops_chat_tool.py web-search ...`, then finish with
  `answer`. For one-off developer artifacts, it must write the artifact file
  and finish with `python ops_chat_tool.py validate-artifact --path ...`; do
  not paste untested code through `answer`. It must not run arbitrary curl,
  inline Python, external image generators, package installs, or suspicious URL
  fetches in this lightweight chat turn.
- The chat agent may decide routing and assignment, but it is not an approval
  authority. Approval, access, credential, and change gates must come from real
  downstream barriers: scoped vault leases, provider permissions, workflow
  policy, and platform approval gates when the ticket agent attempts work.
- Follow-up room messages do not automatically attach to the latest ticket.
  The chat agent sees recent linked tickets and must decide whether the message
  is harmless chat, a new ticket, or a `user-response` note on a specific
  existing ticket. Cancellation-like updates mark the ticket cancelled and stop
  that ticket's active test/worker agent when present.
- Same-message `create-ticket` retries are idempotent. The tool passes a
  `message_hash` in ticket `access_scope`, and the dashboard returns the
  existing active ticket for the same `session_id + message_hash` instead of
  syncing a duplicate provider ticket.
- Ticket worker assignment from `ops_chat_tool.py` does not default to
  `local/agent-default`. Unless a caller explicitly passes a model for a smoke
  test, the tool omits the model and passes the Settings-resolved runtime
  profile/harness to `/api/tickets/{id}/assign-agent`. This prevents stale
  `AGENT_DEFAULT_MODEL` values from breaking Codex OAuth workers.
- Side-effect recovery must not use "latest ticket in the room" for harmless
  chat. If a general/current-information message follows a ticket, answer the
  message unless the user clearly asks for ticket work or explicitly references
  an existing ticket.
- The `create-ticket` tool rejects obvious follow-up/update/cancel/reassign
  messages when the chat session already has linked ticket ids. Use
  `continue-ticket` for those messages so a user confirmation does not open a
  duplicate work ticket.
- `continue-ticket` supports assignment fields for scope changes:
  `--assignment-group`, `--owning-group`, `--assignee`, `--escalation-tier`,
  and `--priority`. Use those fields to reassign or escalate an existing ticket
  when the requester clarifies scope. Do not open a duplicate just to move the
  work to a different team.
- `create-ticket` supports `--affected-user-name` / `--affected-user-email`
  and `continue-ticket` supports affected-user/requester override fields for
  corrections. Use them when the user says the work is for someone else, such
  as "Alice needs Acrobat" or "the CEO is locked out." If a follow-up says
  "actually this is for Bob," continue the existing ticket and update contact
  metadata instead of opening a duplicate.
- The bridge sets Matrix typing state and, for turns that take longer than a few
  seconds, sends a short working acknowledgement so the user sees that the
  agent is alive before the final answer/ticket response arrives.
- The bridge sends fenced code with safe Matrix `formatted_body` HTML, so
  Element renders code blocks for developer one-off scripts without executing
  user HTML.
- The bridge handles Matrix file/image/video/audio uploads. Uploaded files are
  stored in the dashboard runtime upload directory, copied into the chat
  harness workspace under `attachments/`, linked to operational tickets as
  attachment metadata, and treated as untrusted input. Agent-generated
  artifacts from `validate-artifact` can be returned to Element as downloadable
  Matrix files when small enough for the demo bridge.
- Animation/video requests use the bundled `animation-video` skill. Agents
  should create short deterministic MP4/WebM artifacts, validate them, and send
  the artifact back through Ops Chat instead of pasting binary data.
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
- `OPS_CHAT_AGENT_MODEL=<blank to follow Settings profile, or targeted model>`
- `OPS_CHAT_AGENT_HARNESS=<blank|hermes|claude-code|codex>`; blank follows
  the active Settings profile. Use this for bridge-level demo rooms only when
  needed.
- `OPS_CHAT_SEARCH_URL=<private SearXNG base URL, default http://host.docker.internal:7999>`
- `OPS_CHAT_OUTBOUND_ENABLED=true`
- `OPS_CHAT_OUTBOUND_POLL_SECONDS=5`
- `OPS_CHAT_GENERAL_AGENT_TIMEOUT_SECONDS=3600`
- `OPS_CHAT_INTAKE_AGENT_TIMEOUT_SECONDS=3600`
- `OPS_CHAT_DASHBOARD_TIMEOUT_SECONDS=3600`
- `DASHBOARD_SERVICE_TOKEN=<vault/runtime secret>`

Keep local-agent chat/intake and bridge HTTP windows at one hour by default.
Short 120-180 second timeouts are treated as a regression for local model
testing; rely on typing state and the working acknowledgement while the harness
runs.

The preferred path is the dashboard Settings page. Use it to choose
`codex-primary`, `local-only`, or `hermes-external`, tune reasoning/fast mode,
and assign chat to a specific runtime profile. Route switch scripts remain
available for proxy-level local/external flips:

```bash
python3 scripts/switch_model_route.py --route local --restart
python3 scripts/switch_model_route.py --route external --restart
```

Do not manually leave Ops Chat on a stale model override while the Settings
profile or demo proxy route changes. Blank `OPS_CHAT_AGENT_MODEL` is the safest
default.

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
- the ticket shows requester and affected-user fields when applicable, and the
  active provider preserves that contact context.
- operational chat queues a real dashboard agent task unless
  `OPS_CHAT_SMOKE_SPAWN_AGENT=false` is set.
- follow-up chat on the same session is recorded as a `user-response` note.
- a ticket `/request-info` note appears in `/api/ops-chat/outbound/pending`,
  can be acked by the bridge, and does not duplicate after ack.

Scenario smoke:

```bash
python3 scripts/smoke_ops_chat_scenarios.py http://localhost:25480 --cleanup
python3 scripts/smoke_ops_chat_scenarios.py http://localhost:25480 --agent-only --spawn-agent --agent-case account-lockout --agent-timeout 600 --cleanup
python3 scripts/smoke_ops_chat_scenarios.py http://localhost:25480 --agent-only --spawn-agent --agent-case delivery-gate --agent-timeout 600 --cleanup
```

Broad routing matrix:

```bash
python3 scripts/smoke_ops_chat_enterprise_matrix.py http://localhost:25480 --strict-routing --require-provider-sync --cleanup
```

This creates 50 no-spawn chat-intake tickets across executive support, IAM,
email, phishing/EDR, network, endpoint, procurement, onboarding/offboarding,
infrastructure, cloud, database, UI support, CI/CD, audit/compliance, and
platform self-repair. By default it verifies ticket creation and nonempty
agent-selected assignment; add `--strict-routing` to fail when an assignment
does not match the expected demo hint. In the iTop-backed lab, also use
`--require-provider-sync` so each synthetic ticket must have a provider,
provider ref, and `provider_sync_status=synced`. Use `--cleanup` so broad tests
cancel their own synthetic tickets and do not clutter the demo queue.

Demo baseline note: after the 2026-05-21 curation pass, the live dashboard
should have zero open tickets, zero active agents, zero open agent tasks, and
zero pending/approved changes before an audience demo. If an Ops Chat marathon
or broad matrix run leaves synthetic tickets behind, archive them with an
explicit demo-curation reason and keep the golden prepared proofs in
`docs/DEMO_TICKET_CATALOG.md` as the only `Demo Proofs` examples.

This proves general chat no-ticket behavior, private-web-search assisted
answers when the search provider is configured, account lockout, software
request, VPN connectivity routing, phishing and CI/CD routing without
intake-time approval gates, follow-up notes, outbound ticket updates back to
chat, global search visibility, and optional real agent handoff. The
risky-action gates must appear only during downstream ticket execution.

Tool-result reliability:

- Once the chat toolbelt records a structured `ticket`, `ticket-update`, or
  `artifact` result, a later `answer` call in the same harness turn must not
  overwrite it.
- If a model does overwrite the visible result with a general "Ticket #..."
  style response, the API recovers the last structured action from the action
  log and surfaces the real ticket/update/artifact result.
- Bare "change" in a new user request is not enough to treat the message as an
  existing-ticket update. Only explicit scope/change-ticket phrases should
  trigger update recovery.
- Bare "instead" is not enough to attach a replacement request to a cancelled
  ticket. Use `continue-ticket` only when the user explicitly updates/cancels
  a known ticket or says to keep the same request/ticket. A replacement such as
  "instead put in a new ticket to order pizza" should create a distinct ticket.
- If the harness fails to call a final tool after retries, the dashboard has a
  bounded fallback only for obvious existing-ticket updates in a one-ticket
  room or when the user explicitly names a linked ticket id. Harmless chat and
  multi-ticket rooms are not silently attached to the latest ticket.
- Placeholder affected users like `User (user-direct)`, `me`, or `requester`
  are normalized to the chat requester for first-person requests.

Browser Playwright smoke:

```bash
DASHBOARD_URL=https://<host>:25443 \
DASHBOARD_USER=demo_account_1 \
DASHBOARD_PASSWORD=<from vault> \
OPS_CHAT_URL=https://<host>:3303 \
OPS_CHAT_USER=<keycloak chat user> \
OPS_CHAT_PASSWORD=<from vault> \
OPS_CHAT_SEND_MESSAGE=true \
OPS_CHAT_ALLOW_IDENTITY_RESET=true \
node scripts/smoke_ops_chat_playwright.js
```

This proves dashboard login, Element login through Keycloak, same-origin Matrix
health from inside the browser, DM creation to `@agentic-ops:agentic-ops.local`,
ticket creation, and real agent handoff.

One-room Element marathon:

```powershell
$env:OPS_CHAT_URL="https://127.0.0.1:3303"
$env:OPS_CHAT_USER="demo_chat_marathon5"
$env:OPS_CHAT_PASSWORD="<from vault: demo_chat_marathon5>"
$env:PLAYWRIGHT_IGNORE_HTTPS_ERRORS="true"
$env:OPS_CHAT_MARATHON_MARKER="ops-chat-marathon-<unique>"
node scripts\smoke_ops_chat_workspace_marathon.js
```

This keeps one Matrix DM open and mixes harmless chat, current-information
questions, several operational tickets, cancellations, replacement work, scope
updates, and ticket summaries. It is the preferred proof that Ops Chat is not a
single latest-ticket parser path.

If the shared demo DM already has heavy scrollback, create a fresh demo user or
room before running the marathon. A noisy shared room can make Playwright parse
old messages and fail the test harness even when the backend behavior is
healthy.

Latest API-level multi-ticket proof:

- Marker `ops-chat-multiticket-1779338352`
- Watermelon purchase ticket `1384` created, then cancelled from the same chat
- Replacement pizza ticket `1385` created as a distinct request, not attached
  to cancelled ticket `1384`
- Urgent account ticket `1386` created from the same room and updated with a
  Keycloak SSO/MFA clarification
- Room summary answered without creating another ticket
- All synthetic tickets were cleaned up after proof

These tickets are also tagged as newer golden intake examples in the dashboard
`Demo Proofs` filter. Use them to demonstrate chat workspace continuity before
showing the heavier remediation/gating examples:

- `1384`: cancellation from chat after the requester changes scope
- `1385`: replacement request as a distinct ticket
- `1386`: unrelated urgent Identity & Access ticket from the same room, with
  Keycloak SSO/MFA clarification added as a user response

Detailed report for this hardening pass:

- `docs/OPS_CHAT_LIFECYCLE_TEST_REPORT_2026-05-21.md`
- Broad matrix: `ops-chat-enterprise-matrix-1779334693`, then focused repair
  `ops-chat-enterprise-matrix-1779336161`
- Scenario lifecycle: `ops-chat-scenarios-1779336984`
- Element dev artifacts: `ops-chat-dev-artifact-1779337398804`
- Multi-ticket lifecycle: `ops-chat-multiticket-1779338352`

Operational takeaways:

- Do not route by app-side structured parsing; the harness/toolbelt owns the
  decision.
- Do enforce bounded guardrails when the harness chooses an impossible/generic
  assignment for obvious enterprise domains.
- Do not treat a busy Matrix room as one ticket. Use explicit ticket ids,
  same-ticket language, or one-ticket room context for updates.
- Do not treat `instead` alone as a continuation signal. Replacement language
  should create replacement work.
- Use a fresh demo room/user for long UI marathon tests when the shared DM has
  heavy scrollback, or the Playwright harness can parse historical messages.

Requester/affected-user proof, latest live lab:

- Ticket `1284`
- Session `574`
- Requester `Demo Account 1 Demo`
- Affected user initially `Alice Example`, then corrected to
  `Charlie Example` by a follow-up in the same chat session
- iTop ref `703`
- Provider description preserved requester and affected-user lines
- No affected-user email was invented when the user did not provide one

Developer artifact proof:

```powershell
$env:OPS_CHAT_URL="https://127.0.0.1:3303"
$env:OPS_CHAT_USER="demo_chat_marathon5"
$env:OPS_CHAT_PASSWORD="<from vault: demo_chat_marathon5>"
$env:PLAYWRIGHT_IGNORE_HTTPS_ERRORS="true"
$env:OPS_CHAT_DEV_ARTIFACT_MARKER="ops-chat-dev-artifact-<unique>"
node scripts\smoke_ops_chat_dev_artifacts.js
```

This asks for Python, HTML, Markdown, and Bash artifacts through the real
Element UI. Expected result: every artifact says `Validation: passed`, renders
inside Element code blocks, and creates no tickets.

Latest Element artifact proof:

- Marker `ops-chat-dev-artifact-1779337398804`
- User `demo_account_1`
- Python, HTML, Markdown, and Bash all returned validated code blocks
- Ticket count delta was zero for every artifact request
- Extended artifact/upload proof:
  - Marker `hermes-ui-artifacts-1779355887`
  - Python, HTML, Markdown, Bash, MP4 animation, and Matrix file upload all
    passed through the real Element UI
  - Animation used `/root/.agents/skills/animation-video`
  - Upload was treated as untrusted input and returned as a validated Markdown
    artifact
  - Ticket count delta remained zero

Harness note:

- Health can show Hermes, Claude Code, and Codex at once. Codex is selected
  with the same `OPS_CHAT_AGENT_HARNESS` / request `harness` selector as the
  other harnesses.
- On 2026-05-21, Codex reached the AI proxy but the tested lab routes did not
  emit the required `ops_chat_tool.py` tool call within the one-hour window.
  Leave Hermes as the demo default until a tool-capable Codex route passes.

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
- Browser UI retest marker `ops-chat-ui-exec-1779283445` created ticket `1197`
  through Element/Keycloak, synced to iTop ref `616`, delivered a
  `/request-info` question back into Matrix, and recorded the user's chat reply
  as a ticket note.
- Broad enterprise retest marker `ops-chat-enterprise-matrix-1779305167`
  created tickets `1198`-`1248`, passed 50/50 no-spawn cases, and proved global
  search visibility.
- One-room Element marathon marker `ops-chat-marathon-1779299559` passed as
  `demo_chat_marathon5` with 16 turns and 15 visible working acknowledgements.
  It created Figma ticket `1276` and cancelled it, urgent GitLab/account ticket
  `1277`, mailbox ticket `1278`, distinct Adobe replacement ticket `1279`, and
  VPN ticket `1280` which was later cancelled. All five tickets synced to iTop
  refs `695`-`699`. Real agents `350`-`352` were spawned for active work and
  then stopped as smoke-owned cleanup, leaving active agents/processes empty.
- The marathon also verified two reliability fixes: compact retry after a
  missed final chat tool, and ticket-id recovery that refuses to trust stale
  model claims unless the user's current message explicitly referenced that
  ticket.
- Ticket clutter review found repeated watermelon test runs around
  `1264`-`1268`; current code suppresses same-message create retries and blocks
  harmless-chat recovery into the latest ticket. A clean
  watermelon/cancel/pizza proof should produce two tickets, not four.
- Live proof `ops-chat-two-ticket-1779328796` confirmed the current behavior:
  harmless price questions created no tickets, watermelon created `1286`,
  cancellation continued/cancelled `1286`, and pizza replacement created `1287`.
- Real scenario rerun later caught a follow-up confirmation opening a duplicate
  account ticket. The tool now refuses `create-ticket` for obvious follow-up
  text when room tickets already exist, forcing `continue-ticket`.
- If side-effect recovery finds a durable user-response/status note after a
  messy harness turn, it may reply as an update, not "I created ticket." If no
  durable note exists, recovery must not claim success; the harness should retry
  and call `continue-ticket`.
- Assignment group names are normalized by the Ops Chat tool before ticket
  creation or reassignment. If a model says `Delivery Gate`, `CI/CD`,
  `pipeline`, or `release`, the ticket should land in canonical `DevSecOps`
  rather than creating a one-off queue label.
- If the model says it created an Incident, User Request, or Change but the
  final tool result is messy, the API treats that as a ticket-work claim and
  attempts side-effect recovery instead of recording it as harmless chat.
- Developer artifact marker `ops-chat-dev-artifact-1780000005` passed as
  `demo_chat_marathon5`: Python, HTML, Markdown, and Bash artifacts were
  validated with `validate-artifact`, rendered as Element code blocks, and
  created zero tickets. A prior failed attempt showed the model claiming
  validation through `answer`; the API now rejects that path for dev artifacts.
- Real-agent prompt-guard marker `ops-chat-scenarios-1779307368` created ticket
  `1255`, spawned Hermes agent `333`, and verified that the actual process
  prompt included the canonical-ticket no-duplicate instruction.
- Smoke-owned agents `330`, `331`, `332`, and `333` were stopped after visible
  evidence, leaving active agents at `0`.
- The VPN real-agent case correctly asked a pre-ticket clarification instead of
  opening a premature ticket. This is expected when the missing answer changes
  route, scope, urgency, or ticket need.

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
- Element Web is served on `https://127.0.0.1:3303`; the old
  `http://127.0.0.1:3301` URL redirects there. Matrix client and OIDC
  callback traffic also work same-origin under `https://127.0.0.1:3303`;
  `https://127.0.0.1:3302` remains available for direct Synapse
  diagnostics.
- Playwright no-bypass browser proof passed as `demo_chat_live11`, including
  dashboard login, Element/Keycloak login, browser Matrix health, and Matrix DM
  marker `ops-chat-same-origin-playwright-1779261056`.
- That DM created ticket `908`, spawned Hermes agent `307` / task `304`, wrote
  model-turn audit evidence, asked the user which account/system was affected,
  and stopped cleanly in `awaiting_user_response` with no active process left.
- The direct bot-profile flow passed with marker
  `element-direct-agent-ui-1779283071`: open
  `https://127.0.0.1:3303/#/user/@agentic-ops:agentic-ops.local`, click
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
