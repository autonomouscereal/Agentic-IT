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
- Dashboard ticket details show Secure Intake evidence if linked to a ticket.
- Event/audit views show requested/submitted status, field types, and refs,
  never raw values.

## Current Limitations

- Provider adapters consume references only after adapter-specific actions are
  added. The broker intentionally does not expose raw values to agents.
- The universal form is deliberately generic. Native Teams/Slack cards can wrap
  the same request/submit endpoints later without changing the broker contract.
