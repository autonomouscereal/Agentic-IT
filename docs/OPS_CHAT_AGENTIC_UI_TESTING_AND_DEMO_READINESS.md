# Ops Chat Agentic UI Testing And Demo Readiness

Last updated: 2026-05-22.

This document is the checkpoint for the current Ops Chat workstream: Element
UI, Matrix/Synapse, Keycloak login, chat-to-agent routing, ticket sync,
reassignment/escalation, and user-facing ticket updates. It exists so future
agents do not have to reconstruct the intended behavior from old smoke runs.

For the detailed 2026-05-21 hardening evidence, see
`docs/OPS_CHAT_LIFECYCLE_TEST_REPORT_2026-05-21.md`.
For the exact reusable Playwright login/verification-skip bundle, see
`docs/OPS_CHAT_PLAYWRIGHT_BUNDLE.md`.

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

## Current Demo Readiness Snapshot

2026-05-21 final pre-demo pass:

- Dashboard UI login and navigation passed through Playwright.
- Dashboard pages verified nonblank: Overview, Tickets, Intake, Agents,
  Changes, Workflows, Postmortems, CI/CD, Learning, Tools, Setup, Access,
  Audit, and Settings.
- Browser console errors during the dashboard crawl: none.
- Settings quick controls saved `codex-primary`, fast mode on, low reasoning,
  and `max_concurrent_agents=5`; `/api/agents/runner-health` confirmed
  `worker_count=5`, Codex OAuth `logged_in`, and proxy `ok`.
- Element/Ops Chat login-only smoke passed through Keycloak and same-origin
  Matrix health returned `200`.
- Element/Ops Chat message smoke used
  `OPS_CHAT_ROOM_ID=!zSTElAvfSUDmAKZSWm:agentic-ops.local`, skipped Matrix
  verification/encryption prompts, sent marker `demo-bulletproof-1779402310`,
  received a ticket-linked response on ticket `1444`, and spawned real Codex
  worker agent `406`.
- Agent `406` completed task `403`, wrote a public `ops-chat-closure` note,
  resolved ticket `1444`, and active agents returned to `0`.
- Additional UI-intake pass proved the demo-critical paths:
  - general no-ticket answer marker `demo-general-1779402811321`;
  - no-ticket developer checklist marker `demo-dev-1779402811321`;
  - tracked work ticket `1447` / iTop `859` marker
    `demo-ticket-1779402811321`, completed by Codex agent `407`;
  - dashboard-to-chat requester-response marker
    `demo-outbound-1779403016817`, processed by continuation agent `408`;
  - mixed answer-plus-ticket intake ticket `1448` / iTop `860` marker
    `demo-intake-1779403347387`, completed by Codex agent `409`.

2026-05-21 extreme intake stress pass:

- Real Element artifact run marker `demo-extreme-artifacts-1779382600`
  created and validated Python, HTML, Markdown, Bash, MP4 animation, and
  uploaded-file Markdown summary artifacts through Codex fast/low with zero
  ticket creation.
- Combined single-message artifact run marker
  `demo-combined-artifacts-1779383444` created a Python ASCII chart script and
  an MP4 animation in one no-ticket chat turn; both validated and rendered in
  Element without code-block mangling.
- Three simultaneous Element browser jobs created separate tracked work:
  ticket `1453` for demo flowers/procurement, ticket `1454` for a safe
  password reset rehearsal, and ticket `1455` for a synthetic Wazuh SIEM alert.
  The queue handled concurrent Codex workers and returned to idle.
- The procurement ticket intentionally blocked on missing real purchase/vendor
  details; password reset reached the guarded approval path; SIEM stopped at a
  real Wazuh access wall. These are acceptable demo outcomes because the
  platform did not invent approvals or bypass access.
- Triple-ingress test ran chat intake, report-phish, and iTop-origin alert
  ingestion together. Chat created ticket `1458` and stopped at access for CEO
  SSO support; report-phish ticket `1463` resolved with four completed
  approval-gated containment actions; direct iTop alert `874` synced into
  dashboard ticket `1464`, auto-assigned Codex agent `420`, and created access
  child ticket `1465`.
- A prompt/runtime gap was fixed during the stress pass: agents now explicitly
  complete approved access changes before requesting `/api/agents/{id}/vault/lease`,
  because completion activates the per-agent scoped lease. Approval alone is
  not enough.

Known live-demo caveat: the long-lived `demo_account_1` room may continue the
existing queue-health ticket instead of opening a fresh one. That is acceptable
for bridge/agent reliability proof. For a pristine story, use a fresh Matrix
demo user/room or explicitly phrase the request as "open a new ticket".

2026-05-22 severe Playwright regression pass:

- Browser-level Element login and Matrix health passed against
  `https://192.168.50.222:3303` using the same Keycloak/OIDC path used in the
  live demo.
- Focused fresh-ticket smoke marker `fresh-ticket-20260522005321` created
  ticket `1513` / iTop `915`, delivered an outbound requester question back to
  Matrix, recorded the chat reply as a `user-response` ticket note, and the
  worker stopped at a real endpoint-management access barrier with child access
  ticket `1514` / gate `364`.
- Full long-room marathon marker `marathon-20260522005517` verified general
  chat, follow-up memory, small ASCII output, current-info answer formatting,
  working acknowledgements, multiple operational asks, cancellation, room ticket
  summary, iTop sync, and real access gates. It also reproduced stale-room
  over-continuation: an unrelated Figma install was attached to an older GIMP
  ticket in a noisy long-lived room.
- The chat-agent prompt was tightened at the agent decision boundary, not with a
  hidden classifier. Continuation now explicitly means the same ticket id or the
  same work object; different person, device, software title, mailbox, system,
  site, repository, or purchase is new operational work.
- Focused stale-room regression marker `reuse-regression-20260522010734` passed:
  the agent created separate tickets `1525` / iTop `927` for LibreOffice/Avery
  and `1526` / iTop `928` for Figma/Jeff, verified affected-user metadata, and
  both synced to iTop.
- Queue settled after the stress pass: `/api/agents/active` returned zero active
  agents, `worker_count=5`, and `queued_depth=0`.
- Health after the pass: dashboard HTTP/TLS `/health` returned `200`, Element
  returned `200`, and Matrix client versions returned `200`.

Updated testing notes:

- `scripts/smoke_ops_chat_playwright.js` now tolerates current polished wording
  for requester follow-up acknowledgements and retries the ticket-context note
  check briefly so it does not race the write path.
- `scripts/smoke_ops_chat_workspace_marathon.js` now has
  `OPS_CHAT_MARATHON_MODE=ticket-reuse-regression` for a fast two-turn proof
  that unrelated software requests become separate tickets in a noisy room.
- When running Playwright inside the API container against the LAN HTTPS URLs,
  set `PLAYWRIGHT_IGNORE_HTTPS_ERRORS=true`. For direct Node `fetch()` checks
  against the dashboard API, prefer `DASHBOARD_URL=http://127.0.0.1:8000` inside
  the API container or set `NODE_TLS_REJECT_UNAUTHORIZED=0` only for the smoke
  process.

Current residual note: older stress attempts left duplicate software-install
and access-request demo tickets between `1509` and `1524`. They are synced and
safe behind access gates, but they are not the golden examples. Use the newer
verified pair `1525` and `1526` when demonstrating stale-room correction.

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

Mixed requests are allowed in a single agent turn. If a message asks for both
a harmless answer and operational work, the harness should answer the harmless
or current-information part in a reply file, then finish with `create-ticket`
or `continue-ticket` using `--reply-file mixed_reply.md`. Example: "deploy a
bunnies web page and tell me the price of tea in China" should return the tea
answer to the user and also open/assign the bunnies deployment ticket. The
Matrix bridge appends the dashboard ticket and agent identifiers after the
tool result.

Once a ticket worker finishes an Ops Chat-originated ticket, the worker agent is
responsible for the final user response. Before closing, it must write a public
agent note with the outcome, access URL or artifact/report when applicable,
validation evidence, and follow-up status. The note must use `source=agent`,
`visibility=public`, and `external_ref=ops-chat-closure`. The outbound bridge
delivers that explicit agent-authored closure note to Matrix. Generic
ticket-status messages remain control-plane fallbacks, not the desired final
user experience.

Agents may also send requester-facing progress or result notes before closure.
For Ops Chat-originated tickets, the ticket service automatically marks
agent-authored `visibility=user` or `visibility=public` notes with
`external_ref=ops-chat-agent-note` when the agent does not provide a more
specific `ops-chat-*` external reference. This keeps the agent in charge of when
to update the requester while preventing old unrelated public notes from being
backfilled into Matrix.

Matrix delivery hardening note: the application-service bridge awaits inbound
event processing before acknowledging Synapse transactions. If dashboard
handoff fails, the bridge returns HTTP 500 so Synapse can retry instead of
silently dropping the user's message. Agent-authored closure notes render in
Matrix as "Agent completed this request..." and progress notes render as
"Agent update..." for demo readability.

The application may recover side effects and enforce safety, but it should not
replace the agent's decision with a brittle custom JSON classifier.

This is not optional. Future changes must preserve the agent-owned decision
model described in `docs/AGENT_DECISION_MODEL.md`. Add context, tools, tests,
and real boundaries; do not move routing, old-vs-new ticket selection,
assignment, or user-communication decisions into a rigid app parser unless a
specific safety failure requires a narrow, documented fallback.

Important room behavior:

- A Matrix room is a conversation, not a ticket container. One room can contain
  harmless chat, several tickets, cancellations, and replacement requests.
- The dashboard records recent linked tickets and passes them to the harness as
  context. The harness must decide per message whether to answer, create, or
  continue.
- If the user explicitly asks for a fresh/new/separate ticket or says to open,
  file, create, or put in a ticket, the toolbelt allows `create-ticket` even
  when the same sentence contains words like "update" or "keep me updated."
  This avoids stale-room false positives while preserving the agent's ownership
  of old-vs-new decisions.
- If the agent still continues an old ticket too often, treat that as a prompt,
  context, or skill improvement. Do not solve it with a broad terminal-ticket
  prohibition that blocks legitimate agent decisions.
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
- `opened_by_name` / `opened_by_email` when the platform or agent opened work
  on behalf of someone else
- `requester_name` / `requester_email` for the person asking for the work
- `affected_user_name` / `affected_user_email` for the person, account,
  mailbox, endpoint, service, or app impacted by the work
- `provider = itop`
- `provider_ref` / `itop_ref`
- `provider_sync_status = synced`
- `external_url` pointing to iTop details
- Ops Chat agent-created note
- recent chat context preserved in dashboard evidence

Requester and affected user can differ. For example, if Demo Account asks for
software for Alice, the ticket should show Demo Account as requester and Alice
as affected user. Do not invent affected-user email addresses; leave the email
blank unless the user or identity provider provides it. Provider descriptions
use `Name (email)` instead of angle brackets so iTop and other HTML-rendering
ticket systems preserve the contact block.

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
| Requester / affected-user sync | ticket `1284`, session `574`, requester `Demo Account 1 Demo`, affected user `Alice Example`, iTop ref `703`, provider description preserved requester and affected user; follow-up changed affected user to `Charlie Example` without creating a duplicate ticket |
| Ticket clutter regression | historical tickets `1264`-`1267` reviewed; repeated Element test runs plus a too-loose recovery path made the room look noisy. The platform now idempotently suppresses duplicate create-ticket retries by `session_id + message_hash` and refuses latest-ticket recovery for harmless chat. Live proof `ops-chat-two-ticket-1779328796` created exactly two tickets: `1286` cancelled and `1287` replacement. |
| Scenario matrix rerun | marker `ops-chat-scenarios-1779332898`, tickets `1311`-`1315`, general chat, current-info web answer, cat memory, account, software, VPN, phishing, and CI/CD all passed; synthetic tickets were cancelled after proof |
| Real agent account lockout | marker `ops-chat-scenarios-1779334013`, ticket `1318`, Hermes agent `358`, iTop sync, user-facing clarification/checkpoint, cleanup stopped only the smoke-owned agent |
| Real agent delivery gate | marker `ops-chat-scenarios-1779334281`, ticket `1319`, Hermes agent `359`, iTop sync, transient provider retries were recorded cleanly, DevSecOps progress note written, cleanup stopped only the smoke-owned agent |
| Broad enterprise matrix | marker `ops-chat-enterprise-matrix-1779334693`, tickets `1320`-`1368`, 45/50 initial pass with iTop sync; misses were offboarding, restore-file, Nuclei CI/CD, policy exception, and SLA report |
| Focused matrix repair | marker `ops-chat-enterprise-matrix-1779336161`, tickets `1369`-`1373`, 5/5 passed with iTop sync and cleanup after routing guardrail patch |
| Lifecycle regression | marker `ops-chat-scenarios-1779336984`, tickets `1378`-`1382`, general chat, web/current info, cat memory, account, software, VPN, phishing follow-up, and delivery gate all passed with cleanup |
| Developer artifact UI proof | marker `ops-chat-dev-artifact-1779337398804`, user `demo_account_1`, Python/HTML/Markdown/Bash rendered as Element code blocks, validation passed, and zero tickets were created |
| Multi-ticket lifecycle | marker `ops-chat-multiticket-1779338352`, one chat session created watermelon ticket `1384`, cancelled it, created distinct pizza ticket `1385`, created urgent account ticket `1386`, updated `1386`, summarized room tickets, then cleaned all three |
| Mixed answer plus ticket | ticket `1418`, session `716`, Codex agent `385` / task `382`; one chat message asked for a static otter web page deployment and the price of tea in China. The chat reply answered the tea-price portion, created and assigned the Platform Operations ticket, opened approval gate `314`, published `https://192.168.50.222:25443/published/otters-1418/`, and finished with zero active agents. |

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
- A later ticket-clutter review found the same recovery family could also reuse
  the latest room ticket for a harmless current-information question. That path
  is now gated to operational-looking ticket requests only. `create-ticket`
  calls also carry a message hash, and `/api/tickets` returns the existing
  active Ops Chat ticket on same-message retry instead of creating and syncing a
  duplicate provider ticket.
- A real scenario rerun later caught a different duplicate path: a
  follow-up/confirmation message in a room with an account ticket used
  `create-ticket` instead of `continue-ticket`. The tool now rejects
  follow-up/update/cancel/reassign-shaped create attempts when room tickets
  already exist, forcing the harness to continue the correct ticket.
- The same rerun showed a recovery presentation issue: the ticket had the
  correct `user-response` note, but the room reply could still say "I created
  ticket" after recovering the side effect. Session-side recovery now formats
  follow-up side effects as ticket updates.
- A later rerun showed the opposite risk: the room could say "updated" without
  the `user-response` note existing. Recovery now refuses to claim an update
  unless the durable note/status side effect is present, forcing the harness to
  retry with `continue-ticket`.
- Developer artifact testing exposed the same class of issue for code: the
  harness could claim it had validated a script while using the general answer
  path. Dev artifact asks now require `validate-artifact`; if the harness calls
  `answer` instead, the turn is rejected and retried with an artifact-only
  prompt.
- Real-agent reruns exposed a structured-result overwrite pattern: Hermes could
  create the ticket and then call `answer`, causing the final result file to
  look like general chat. The toolbelt now preserves earlier ticket/update/
  artifact results, and the API can recover the last structured action from
  the action log if a later general reply claims ticket work.
- Broad matrix and scenario scripts now support `--cleanup`, and the enterprise
  matrix supports `--require-provider-sync`, so breadth tests can prove iTop
  sync without leaving active demo clutter.
- A 50-case enterprise matrix on marker `ops-chat-enterprise-matrix-1779334693`
  exposed five routing gaps: offboarding, restore-from-backup, Nuclei CI/CD,
  policy exception, and SLA report. Guardrails now normalize those obvious
  enterprise domains while keeping the chat harness in control of the turn.
  Focused rerun marker `ops-chat-enterprise-matrix-1779336161` passed 5/5.
- Scenario marker `ops-chat-scenarios-1779336299` exposed a follow-up turn
  where the harness skipped the required final `continue-ticket` tool. The
  platform now has a bounded no-tool fallback only for obvious existing-ticket
  updates in a single-ticket room or when the user explicitly names a linked
  ticket id. Scenario marker `ops-chat-scenarios-1779336984` passed after this
  repair.
- Multi-ticket marker `ops-chat-multiticket-1779338352` proved that
  "instead put in a new ticket" creates replacement work instead of continuing
  a cancelled ticket. The word "instead" is no longer treated as an automatic
  existing-ticket update by itself; explicit "same ticket"/"keep the same"
  language still routes to continuation.
- A later `demo_account_1` Element marathon attempt failed as a test-harness
  problem because the shared DM had a large old scrollback and the output
  flooded with historical messages. It created no tickets. For future long UI
  marathons, use a fresh demo user/room or add a room reset step before running
  the Playwright script.

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
python3 scripts/smoke_ops_chat_scenarios.py http://127.0.0.1:25480 --cleanup
python3 scripts/smoke_ops_chat_enterprise_matrix.py http://127.0.0.1:25480 --strict-routing --require-provider-sync --cleanup
```

Real agent cases:

```bash
export DASHBOARD_SERVICE_TOKEN=<runtime secret>
python3 scripts/smoke_ops_chat_scenarios.py http://127.0.0.1:25480 --agent-only --spawn-agent --agent-case account-lockout --agent-timeout 600 --cleanup
python3 scripts/smoke_ops_chat_scenarios.py http://127.0.0.1:25480 --agent-only --spawn-agent --agent-case delivery-gate --agent-timeout 600 --cleanup
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

## 2026-05-22 Demo Blocker Regression

Validated fixes:

- Ops Chat ticket closure delivery: ticket-agent `agent-resolution` notes with
  `visibility=user/public` on Ops Chat tickets are marked
  `external_ref=ops-chat-closure` and delivered to Matrix as
  `Agent completed this request...`. Backfill verified ticket `1497` note
  `5187` was delivered into `ops_chat_messages` as outbound event `note:5187`.
- Multi-artifact chat output: repeated `validate-artifact` calls now append
  instead of overwriting. Real Element/Playwright run
  `demo-fix-artifacts-20260521234612` passed Python, HTML, Markdown, Bash, and
  combined Python + Remotion MP4 cases with zero ticket creation.
- Roundcube Report Phish handoff: a fresh email reported through the real
  Roundcube button created dashboard ticket `1500`, synced iTop ref `902`,
  auto-assigned Codex agent `428`, recorded passive triage notes, and opened
  manual approval gate `357` before mailbox/quarantine validation.

Regression commands:

```bash
python -m py_compile api/routes/ops_chat.py api/services/ticket_service.py
python -m py_compile reference_skills/keycloak-mailcow-bridge/scripts/deploy_mailcow_api.py
node --check scripts/smoke_ops_chat_dev_artifacts.js
python -m pytest tests/test_ops_chat_ticket_lifecycle_regressions.py tests/test_ticket_service_provider_sync.py -q
```

Real UI checks should be run from the API container where Playwright is already
installed. Use Element on `https://host.docker.internal:3303` and Roundcube on
`http://host.docker.internal:2581/webmail/`; never replace either with a shim
for demo acceptance.

## Known Rough Edge

Element first-login and first-contact prompts are stateful and can make browser
automation flaky even when the real system is working. The smoke script handles
the common prompts, but if a prompt blocks a run, inspect the body text and add
a narrow dismissal for that prompt. Do not replace Element with a shim to make
testing easier; the point is to prove the real client path.
