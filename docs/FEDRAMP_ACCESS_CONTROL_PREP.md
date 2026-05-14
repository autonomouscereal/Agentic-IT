# FedRAMP Access Control Preparation

Status: prepared locally on 2026-05-13. Not deployed.

## Goal

The dashboard must enforce least privilege across users, agents, tickets,
workflows, credentials, tools, and audit evidence. An agent may never receive a
permission, credential, ticket scope, classification, or tool capability that
the spawning user could not use directly.

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
- `api/services/access_control.py`
  - Maps HTTP routes to explicit permission keys.
  - Evaluates role capabilities and wildcard grants.
  - Computes classification ceiling.
  - Records agent permission snapshots.
  - Refuses requested agent permissions that exceed the spawner capability set.
- `api/app.py`
  - Adds default-off middleware so the system can run in audit-only or enforce
    mode without route rewrites.
- `api/routes/access.py`
  - Exposes the active route-permission map, role capabilities, classification
    order, and agent permission boundary in `/api/access/policies`.
- `tests/test_access_control_policy.py`
  - Proves route permission mapping and the "agent cannot exceed spawner"
    boundary locally without hitting the live server.

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
   - agent spawn denied when requested tools/permissions exceed spawner
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
  blocked, but cannot use platform-admin credentials or bypass approval gates.

## Remaining Work

- Apply scope predicates to ticket, agent, change, workflow, and audit queries.
- Carry the evaluated request identity into every agent spawn call.
- Add provider-specific credential delegation tables that reference vault keys,
  never plaintext credentials.
- Add UI barriers: classification badges, locked rows, denied-state messages,
  and "why you cannot access this" audit links.
- Add Playwright demos for two-way visibility boundaries and approval denials.
