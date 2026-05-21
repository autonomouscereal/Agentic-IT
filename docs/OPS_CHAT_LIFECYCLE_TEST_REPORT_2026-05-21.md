# Ops Chat Lifecycle Test Report - 2026-05-21

This report captures the live Ops Chat hardening pass for conversational
intake, ticket lifecycle behavior, provider sync, developer artifact rendering,
and cleanup. It is intentionally evidence-heavy so future agents can distinguish
verified behavior from assumptions.

## Scope

The goal was to test Ops Chat from the user perspective and from the dashboard
control-plane perspective:

- harmless/general chat should answer without tickets;
- current-information answers should not create tickets;
- one room can contain multiple unrelated operational requests;
- cancellations should target the correct ticket;
- replacement work should create a distinct ticket;
- follow-up user replies should become `user-response` notes;
- chat-created tickets should sync to iTop;
- the chat harness should choose assignment/routing through its toolbelt;
- platform guardrails should recover safely when the harness misses a final
  tool call;
- one-off developer artifacts should validate and render as code blocks without
  creating tickets;
- synthetic tickets and smoke-owned agents should be cleaned up.

## Live Environment

Reference deployment:

- Dashboard: `https://192.168.50.222:25443`
- Ops Chat / Element: `https://192.168.50.222:3303`
- Dashboard internal API: `http://127.0.0.1:25480`
- AI proxy: `http://127.0.0.1:4001`
- Active chat harness: Hermes
- Active chat model during the proof: `deepseek/deepseek-v4-flash`
- Ticket provider: iTop

Secrets used during testing came from the local/server vaults. No token or
password belongs in this report.

## Fixes Made

### Structured Result Preservation

Hermes can occasionally create a ticket and then call the `answer` tool in the
same lightweight chat turn. That made the visible result look like general chat
even though a ticket had been created.

The toolbelt now preserves earlier structured `ticket`, `ticket-update`, and
`artifact` results. The API can also recover the last structured action from
the action log if a later general reply claims ticket work.

### Bounded Existing-Ticket Fallback

One live lifecycle run created and synced a phishing ticket, but the follow-up
message returned the generic harness failure because Hermes did not call the
required final `continue-ticket` tool.

The repair is deliberately bounded:

- the harness still gets normal attempts first;
- fallback applies only when the message clearly looks like an
  update/cancel/scope-change;
- fallback requires exactly one linked room ticket or an explicit linked
  `ticket #N` reference;
- harmless chat and multi-ticket rooms are not silently attached to the latest
  ticket;
- fallback writes a durable `user-response` note;
- cancellation-like fallback updates set ticket status to `cancelled`.

### Replacement Request Handling

The first clean multi-ticket proof caught a bad user experience: after
watermelon was cancelled, "instead order pizza" continued the cancelled
watermelon ticket.

The toolbelt no longer treats bare `instead` as an automatic follow-up signal.
Explicit same-ticket language still continues a ticket. Replacement language
such as "instead put in a new ticket" creates distinct work.

### Enterprise Routing Guardrails

The broad 50-case matrix exposed five routing gaps:

- offboarding -> Identity & Access
- restore deleted file from backup -> Infrastructure Operations
- Nuclei CI/CD finding -> DevSecOps
- policy exception/risk acceptance -> Compliance & Audit
- SLA report -> Compliance & Audit

The chat harness still chooses through the toolbelt, but obvious enterprise
domain text is now normalized by the toolbelt when the model selects a generic
or conflicting group.

## Live Proofs

### Broad Enterprise Matrix

Command shape:

```bash
python3 scripts/smoke_ops_chat_enterprise_matrix.py http://127.0.0.1:25480 \
  --strict-routing --require-provider-sync --cleanup
```

Initial marker: `ops-chat-enterprise-matrix-1779334693`

Result:

- 50 cases executed.
- 45 passed on first run.
- Tickets `1320`-`1368` were created and synced to iTop where tickets were
  created.
- Five misses were recorded and then repaired:
  offboarding, restore-file, Nuclei finding, policy exception, SLA report.
- No active agents or processes remained after cleanup.

Focused repair marker: `ops-chat-enterprise-matrix-1779336161`

Focused rerun result:

| Case | Ticket | iTop Ref | Expected Group | Result |
| --- | ---: | ---: | --- | --- |
| offboarding | 1369 | 788 | Identity & Access | passed |
| restore-file | 1370 | 789 | Infrastructure Operations | passed |
| nuclei-finding | 1371 | 790 | DevSecOps | passed |
| policy-exception | 1372 | 791 | Compliance & Audit | passed |
| sla-report | 1373 | 792 | Compliance & Audit | passed |

All five synthetic tickets were cancelled during cleanup.

### Scenario Lifecycle Smoke

Command shape:

```bash
python3 scripts/smoke_ops_chat_scenarios.py http://127.0.0.1:25480 --cleanup
```

Failed marker before fix: `ops-chat-scenarios-1779336299`

- Created tickets `1374`-`1377`.
- Failed because a phishing follow-up did not continue ticket `1377`.
- Synthetic tickets were cancelled immediately.

Passing marker after fix: `ops-chat-scenarios-1779336984`

Result:

- General chat answered without a ticket.
- Current-information web answer returned without a ticket.
- Cat follow-up used chat memory and did not create a ticket.
- Account lockout ticket `1378` routed to Identity & Access.
- Software request ticket `1379` routed to Endpoint Support.
- VPN ticket `1380` routed to Network Operations.
- Phishing ticket `1381` routed to Security Operations and accepted the
  follow-up as a durable `user-response`.
- Delivery gate ticket `1382` routed to DevSecOps.
- All synthetic tickets were cancelled during cleanup.

### Developer Artifact UI Proof

Command shape:

```bash
node scripts/smoke_ops_chat_dev_artifacts.js
```

Marker: `ops-chat-dev-artifact-1779337398804`

Result through real Element UI and Keycloak as `demo_account_1`:

| Artifact | Validation | Ticket Delta |
| --- | --- | ---: |
| Python | passed | 0 |
| HTML | passed | 0 |
| Markdown | passed | 0 |
| Bash | passed | 0 |

Element rendered the returned artifacts as code blocks. No ticket was created
for pure one-off developer artifact asks.

### Multi-Ticket Lifecycle

Command shape: direct dashboard Ops Chat endpoint, same endpoint used by the
Matrix bridge.

Marker: `ops-chat-multiticket-1779338352`

One chat session performed:

1. General "why is the sky blue" question.
2. Watermelon purchase request for Alice.
3. Cancel watermelon because Alice is allergic.
4. Replacement pizza request.
5. Urgent account lockout request.
6. Clarify account issue is Keycloak SSO/MFA.
7. Ask what tickets are being tracked in the room.

Result:

| Work | Ticket | Behavior |
| --- | ---: | --- |
| Watermelon purchase | 1384 | created, then cancelled |
| Pizza replacement | 1385 | created as distinct replacement work |
| Urgent account lockout | 1386 | created, then updated with SSO/MFA clarification |
| Room summary | none | answered without creating another ticket |

All three synthetic tickets were cancelled during cleanup.

### No Active Agent Leakage

After live tests and cleanup:

```json
{"agents":[],"count":0}
```

and:

```json
{"processes":[],"active_processes":[]}
```

## Test Harness Caveat

A later Element one-room marathon attempt with marker
`ops-chat-marathon-1779337715245` failed as a test-harness/UI-history issue,
not as a product proof:

- it reused the busy `demo_account_1` DM;
- Element scrollback included older messages and previous dev-artifact output;
- the Playwright script parsed noisy historical content;
- global search found no tickets for that marker, so no cleanup ticket action
  was needed.

For future full UI marathons, use a fresh demo user or fresh room, or add a
room reset step before running `scripts/smoke_ops_chat_workspace_marathon.js`.

## Commands To Reproduce

Set the dashboard service token from the live `.env` on the server, then run:

```bash
python3 scripts/smoke_ops_chat_scenarios.py http://127.0.0.1:25480 --cleanup
python3 scripts/smoke_ops_chat_enterprise_matrix.py http://127.0.0.1:25480 \
  --strict-routing --require-provider-sync --cleanup
```

For real-agent proofs, use one or more bounded cases:

```bash
python3 scripts/smoke_ops_chat_scenarios.py http://127.0.0.1:25480 \
  --agent-only --spawn-agent --agent-case account-lockout --agent-timeout 600 --cleanup
python3 scripts/smoke_ops_chat_scenarios.py http://127.0.0.1:25480 \
  --agent-only --spawn-agent --agent-case delivery-gate --agent-timeout 600 --cleanup
```

For Element UI artifact rendering:

```powershell
$env:OPS_CHAT_URL="https://192.168.50.222:3303"
$env:OPS_CHAT_USER="<demo chat user>"
$env:OPS_CHAT_PASSWORD="<from vault>"
$env:PLAYWRIGHT_IGNORE_HTTPS_ERRORS="true"
$env:OPS_CHAT_DEV_ARTIFACT_MARKER="ops-chat-dev-artifact-<unique>"
node scripts\smoke_ops_chat_dev_artifacts.js
```

## Acceptance Criteria

Before a demo, Ops Chat should satisfy:

- dashboard `/health` returns `ok`;
- `/api/ops-chat/matrix/health` reports Matrix Synapse + Element;
- harmless chat does not create tickets;
- current-information chat does not create tickets;
- operational chat creates provider-synced tickets;
- follow-up chat records `user-response` notes;
- cancellations cancel the intended ticket;
- replacement requests create distinct tickets;
- broad matrix run passes with provider sync;
- dev artifacts render as code blocks and create no tickets;
- active agents/processes are empty after cleanup.

