# FedRAMP Access Control Preparation

Status: enforcement and per-agent vault lease proof deployed and live-verified
on 2026-05-14. On 2026-05-18, the live demo dashboard moved from preparation
to enforced app-wide security: UI/static/health/API routes now require
authentication, trusted proxy headers require a shared secret, service traffic
uses a separate token, and databases are bound to localhost. See
[FedRAMP Security Hardening](FEDRAMP_SECURITY_HARDENING.md) for the current
deployment contract.

## Goal

The dashboard must enforce least privilege across users, agents, tickets,
workflows, credentials, tools, and audit evidence. An agent may spawn when work
is requested, but it may not use a permission, credential, ticket scope,
classification, or tool capability outside its own per-agent vault leases. When
it hits a denied resource, it must document the wall and create an access
request instead of borrowing broader credentials.

This is an additive preparation layer. Defaults remain demo-safe:

- `DASHBOARD_AUTH_MODE=disabled` gives local lab access the existing
  `platform-admin` behavior.
- `DASHBOARD_AUTH_ENFORCEMENT=audit-only` records decisions without blocking.
- `DASHBOARD_AUTH_ENFORCEMENT=enforce` is the intended FedRAMP cutover mode
  after OIDC/header identity is wired through Keycloak or another IdP.

## Local Changes

- `api/migrations/013_fedramp_access_controls.sql`
  - Adds role permission grants.
  - Adds user access scopes for group/org/classification boundaries.
  - Adds per-agent permission snapshots.
  - Adds access decision log structure.
  - Adds ticket ownership and classification fields.
- `api/migrations/014_agent_vault_leases.sql`
  - Adds `agent_vault_leases`, a per-agent manifest of scoped vault references.
  - Stores only vault reference names and lease metadata; never stores or
    returns secret values.
- `api/services/access_control.py`
  - Maps HTTP routes to explicit permission keys.
  - Evaluates role capabilities and wildcard grants.
  - Computes classification ceiling.
  - Records agent permission snapshots.
  - Trims requested agent permissions that exceed the spawner capability set
    while still allowing the agent to spawn and encounter/use denials normally.
  - Creates and evaluates per-agent vault leases by system/resource/action.
- `api/app.py`
  - Adds default-off middleware so the system can run in audit-only or enforce
    mode without route rewrites.
- `api/routes/access.py`
  - Exposes the active route-permission map, role capabilities, classification
    order, and agent permission boundary in `/api/access/policies`.
  - Adds user scope CRUD for demo/provisioning workflows.
- `api/routes/agents.py`
  - Adds `/api/agents/{id}/vault` and `/api/agents/{id}/vault/lease`.
  - Lease requests return scoped vault references on allow and HTTP 403 on
    denial. They do not return secret values.
- `api/routes/tickets.py`
  - Applies row-level group/classification checks to ticket list/detail/notes,
    assignment, postmortem/workflow starts, and status updates.
- `tests/test_access_control_policy.py`
  - Proves route permission mapping, ticket scope/classification boundaries,
    agent permission trimming, and vault lease match behavior.
- `scripts/smoke_permission_vault_e2e.py`
  - Proves real HTTP 403 behavior in enforcement mode: Dev Team Y cannot see or
    note Dev Team Z tickets, Team Z can be scoped to both queues, an agent can
    spawn from Team Y, a Dev Y GitLab lease is allowed, a Dev Z GitLab lease is
    denied, and no secret values are returned.

## Policy Model

Roles grant capabilities such as:

- `tickets:read`, `tickets:note`, `tickets:create`
- `agents:spawn`, `agents:read`, `agents:stop`
- `changes:request`, `changes:approve`, `changes:complete`
- `audit:read`, `access:read`, `access:admin`
- `tools:read`, `tools:operate`

Scopes constrain where those capabilities apply:

- `group`: team or assignment group, such as Security Operations or DevSecOps.
- `organization`: customer org, tenant, contract, or business unit.
- `classification`: maximum data classification the user or agent may see.
- future provider scopes: ServiceNow groups, Jira projects, GitLab projects,
  Wazuh index scopes, mailbox scopes, Keycloak groups.

Scope rows can also carry per-system vault lease metadata in `permissions`, for
example:

```json
[
  {
    "system": "gitlab",
    "resource_type": "project",
    "resource_id": "dev-y/*",
    "actions": ["read"],
    "credential_ref": "<vault:gitlab_dev_y_read>"
  }
]
```

At spawn time the dashboard writes a per-agent `agent_vault.json` in the
agent work directory and mirrors the same leases in `agent_vault_leases`. The
agent must request a specific lease before using external credentials. Denied
lease requests are logged in `access_decision_log` and returned as HTTP 403 so
the agent can file an access request.

Classifications are ordered:

`public < internal < confidential < restricted < secret`

## Deployment Cutover Plan

1. Deploy the additive migration only.
2. Keep `DASHBOARD_AUTH_ENFORCEMENT=audit-only`.
3. Put the dashboard behind Keycloak/OIDC or a trusted auth proxy that supplies
   `x-auth-request-user`, `x-auth-request-email`, and `x-auth-provider`.
4. Create demo users and group/classification scopes.
5. Review `/api/access/policies`, `/api/access/me`, and access decision events.
6. Run local and live smokes for:
   - ticket visibility by group
   - audit visibility by auditor role
   - approval restrictions by manager/CAB role
   - agent spawn with allowed subset
   - agent spawn with denied requested permissions trimmed from the effective
     envelope, not blocked at spawn
   - per-agent vault lease allowed/denied behavior for different systems
7. Switch enforcement to `enforce` only after the audit-only run shows no
   unexpected denies.

## Demo Examples To Build Before Server Deployment

- Dev Team Y can see Dev Team Y tickets and spawn code-review agents there, but
  cannot see Dev Team Z tickets or operate global integrations.
- Security Operations can work phishing and EDR/SIEM tickets, request mailbox or
  endpoint changes, and read relevant evidence, but cannot grant itself IAM
  roles.
- Team Z lead can see both Team Z and Team Y queues by scope, while Team Y
  cannot reciprocally see Team Z.
- Auditor can read tickets, evidence, approvals, and audit trails but cannot
  spawn agents or approve changes.
- Agent spawned by an analyst can request a least-privilege access ticket when
  a system/resource lease is denied, but cannot use platform-admin credentials
  or bypass approval gates.

## Remaining Work

- Apply scope predicates to agent, change, workflow, and audit queries.
- Expand provider-specific credential broker adapters so allowed vault
  references can be resolved by each deployment's vault without exposing secret
  values through dashboard JSON.
- Add UI barriers: classification badges, locked rows, denied-state messages,
  and "why you cannot access this" audit links.
- Add Playwright demos for two-way visibility boundaries and approval denials.

## Enforcement Smoke

Use this sequence in a controlled test window after confirming no unrelated
agents are active:

```bash
python scripts/smoke_permission_vault_e2e.py --print-seed-sql
python scripts/smoke_permission_vault_e2e.py http://127.0.0.1:25480
```

The first command prints raw PostgreSQL seed SQL for demo users/scopes. The
second command requires `DASHBOARD_AUTH_MODE=header` and
`DASHBOARD_AUTH_ENFORCEMENT=enforce`.

Latest live proof, local+iTop provider matrix:

- Marker: `PERMISSION_PROVIDER_MATRIX_1778768984`.
- Dev Y local ticket `509`; Dev Z restricted negative-control ticket `510`.
- Dev Y iTop parent ticket `511`, provider ref `299` / `R-000308`.
- Access request child ticket `512`, provider ref `300` / `R-000309`.
- Dev Y could not spawn an agent on hidden Dev Z scope through direct
  `/api/agents/spawn`.
- Dev Y spawned test agent `181` on its own ticket; over-broad requested
  permissions were trimmed rather than blocking spawn.
- GitLab `dev-y/app` lease allowed as lease id `61`.
- GitLab `dev-z/app` lease denied with reason `missing_agent_vault_lease`.
- iTop `team-y/incident-123` comment lease allowed as lease id `63`.
- iTop `team-z/incident-999` read lease denied, then granted after access
  approval as lease id `64` with credential ref
  `<vault:itop_team_z_read_after_approval>` and no secret value returned.
- iTop directly reported the access request provider object `R-000309` as
  `resolved` after gate completion.
- Final active agent count: `0`.

Latest local-model agentic proof status:

- Marker `AGENTIC_PERMISSION_VAULT_1778768749`, ticket `504`, agent `180`.
- The agent received the correct bounded vault manifest and no Dev Z lease, but
  the currently configured Qwen local model did not emit executable tool calls.
- The runner now fails this state fast and audibly instead of silently hanging:
  `Agent produced no output for 65 seconds; runner marked it stalled and stopped
  the process to prevent a silent harness/model hang.`
- No active agents or agent processes remained after the failed proof.
- A complete local-model permission-wall/resume proof still requires a
  tool-capable local model or proxy configuration. The control-plane/iTop
  permission boundary itself is verified by the matrix above.

Previous live proof:

- Marker: `PERMISSION_VAULT_E2E_1778761664`.
- Dev Team Y scoped ticket: `480`.
- Dev Team Z scoped ticket: `481`.
- Dev Y could list/read/note ticket `480` and could not list/read/note ticket
  `481`.
- Dev Z could list both tickets because it was explicitly scoped to Team Z and
  Team Y.
- Dev Y spawned agent `170`.
- Agent `170` received six scoped vault leases: dashboard ticket `480`
  read/note/request_access, GitLab `dev-y/*` read, and iTop `team-y/*`
  read/comment.
- `/api/agents/170/vault/lease` allowed GitLab `dev-y/app` read with
  credential ref `<vault:gitlab_dev_y_read>` and returned no secret value.
- `/api/agents/170/vault/lease` denied GitLab `dev-z/app` read with HTTP 403
  and reason `missing_agent_vault_lease`.
- `access_decision_log` recorded both the allow and deny decisions.
- Final verification after restoring normal mode: 73 unit tests passed,
  platform doctor passed 18/18, auditor smoke returned OK, and
  `/api/agents/active` returned `0`.
