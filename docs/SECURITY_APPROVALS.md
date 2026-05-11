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
  -d '{"approved_by":"operator"}'
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
  -d '{"result":"Block applied in test environment."}'
```

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

