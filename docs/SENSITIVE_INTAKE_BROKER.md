# Sensitive Intake Broker

The sensitive intake broker is the platform boundary for user-provided secrets
and protected personal information.

It exists because chat, email, ticket descriptions, audit logs, provider sync,
agent prompts, and memory are text paths. Text paths are useful for traceability,
but they are the wrong place for SSNs, dates of birth, temporary passwords, API
keys, recovery codes, HR data, financial data, or customer-protected values.

## Contract

- Agents may ask for protected fields by label, type, and purpose.
- Users submit values through a secure broker form, not chat or ticket text.
- Values are encrypted in `sensitive_intake_values`.
- Agents receive request references and value references only.
- Ticket descriptions, ticket notes, Ops Chat messages, provider payloads, event
  logs, and audit views display only references/status.
- Defensive redaction still runs if a user pastes a value into chat by mistake.
- Required fields are validated before any value is stored. Incomplete
  submissions record a rejected audit event but store no partial values.
- Form tokens are one-submit. A correction or additional value set requires a
  new secure intake request.
- Attachment metadata such as filenames, storage refs, Matrix URLs, and custom
  metadata is redacted before it is persisted or linked to tickets.
- Provider adapters must resolve sensitive references server-side inside
  approval-gated actions. Do not expose a generic "read secret" endpoint to
  agents.

## Tables

- `sensitive_intake_requests`: one dynamic form request with purpose, requested
  fields, requester/session/ticket linkage, expiry, and submission status.
- `sensitive_intake_values`: encrypted values keyed by `value_ref`, plus field
  label/type, hash/fingerprint, length, submitter, and status.
- `sensitive_intake_events`: audit-safe process events such as requested,
  submitted, expired, and automatic redaction.

Raw values are never returned by the broker API.

## Agent Flow

1. User asks for work.
2. Agent decides it needs protected fields.
3. Agent calls:

```bash
python ops_chat_tool.py request-sensitive-fields \
  --purpose "new user onboarding" \
  --field "legal_name|freeform_sensitive|Full legal name|required" \
  --field "dob|dob|Date of birth|required" \
  --field "ssn|ssn|SSN|required"
```

4. The user receives a secure form link.
5. The user submits the form.
6. The broker stores encrypted values and records audit-safe events.
7. Chat/ticket history shows only field labels, references, status, and
   timestamps.
8. A downstream provider action may consume references after real authorization
   gates are satisfied.

The browser form uses native `required` controls for immediate user feedback.
The API still enforces the same checks server-side before storing anything.

## Brokered Action Adapter

The broker is not only a form. It is a handoff boundary for server-side
provider adapters.

Current implemented adapter:

`POST /api/access/users/secure-local-account`

Purpose: create or update a local Agentic Operations dashboard login from a
submitted secure-intake request.

Input:

```json
{
  "request_ref": "sir_...",
  "username": "secure_e2e_example",
  "display_name": "Secure E2E Example",
  "email": "optional@example.invalid",
  "role": "auditor",
  "enabled": true
}
```

Behavior:

- Resolves the submitted credential value inside the API process only.
- Hashes the password with the dashboard password hasher.
- Creates or updates the dashboard user and role.
- Logs only refs/status/evidence.
- Returns `raw_values_returned: false`; agents never receive the password.
- Requires the same access-admin boundary as the normal `/api/access/users`
  management endpoints.

Normal `/api/access/users` output intentionally omits `password_hash` and any
raw credential material.

## Defensive Redaction

The broker also protects accidental pastes. The following paths call the
redaction service before normal storage:

- inbound Ops Chat user messages
- Ops Chat transcript writes
- ticket title/description creation
- ticket notes
- provider push descriptions
- event-log details

Example input:

```text
Set up Bob. SSN 123-45-6789 password: SuperSecret123
```

Stored text:

```text
Set up Bob. SSN <sensitive:ssn:siv_...> password: <sensitive:credential:siv_...>
```

The raw values are encrypted in the broker and are absent from normal logs.

## Configuration

Set these in runtime or vault-backed environment:

```env
DASHBOARD_PUBLIC_URL=https://agentic-ops.example.local:25443
SENSITIVE_INTAKE_MASTER_KEY=<vault:sensitive-intake-master-key>
SENSITIVE_INTAKE_EXPIRES_HOURS=24
SENSITIVE_INTAKE_MAX_TEXT_SCAN_CHARS=20000
```

`SENSITIVE_INTAKE_MASTER_KEY` should be a Fernet key. If omitted, the service
derives a stable key from other runtime dashboard secrets, but production
deployments should set an explicit vault-backed key.

Generate a Fernet key:

```bash
python - <<'PY'
from cryptography.fernet import Fernet
print(Fernet.generate_key().decode())
PY
```

## Demo Notes

Good demo prompt:

```text
I need to onboard Bob. You'll need SSN, DOB, full legal name, and an initial
password. Can you continue securely?
```

Expected behavior:

- The chat agent opens a secure form instead of asking for values in chat.
- The form page says agents receive references only.
- Incomplete submissions are blocked before any partial values are stored.
- Dashboard ticket details show Secure Intake evidence if linked to a ticket.
- Event/audit views show requested/submitted status, field types, and refs,
  never raw values.
- If a ticket worker mistakenly uses the normal ticket requester-info endpoint
  for account setup or protected fields, the platform converts that outbound
  ask into a secure form before it is delivered to Matrix/Element.

Evidence screenshots:

- `docs/evidence/sensitive-intake-form-request.png`
- `docs/evidence/sensitive-intake-form-submitted.png`
- `docs/evidence/sensitive-intake-ui-missing-required.png`
- `docs/evidence/sensitive-intake-ui-submitted.png`
- `docs/evidence/sensitive-intake-dashboard-secure-section.png`

## Regression Command

Run the expanded smoke against a live dashboard:

```bash
export DASHBOARD_SERVICE_TOKEN="$(grep -E '^DASHBOARD_SERVICE_TOKEN=' .env | tail -n1 | cut -d= -f2-)"
python3 scripts/smoke_sensitive_intake.py http://<loopback>:25480
```

Run the real Matrix/Element intake proof from an operator workstation:

```powershell
$env:DASHBOARD_URL="https://<operator-host>:25443"
$env:DASHBOARD_USER="demo_account_1"
$env:DASHBOARD_PASSWORD="<from vault>"
$env:OPS_CHAT_URL="https://<operator-host>:3303"
$env:OPS_CHAT_USER="demo_account_1"
$env:OPS_CHAT_PASSWORD="<from vault>"
$env:OPS_CHAT_ROOM_ID="<optional known bot room id>"
$env:PLAYWRIGHT_IGNORE_HTTPS_ERRORS="true"
$env:OPS_CHAT_SENSITIVE_MARKER="ops-chat-sensitive-<unique>"
$env:OPS_CHAT_SENSITIVE_SCENARIO="fallback"
$env:PLAYWRIGHT_SCREENSHOT_DIR="docs/evidence/$env:OPS_CHAT_SENSITIVE_MARKER"
$env:NODE_PATH="$(npm root -g)"  # only needed when Playwright is installed globally
node scripts/smoke_ops_chat_sensitive_intake_ui.js
```

`OPS_CHAT_SENSITIVE_SCENARIO` supports:

- `fallback`: Element creates a ticket, a ticket worker/request-info ask is
  converted to a secure form, and ticket context is verified refs-only.
- `direct`: the chat harness itself uses `ops_chat_tool.py
  request-sensitive-fields`, returns a `/secure-intake/` link, and does not
  create a ticket before protected values are brokered.
- `redaction`: a synthetic accidental paste is stored in dashboard Ops Chat
  messages as `siv_...` references, with raw generated canaries absent from
  dashboard/model-visible state.
- `judgment`: natural no-hint prompts prove the chat agent chooses secure
  intake for protected onboarding and financial packets, while harmless chat
  and normal software requests avoid unnecessary secure forms.
- `account-e2e`: no-hint dashboard account request triggers secure intake,
  submits a brokered password, creates a real local read-only dashboard login
  through a ticket worker, verifies UI login, and verifies read-only denial.
- `all`: runs fallback, direct, redaction, judgment, and account-e2e in one
  browser session.

This browser test logs into Element, creates a Matrix-linked ticket, forces the
ticket requester-info path to request account-sensitive fields, waits for a
`/secure-intake/` link in the actual chat room, submits the secure form through
the browser, verifies ticket context contains submitted `sir_...` request refs,
then verifies the secure request detail contains `siv_...` value refs with
`raw_values_returned=false`. Generated submitted values must not appear in chat,
ticket context, request detail, or audit-visible payloads.

The smoke verifies request metadata redaction, public form safety, missing
required-field rejection, complete submission, one-submit token enforcement,
requested/rejected/submitted audit events, attachment metadata redaction, and no
raw submitted values in API responses.

The current detector covers common demo canaries for SSN, DOB, password-like
credentials, API tokens, recovery codes, government IDs, and payment-card-like
values. It is a defensive guard, not a substitute for the secure form path.

Latest live Element proof, 2026-06-05:

- Marker: `ops-chat-sensitive-20260605121228`
- Ticket: `1671` was created through the real Matrix/Element DM, used for the
  proof, then cancelled as synthetic smoke evidence.
- Secure request: `sir_MgSO2aue1inAhrp40SRebQi`
- Field labels were clean and generic: full legal name, SSN, date of birth,
  desired username, work email address, role, manager or sponsor, start date,
  and initial password.
- The browser submitted the form; dashboard context showed submitted refs only
  and no raw generated values.
- The script stopped its synthetic worker and left active agents at zero.
- Screenshots:
  `docs/evidence/ops-chat-sensitive-20260605121228/secure-intake-form-requested.png`,
  and
  `docs/evidence/ops-chat-sensitive-20260605121228/secure-intake-form-submitted.png`.

Additional hardening proof, 2026-06-05:

- Element fallback rerun passed with marker
  `ops-chat-sensitive-rerun-20260605123004`, ticket `1673`, secure request
  `sir_K4eNSmMkfx0WFpJXVHOws`, 9 fields, refs-only ticket context, synthetic
  agent `492` stopped, and ticket cancelled.
- Authenticated dashboard-route direct harness proof passed with marker
  `opschatdirectalphatest`, session `791`, secure request
  `sir_8amUhbm97Te3eqd2HC8AffB`, 8 fields, no ticket, and no raw generated
  values in request/session payloads.
- Authenticated dashboard-route accidental-paste proof passed with marker
  `opschatredactionalphatest`, session `792`, no ticket, `siv_...` refs in
  dashboard Ops Chat messages, and no raw generated canaries in dashboard
  payloads.
- The Element static-asset issue was fixed live after source added nginx
  `sendfile off;` and `keepalive_timeout 0;`. Full normal HTTPS bundle body
  downloads now return immediately.
- Full Matrix/Element hardening pass after deploy: marker
  `opschatsensitiveallX`; fallback ticket `1674`; fallback secure request
  `sir_mrcbO24VFtlV5Nl9lTsJnwWS`; direct secure request
  `sir_4ls3JDdYqm98OhqDlSSBWqY`; redaction scenario stored refs only; raw
  generated canaries absent; synthetic agent `493` stopped and ticket
  cancelled.

No-hint extreme Element proof, 2026-06-05:

- Full Matrix/Element hardening pass: marker `opschatallhardZ`.
- `fallback`: ticket `1679`, secure request
  `sir_AXfRYiOUETnAtGlJ9ZFpI2f`, 9 submitted fields, request detail returned
  value refs only, synthetic agent `498` stopped, ticket cancelled.
- `direct`: secure request `sir_06CzdL2ImmSrmxfRja0AkhXu`, 8 submitted fields,
  no ticket created before protected values were brokered.
- `redaction`: accidental fake SSN/password/token paste stored marker-local
  `siv_...` refs only; raw canaries absent from dashboard Ops Chat payloads.
- `judgment`: the agent inferred secure intake without being told for natural
  account-onboarding and vendor payment packet asks. Requests
  `sir_I6CYgQc1JaZuNpDedcQISfu` and
  `sir_M2186yptysQ8Ui5VnZ6bqTI` submitted 8 and 6 fields respectively with
  value refs only.
- Negative controls passed: a normal 7-Zip software request created a ticket
  without a secure form, and a harmless Wyoming-capital question created no
  ticket and no secure form.
- Screenshots:
  `docs/evidence/opschatallhardZ/secure-intake-form-requested.png` and
  `docs/evidence/opschatallhardZ/secure-intake-form-submitted.png`.

Fresh no-hint rerun after docs/test hardening, 2026-06-05:

- Marker `opschatjudgeliveQ`, scenario `judgment`, Matrix session `790`.
- Natural onboarding secure request
  `sir_TfUhp3EpkaPE6Jjajfw2oLp`: 8 submitted fields, 8 value refs,
  `raw_values_returned=false`.
- Natural vendor payment secure request
  `sir_j3Wmzm3ybc0EpuNz6uABig3P`: 6 submitted fields, 6 value refs,
  `raw_values_returned=false`.
- Accidental paste path reused ticket `1680`; dashboard session text contained
  marker-local `siv_...` refs, ticket context showed secure request refs, and
  secure request detail showed value refs only. Ticket was cancelled after
  synthetic proof cleanup.
- Non-sensitive 7-Zip request created ticket `1682` without a secure form;
  synthetic agent `501` was stopped and ticket `1682` was cancelled.
- Harmless Wyoming-capital question created no ticket and no secure form.

No-hint end-to-end brokered account proof, 2026-06-05:

- Marker `opsacctnohintI`, scenario `account-e2e`.
- User asked in Element for a local read-only Agentic Operations dashboard
  account named `secure_e2e_cctnohinti`. The prompt did not mention passwords,
  protected fields, secure intake, forms, or brokered credentials.
- The chat agent inferred that account provisioning required protected input
  and opened secure request `sir_w38HLNlY5t5g7Uj3PXldG` before ticket creation.
- The secure form collected two protected fields: initial temporary password
  and identity verification details.
- After form submission, the agent created and worked ticket `1685`; iTop sync
  reference `1084`; final status `resolved`.
- The worker used the brokered account adapter to create local dashboard user
  `secure_e2e_cctnohinti` with role `auditor`.
- Playwright verified the new user could log in through the dashboard UI with
  the submitted brokered password, then verified read-only enforcement by
  attempting `POST /api/access/users` as that user and receiving HTTP `403`.
- Final live checks: Codex selected, max active agents `5`, queue depth `0`,
  active agents `0`, active harness processes `0`, `/api/access/users`
  returned no `password_hash` keys and no PBKDF2 hash strings, and ticket
  `1685` contained the secure request ref without password hash leakage.
- Screenshots:
  `docs/evidence/opsacctnohintI/secure-intake-form-requested.png` and
  `docs/evidence/opsacctnohintI/secure-intake-form-submitted.png`.

Latest stress rerun, 2026-06-06:

- No-hint account E2E marker `stress-account-e2e-1780764640` used Element as
  `demo_chat_general1`.
- The user asked naturally for read-only dashboard account
  `secure_e2e_1780764640` without mentioning secure forms, passwords, brokered
  credentials, or protected fields.
- The chat agent opened secure request `sir_8QvDyDUWgKdM0JfLOtcP6HU` before
  ticket creation, collected two protected fields, and returned refs only.
- The worker created ticket `1997`, synced to iTop, created local dashboard
  user `secure_e2e_1780764640` with role `auditor`, and resolved the ticket.
- Playwright verified dashboard UI login with the submitted brokered password,
  then verified read-only enforcement by attempting an admin mutation and
  receiving HTTP `403`.
- Raw password values and password hashes were absent from ticket context,
  chat/session payloads, `/api/access/users`, and script output.
- Screenshots are under
  `docs/evidence/stress-account-e2e-1780764640/`.

Latest no-hint judgment stress, 2026-06-06:

- Marker `stress-sensitive-judgment-1780763052`.
- Natural protected onboarding and financial packet prompts opened secure
  forms without being told to use secure intake.
- Accidental pasted protected values were redacted into `siv_...` references in
  dashboard-visible session state.
- Non-sensitive software work created a normal ticket, and harmless chat
  created no ticket and no secure form.

Earlier brokered account plumbing proof, 2026-06-05:

- Marker `opsacctfinalB`, scenario `account-e2e`.
- User asked naturally in Element for a local read-only dashboard account and
  said they had an initial temporary password and identity verification details
  to provide. This proved the adapter plumbing, but the stricter no-hint
  standard is now `opsacctnohintI`.
- Secure request `sir_QmLqRpPngf6pQqIjzstWorO` collected two protected fields:
  initial temporary password and identity verification details.
- After form submission, the agent created and worked ticket `1684`; iTop sync
  reference `1083`; final status `resolved`; agent `503`.
- The worker used the brokered account adapter to create local dashboard user
  `secure_e2e_acctfinalb` with role `auditor`.
- Playwright verified the new user could log in through the dashboard UI with
  the submitted password, then verified read-only enforcement by attempting
  `POST /api/access/users` as that user and receiving HTTP `403`.
- Final live checks: `/api/access/users` returned no `password_hash` keys and
  no PBKDF2 hash strings; ticket context did not contain the generated
  password; active agents and runner processes returned to zero.
- Screenshots:
  `docs/evidence/opsacctfinalB/secure-intake-form-requested.png` and
  `docs/evidence/opsacctfinalB/secure-intake-form-submitted.png`.

## Current Limitations

- Provider adapters consume references only after adapter-specific actions are
  added. The broker intentionally does not expose raw values to agents.
- The universal form is deliberately generic. Native Teams/Slack cards can wrap
  the same request/submit endpoints later without changing the broker contract.
- If a user manually pastes protected values into Matrix/Element, the Matrix
  homeserver will still receive the original event. The platform bridge
  redacts before dashboard storage, ticketing, model prompts, audit/event
  details, and memory-visible text. The secure form path is the required
  no-plaintext intake path.
