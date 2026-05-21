# Ops Chat Playwright Bundle

Last updated: 2026-05-21.

This is the canonical browser-test pattern for Agentic Operations Ops Chat.
Future UI tests should model this bundle instead of rediscovering Element,
Keycloak, Matrix, and chat-room quirks from scratch.

## Canonical Script

Use:

```powershell
node scripts\smoke_ops_chat_playwright.js
```

The script is intentionally self-contained. It includes:

- dashboard login through the HTTPS edge;
- Element login through Keycloak;
- same-origin Matrix health probe with `fetch("/_matrix/client/versions")`;
- Element prompt handling for:
  - `Confirm encryption setup`;
  - `Verify this device`;
  - `Confirm your digital identity`;
  - `Are you sure? Without verifying...`;
  - first-contact `Start a chat with this new contact`;
- optional deterministic room navigation with `OPS_CHAT_ROOM_ID`;
- safe ticket-link detection that accepts either a new ticket or an
  agent-selected existing ticket update;
- screenshot capture via `PLAYWRIGHT_SCREENSHOT_DIR`;
- no secret printing.

## Demo Defaults

For the current lab demo account:

```powershell
$env:DASHBOARD_URL="https://192.168.50.222:25443"
$env:DASHBOARD_USER="demo_account_1"
$env:DASHBOARD_PASSWORD="<from vault: demo_account_1>"
$env:OPS_CHAT_URL="https://192.168.50.222:3303"
$env:OPS_CHAT_USER="demo_account_1"
$env:OPS_CHAT_PASSWORD="<from vault: demo_account_1>"
$env:OPS_CHAT_ROOM_ID="!zSTElAvfSUDmAKZSWm:agentic-ops.local"
$env:PLAYWRIGHT_IGNORE_HTTPS_ERRORS="true"
$env:OPS_CHAT_SEND_MESSAGE="true"
$env:OPS_CHAT_ALLOW_IDENTITY_RESET="false"
$env:OPS_CHAT_TEST_OUTBOUND="false"
$env:OPS_CHAT_MARKER="demo-reliability-<unique>"
$env:OPS_CHAT_TEST_MESSAGE="Open a fresh low-risk demo reliability ticket to verify Ops Chat can create work and assign an agent. Keep the work demo-safe and record the marker $env:OPS_CHAT_MARKER."
node scripts\smoke_ops_chat_playwright.js
```

`OPS_CHAT_ALLOW_IDENTITY_RESET=false` is deliberate. Demo smoke tests should not
reset Matrix identity or try to complete encrypted-chat setup. Ops Chat does not
need Matrix E2EE for this demo proof; the platform proof is identity, bridge
delivery, dashboard linkage, and agent response.

## Expected Pass Signal

The script should print JSON like:

```json
{
  "status": "passed",
  "dashboard": {"url": "https://192.168.50.222:25443/", "user": "demo_account_1"},
  "ops_chat": {"url": "https://192.168.50.222:3303/#/home", "user": "demo_account_1"},
  "message": {"marker": "demo-reliability-...", "ticketId": 1444},
  "outbound": null
}
```

The `ticketId` does not have to be brand new. Ops Chat is agent-decision-first,
so a long-lived room may continue a relevant existing ticket. For bridge
reliability, a visible ticket-linked agent response is the pass condition. For
clean demo storytelling, use a fresh Matrix user/room or explicitly ask to
open a new ticket.

## Latest Live Proof

2026-05-21:

- Settings quick controls set `codex-primary`, fast mode on, low reasoning,
  and `max_concurrent_agents=5`.
- Playwright logged into Element through Keycloak as `demo_account_1`.
- The script skipped Matrix verification/encryption prompts.
- It used room `!zSTElAvfSUDmAKZSWm:agentic-ops.local`.
- It sent marker `demo-reliability-1779401709`.
- It received a ticket-linked response on ticket `1444`.
- Runner health after the test: Codex OAuth `logged_in`, proxy `ok`,
  `worker_count=5`, `queued_depth=0`, active agents `0`.

Additional bulletproofing pass, same day:

- Authenticated dashboard Playwright crawl visited Overview, Tickets, Intake,
  Agents, Changes, Workflows, Postmortems, CI/CD, Learning, Tools, Setup,
  Access, Audit, and Settings.
- The crawl found no blank pages and no browser console errors.
- The crawl exercised `Settings -> Demo Agent Controls`, saved Codex fast mode,
  low reasoning, and `5` active agents, then verified runner health reflected
  the values.
- Ops Chat login-only smoke passed with same-origin Matrix health `200`.
- Ops Chat message smoke sent marker `demo-bulletproof-1779402310` through
  Element, into the bridge, through the dashboard, and to a real Codex worker.
- Agent `406` / task `403` completed ticket `1444`, wrote a public
  `external_ref=ops-chat-closure` note, resolved the ticket, and left active
  agents at `0`.

## Do Not Regress

- Do not click **Confirm** for encryption setup in demo smoke tests.
- Do not reset digital identity during normal Ops Chat smoke.
- Do not require every room message to create a new ticket.
- Do not bypass Element/Keycloak with direct API calls when the goal is user
  experience validation.
- Do not treat a long first-contact/profile path as the preferred demo path
  when a known room id exists.
