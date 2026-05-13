# Security And Approval Guardrails

Last updated: 2026-05-11.

## Baseline Rules

Agents must request approval before actions that can alter or destroy anything:

- file writes outside the isolated work directory
- service restarts
- firewall, EDR, network, DNS, proxy, or blocklist changes
- mailbox quarantine/delete/move/send actions
- account disable/reset/group/role changes
- repository writes, merges, deployments, CI/CD changes
- production system configuration changes
- database writes outside the dashboard API contract
- anything that would be hard to undo or may affect users

## Default Harness Boundary

Current managed agents run with:

```text
AGENT_PERMISSION_MODE=acceptEdits
AGENT_ALLOWED_TOOLS=Read,Write,Bash(curl *)
```

This lets agents:

- read/write their isolated work files
- call dashboard API endpoints with `curl`
- write checkpoints

It does not intentionally grant arbitrary shell administration capability.

## Change Request API

Create:

```bash
curl -sS -X POST http://localhost:25480/api/changes/request \
  -H 'Content-Type: application/json' \
  -d '{
    "agent_id": 26,
    "ticket_id": 28,
    "action": "block_url",
    "target": "https://example.invalid/phish",
    "reason": "Confirmed phishing URL in delivered message.",
    "command": "no-op in lab",
    "risk_level": "medium",
    "approval_policy": {"requires_human": true}
  }'
```

Poll:

```bash
curl -sS http://localhost:25480/api/changes/7/status
```

Approve:

```bash
curl -sS -X POST http://localhost:25480/api/changes/7/approve \
  -H 'Content-Type: application/json' \
  -d '{"approved_by":"operator","reason":"Reviewed evidence and approved scoped action."}'
```

Demo/lab auto-approval:

```bash
curl -sS -X POST http://localhost:25480/api/changes/7/approve \
  -H 'Content-Type: application/json' \
  -d '{"approved_by":"demo-auto-approver","reason":"Demo mode auto-approval to prove the approval gate without waiting for a human."}'
```

Reject:

```bash
curl -sS -X POST http://localhost:25480/api/changes/7/reject \
  -H 'Content-Type: application/json' \
  -d '{"rejected_by":"operator","reason":"Need stronger evidence."}'
```

Complete:

```bash
curl -sS -X POST http://localhost:25480/api/changes/7/complete \
  -H 'Content-Type: application/json' \
  -d '{"completed_by":"agent_26","result":"Block applied in test environment. Compile/test/diff evidence ..."}'
```

## Completion Advancement

Approved change requests should not remain in `approved` after the work is done.
The primary path is agent-driven: after the approved action is executed and
verified, the agent calls `POST /api/changes/{id}/complete` with evidence.

The control plane also has a deterministic fallback:

- `agent_runner` checks for approved, agent-linked changes after a clean task completion.
- `task_tracker` performs the same check when completion is detected from `checkpoint.json`.
- `agent_auditor` sweeps already-completed tasks that still have approved changes.
- Changes with `approval_policy.auto_complete=false` or
  `approval_policy.manual_completion_required=true` are left for explicit manual completion.

Auto-completion writes the compiled evidence into `change_requests.result` and
records both `event_log` and `audit_log` entries with actor `agent-supervisor`.

## Account Access Gates

Permission walls use the same approval table, but are created through the
ticket-scoped access request API:

```bash
curl -sS -X POST http://localhost:25480/api/tickets/<ticket_id>/access-request \
  -H "Content-Type: application/json" \
  -d '{"agent_id":123,"resource":"Wazuh Dashboard","permission":"SIEM analyst read access","assignment_group":"Identity & Access","reason":"Agent received access denied while reviewing alert evidence."}'
```

This creates:

- a child `UserRequest` ticket assigned to the access-owning group.
- a parent-ticket change gate with `approval_policy.access_request=true`.
- an `access_requests` row tying parent ticket, child ticket, agent, and change
  gate together for audit.

Approval of the gate resumes the original ticket agent. Completion of the gate
marks the access request as `granted` and writes grant evidence to both parent
and child ticket timelines.

## Demo Transparency

Every change request is presented as an approval gate in the ticket timeline.
The control plane writes ticket notes for:

- `Approval gate opened`
- `Approval gate AUTO-APPROVED` or `Approval gate approved`
- `Approval gate rejected`
- `Approval gate completed`

Auto-approval is intentionally loud in the demo. If `approved_by` contains
`auto`, `demo`, or `smoke`, the approval audit payload includes:

```json
{
  "approval_gate": true,
  "approval_mode": "demo_auto_approval",
  "auto_approved": true
}
```

The dashboard ticket detail modal renders each change as an **Approval Gate**
card with an `Auto-approved demo gate` badge and direct links to the full gate,
ticket, and agent audit trails.

## Future Access Control

The dashboard currently assumes an operator can approve changes. Before production:

- add Keycloak/OIDC authentication
- map user roles to dashboard permissions
- require specific roles for approval
- require stronger approval for high-risk actions
- record authenticated user identity in `approved_by`/`reviewed_by`
- optionally sync approvals into the ticketing provider's native change workflow

## Audit

Use:

```bash
curl -sS 'http://localhost:25480/api/dashboard/audit?limit=100'
```

Useful filters:

- `source=event`
- `source=audit`
- `level=error`
- `ticket_id=<id>`
- `agent_id=<id>`
- `q=<text>`

Audit/event logs are not a replacement for production SIEM retention yet. They are the dashboard-native operational record.
