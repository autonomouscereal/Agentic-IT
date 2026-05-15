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

Agents now use per-agent vault leases for system credentials. Before accessing
GitLab, Wazuh/SIEM, mail, iTop, Keycloak, or another provider, request the
specific lease from:

```bash
curl -sS -X POST "$SOC_DASHBOARD_URL/api/agents/$AGENT_ID/vault/lease" \
  -H "Content-Type: application/json" \
  -d '{"system":"gitlab","resource_type":"project","resource_id":"dev-y/app","action":"read"}'
```

If the lease request returns HTTP 403, treat that as the permission wall. The
response is the evidence for the access request. Do not reuse dashboard admin
credentials, broader provider tokens, or another agent's vault reference.

Lease responses include a human-readable `broker_trace.human_summary`. Use that
text in ticket notes when explaining the wall or approved access. It is safe to
quote because the dashboard returns only lease ids, vault references, decisions,
and provider metadata; `credential_value` is always `null`.

The dashboard supports two broker shapes:

- `lease-reference`: the agent receives a scoped vault reference only.
- `prebuilt_provider_endpoint`: the dashboard validates the lease and returns
  redacted provider evidence through a product adapter, such as the Wazuh
  manager/rule/alert endpoints.

Deployments can swap the underlying vault provider by configuration while
preserving the same lease API. The reference lab labels the provider
`server-manager`.

Approved workflows can define normal investigation leases in
`approval_policy.preapproved_leases`. When the workflow is active/approved and
reviewed, new agents spawned for matching tickets receive only those exact
scoped leases at startup, so proven read-only workflows do not need to request
the same access every run. Remediation or environment-changing actions still
require change approval.

When creating an access request for a denied vault lease, include a
`lease_request` payload with the exact `system`, `resource_type`,
`resource_id`, `action`, and optional `credential_ref`. Completing the approved
access gate mints the scoped `agent_vault_leases` row for the original or
resumed agent without exposing any credential value.

If a local model omits `lease_request` but names a known provider resource such
as `wazuh.manager API`, `Wazuh alert index <name>`, or
`GitLab project <group/project>`, the SOC Dashboard now infers the scoped lease
request and records `lease_request_inferred` in audit/event evidence. This is a
fallback only; explicit `lease_request` is still preferred for exact scopes.

For Wazuh/SIEM work after approval, agents must use dashboard-gated provider
endpoints instead of calling Wazuh directly:

```bash
curl -sS "$SOC_DASHBOARD_URL/api/agents/$AGENT_ID/wazuh/manager/status"
curl -sS "$SOC_DASHBOARD_URL/api/agents/$AGENT_ID/wazuh/rules/11"
curl -sS "$SOC_DASHBOARD_URL/api/agents/$AGENT_ID/wazuh/alerts/search?rule_id=11&source_ip=192.0.2.10"
```

These endpoints validate the agent's Wazuh lease, return no secret values, and
write provider-access audit events.

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

Real Wazuh lease/provider proof:

```bash
python scripts/agentic_wazuh_access_request_demo.py http://localhost:25480 qwen/qwen3.6-27b
```

Expected proof: the first agent stops at `waiting_for_access`, an access request
ticket and approval gate are created, approval resumes a new ticket agent, the
resumed agent completes the grant gate with evidence, writes the final note, and
explicitly resolves the original ticket through the ticket status endpoint.

Latest live proof, 2026-05-14:

- Parent ticket `476` used marker `ACCESS_RESUME_1778725601`.
- First agent `168` created access request `4`, iTop access ticket `477`
  / provider ref `289`, and change `144`, then stopped at `awaiting_access`
  with checkpoint `waiting-for-access-ACCESS_RESUME_1778725601`.
- `access-demo-approver` approved change `144`, which spawned resumed agent
  `169`.
- Agent `169` completed the approved access grant with lab-safe evidence,
  changed access request `4` to `granted`, wrote final
  `ACCESS RESUME COMPLETE` notes, and resolved parent ticket `476`.

Latest permission/vault provider proof, 2026-05-14:

- Marker `PERMISSION_PROVIDER_MATRIX_1778768984`.
- iTop parent ticket `511` synced to provider ref `299`.
- Access request child ticket `512` synced to provider ref `300`.
- Denied iTop Team Z read lease became granted lease id `64` only after the
  access gate was approved and completed.
- Direct iTop readback showed the access request child ticket as `resolved`.

Latest fully agentic first-alias permission/vault proof, 2026-05-14:

- Marker `AGENTIC_PERMISSION_VAULT_1778778629`.
- Parent ticket `525`, initial agent `190`, resumed agent `191`, access request
  `12`, iTop child access ticket `527` / provider ref `304`, change gate `154`.
- Agent `190` proved least privilege by receiving only GitLab `dev-y/*` read
  lease `93`, then getting HTTP 403 / `missing_agent_vault_lease` for GitLab
  `dev-z/app` read. It wrote the permission-wall note, created the iTop-synced
  child access request with a `lease_request`, and stopped at
  `awaiting_access` instead of borrowing broader credentials.
- After approval, agent `191` completed change `154`, which moved access
  request `12` to `granted`, resolved the iTop child ticket, and minted scoped
  Dev Z leases for agents `190` and `191`.
- Agent `191` then re-requested its own GitLab `dev-z/app` read lease and got
  `allow: true`, lease `99`, credential ref
  `<vault:gitlab_dev_z_read_after_approval>`, and `credential_value: null`.
  It wrote final evidence, resolved parent ticket `525`, wrote final checkpoint
  `vault-access-complete-AGENTIC_PERMISSION_VAULT_1778778629`, and exited with
  task `188` completed at 100%.
