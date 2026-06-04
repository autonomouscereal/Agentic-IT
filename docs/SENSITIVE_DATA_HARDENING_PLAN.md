# Sensitive Data Hardening Plan

This plan covers places where agents could accidentally receive, store, repeat,
or disclose data they should not see directly.

The product rule is simple: agents may reason over process state and broker
references, but protected values should move through controlled platform
boundaries.

## Current Controls

- Sensitive Intake Broker for user-submitted protected values.
- One-submit secure forms with required-field validation before storage.
- Encrypted `sensitive_intake_values` rows and audit-safe request/submission
  events.
- Defensive redaction for Ops Chat, tickets, ticket notes, provider payload
  descriptions, event log details, secure request metadata, and attachment
  metadata.
- Agents receive `sir_...` request refs and `siv_...` value refs, not raw
  values.
- Provider adapters must resolve refs server-side inside scoped,
  approval-gated actions.

## Recently Covered Use Cases

- SSN, DOB, passwords, API tokens, recovery codes, government IDs, and payment
  card-like values.
- Secure form request metadata containing accidental sensitive text.
- Missing required secure form fields fail before partial storage.
- One-submit token enforcement.
- Ops Chat secure-form request and submission round trip.
- Ticket title, description, note, and provider payload redaction.
- Attachment filename, storage reference, Matrix URL, and metadata redaction.
- Dashboard ticket evidence shows only form status, labels, timestamps, and
  references.

## Remaining Risk Areas

1. **Uploaded File Contents**
   Raw PDF/DOCX/image/text uploads can contain protected values, prompt
   injection, hidden metadata, embedded macros, or malicious links. Current
   controls warn agents and redact attachment metadata, but raw file bytes are
   still available to the agent when a workflow needs them.

2. **Generated Artifacts And Agent Replies**
   Agents can create scripts, markdown, reports, screenshots, videos, or files
   that accidentally repeat protected text learned from a prompt/tool output.

3. **Tool Stdout/Stderr And Harness Logs**
   Command output, provider API responses, stack traces, and agent transcripts
   can include secrets, headers, URLs with tokens, or copied user data.

4. **Memory And Learning Pipelines**
   Postmortems, workflow synthesis, knowledge articles, and agent memory are
   high-value places for durable leakage if they ingest raw ticket/tool text.

5. **Provider Adapter Payloads**
   External ITSM/SIEM/IAM/email/dev tools may have fields that are less obvious
   than title/description/note, such as custom fields, comments, attachment
   names, usernames, device metadata, or webhook payloads.

6. **Search And Reporting Surfaces**
   Global search, audit summaries, analytics, CSV exports, screenshots, and
   dashboards can amplify a leak because they make data easier to find.

7. **Email, Chat, And Alert Ingestion**
   Incoming email bodies, Matrix history, alert payloads, webhook payloads, and
   SIEM events can include credentials or personal data before a human or agent
   has classified them.

8. **Model Provider Boundaries**
   External model routes can receive prompt text, summarized tool output, and
   file excerpts. Regulated deployments need local/on-prem-only routing by
   default and explicit policy gates for external routes.

## Recommended Implementation Sequence

1. **Content Broker For Uploaded Files**
   Store raw uploads encrypted and present agents with a sanitized manifest plus
   extracted, redacted summaries by default. Require explicit workflow permission
   to access raw file bytes.

2. **Central Egress Scrubber**
   Add a final redaction pass before assistant chat replies, ticket public
   notes, generated artifacts, postmortems, workflow drafts, knowledge articles,
   audit summaries, exports, and Matrix outbound messages.

3. **Tool Output Scrubber**
   Wrap command/API/tool output before it is persisted to task logs, checkpoints,
   notes, and model follow-up prompts. Preserve full raw output only in an
   encrypted restricted evidence store when needed.

4. **Reference-Aware Provider Adapters**
   Teach adapters to consume `siv_...` refs inside specific approved actions
   such as account creation, password reset, or HR onboarding without returning
   raw values to the agent.

5. **Memory/Learning Guard**
   Add sensitive-data scanning before memory writes, postmortem synthesis,
   workflow promotion, skill creation, and knowledge article creation.

6. **Global Search/Export Guard**
   Ensure searchable/indexed/exported content is already redacted and add
   regression canaries for search results, audit views, and CSV/report exports.

7. **Policy-Aware Model Routing**
   Add a per-ticket/data-classification guard that blocks external model routes
   for protected or regulated work unless an operator explicitly approves that
   route.

8. **Continuous Leak Canary Suite**
   Keep synthetic values for SSN, DOB, token, recovery code, government ID,
   payment card, URL token, and file metadata. Run canaries across chat,
   tickets, notes, attachments, audit, search, memory, generated artifacts, and
   provider sync after every security-sensitive change.

## Acceptance Standard

For every sensitive-data path:

- The user can submit the needed information naturally.
- The agent receives process context and references only.
- The platform can prove request/submission/access/audit events occurred.
- Raw values do not appear in chat, tickets, notes, audit, search, memory,
  model prompts, provider payload text, logs, or generated artifacts.
- Any raw-value resolution happens only inside narrow server-side provider
  actions protected by RBAC, approval gates, and scoped audit.
