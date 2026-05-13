---
name: account-access-workflow
description: >
  Handle permission walls during agentic ticket work by creating auditable
  account access request tickets, approval gates, and resume evidence. Use when
  an agent needs GitLab, SIEM/Wazuh, mailbox, repository, system, role, or group
  access before it can complete the original task.
---

# Account Access Workflow

Use this skill when work is blocked by missing access. Do not bypass the
control, reuse broader credentials, or ask the operator for a secret in chat.
Create a child access request and wait for approval.

## Flow

1. Read the current ticket and determine the exact missing resource and minimum
   permission needed.
2. Create an access request:

```bash
curl -sS -X POST "$SOC_DASHBOARD_URL/api/tickets/$TICKET_ID/access-request" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": 123,
    "resource": "GitLab project demo/private-infra",
    "permission": "Developer repository read access",
    "account_ref": "agent-123",
    "assignment_group": "DevSecOps",
    "risk_level": "medium",
    "sync_provider": false,
    "reason": "Repository API returned 403; least-privilege read access is required before evidence can be reviewed."
  }'
```

3. Add a note on the parent ticket that names the blocker, child access ticket,
   and approval gate.
4. Update `checkpoint.json` with `status: waiting_for_access` and progress below
   `100`, then stop.
5. When the approval gate is approved, the dashboard resumes the original
   ticket. Re-read ticket context, verify the approved grant or lab-safe grant
   note, complete the change with evidence, and continue the original task.
6. When the original task is complete, write final evidence and explicitly call
   `POST /api/tickets/{ticket_id}/status`. Use `close_provider: true` only when
   the external provider record should also close; otherwise use
   `close_provider: false` and leave any provider-side access ticket for the
   access owner workflow.

## Seeded RACI Examples

- `GitLab repository access`: routes to `DevSecOps`, accountable to the
  repository owner, and requires approval before project membership changes.
- `SIEM analyst access`: routes to `Identity & Access`, accountable to Security
  Operations, and requires approval before Wazuh/SIEM read roles or alert index
  access are granted.

## Guardrails

- Request the narrowest role and resource scope that can complete the ticket.
- Include owner/manager approval, expiration or review date, rollback path, and
  grant evidence before completing the access gate.
- Never store passwords, API tokens, or session secrets in ticket notes.
- In lab/demo runs, record a lab-safe grant note instead of changing production
  permissions.

## Tests

Control-plane smoke:

```bash
python scripts/smoke_access_request_control_plane.py http://localhost:25480
```

Real local-model resume proof:

```bash
python scripts/agentic_access_request_resume_demo.py http://localhost:25480 qwen/qwen3.6-27b
```

Expected proof: the first agent stops at `waiting_for_access`, an access request
ticket and approval gate are created, approval resumes a new ticket agent, the
resumed agent completes the grant gate with evidence, writes the final note, and
explicitly resolves the original ticket through the ticket status endpoint.
