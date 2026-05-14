-- FedRAMP-style access-control preparation.
-- Raw PostgreSQL only. This migration is additive and safe to deploy before
-- turning enforcement on.

CREATE TABLE IF NOT EXISTS dashboard_role_permissions (
    role_name VARCHAR(100) NOT NULL REFERENCES dashboard_roles(name) ON DELETE CASCADE,
    permission_key VARCHAR(160) NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (role_name, permission_key)
);

CREATE TABLE IF NOT EXISTS dashboard_user_scopes (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES dashboard_users(id) ON DELETE CASCADE,
    scope_type VARCHAR(80) NOT NULL,
    scope_value VARCHAR(240) NOT NULL,
    permissions JSONB NOT NULL DEFAULT '[]',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, scope_type, scope_value)
);

CREATE TABLE IF NOT EXISTS agent_permission_context (
    agent_id INTEGER PRIMARY KEY REFERENCES agents(id) ON DELETE CASCADE,
    ticket_id INTEGER REFERENCES tickets(id) ON DELETE SET NULL,
    spawned_by_username VARCHAR(240) NOT NULL DEFAULT 'system',
    roles JSONB NOT NULL DEFAULT '[]',
    allowed_permissions JSONB NOT NULL DEFAULT '[]',
    scopes JSONB NOT NULL DEFAULT '[]',
    max_classification VARCHAR(80) NOT NULL DEFAULT 'internal',
    delegated_credential_refs JSONB NOT NULL DEFAULT '[]',
    policy_snapshot JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS access_decision_log (
    id SERIAL PRIMARY KEY,
    actor VARCHAR(240) NOT NULL,
    subject_type VARCHAR(80) NOT NULL,
    subject_id VARCHAR(240),
    action VARCHAR(160) NOT NULL,
    resource_type VARCHAR(80) NOT NULL,
    resource_id VARCHAR(240),
    decision VARCHAR(40) NOT NULL,
    reason TEXT,
    policy_snapshot JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE tickets
    ADD COLUMN IF NOT EXISTS owning_group VARCHAR(160),
    ADD COLUMN IF NOT EXISTS security_classification VARCHAR(80) NOT NULL DEFAULT 'internal',
    ADD COLUMN IF NOT EXISTS access_scope JSONB NOT NULL DEFAULT '{}';

ALTER TABLE service_raci_rules
    ADD COLUMN IF NOT EXISTS security_classification VARCHAR(80) NOT NULL DEFAULT 'internal',
    ADD COLUMN IF NOT EXISTS access_scope JSONB NOT NULL DEFAULT '{}';

INSERT INTO dashboard_role_permissions (role_name, permission_key, description) VALUES
    ('platform-admin', '*', 'Full platform access.'),
    ('soc-manager', 'tickets:*', 'Manage SOC tickets.'),
    ('soc-manager', 'agents:*', 'Manage agents and agent tasks.'),
    ('soc-manager', 'changes:*', 'Manage change gates and approvals.'),
    ('soc-manager', 'workflows:*', 'Manage workflow reviews and activation.'),
    ('soc-manager', 'audit:read', 'Read audit evidence.'),
    ('soc-manager', 'access:read', 'Read access-management state.'),
    ('analyst', 'tickets:read', 'Read tickets within assigned scopes.'),
    ('analyst', 'tickets:note', 'Write notes within assigned scopes.'),
    ('analyst', 'tickets:request_info', 'Request user information on assigned work.'),
    ('analyst', 'access:request', 'Request approval-gated account or system access.'),
    ('analyst', 'changes:request', 'Request approval-gated changes.'),
    ('analyst', 'agents:assigned', 'Work through assigned agents only.'),
    ('auditor', 'tickets:read', 'Read scoped tickets.'),
    ('auditor', 'changes:read', 'Read change gates.'),
    ('auditor', 'audit:read', 'Read audit evidence.'),
    ('auditor', 'evidence:read', 'Read evidence records.'),
    ('auditor', 'access:read', 'Read access-management state.'),
    ('agent-operator', 'agents:spawn', 'Spawn agents within caller scope.'),
    ('agent-operator', 'agents:read', 'Read agent status.'),
    ('agent-operator', 'tickets:read', 'Read ticket context needed to spawn scoped agents.'),
    ('agent-operator', 'access:request', 'Request approval-gated account or system access.'),
    ('agent-operator', 'changes:request', 'Request approval-gated changes.')
ON CONFLICT (role_name, permission_key) DO UPDATE SET
    description = EXCLUDED.description;

UPDATE tickets
SET owning_group = COALESCE(owning_group, assignee_team, assignee, 'Unassigned')
WHERE owning_group IS NULL;

CREATE INDEX IF NOT EXISTS idx_dashboard_role_permissions_role ON dashboard_role_permissions(role_name);
CREATE INDEX IF NOT EXISTS idx_dashboard_user_scopes_user ON dashboard_user_scopes(user_id);
CREATE INDEX IF NOT EXISTS idx_dashboard_user_scopes_scope ON dashboard_user_scopes(scope_type, scope_value);
CREATE INDEX IF NOT EXISTS idx_agent_permission_context_ticket ON agent_permission_context(ticket_id);
CREATE INDEX IF NOT EXISTS idx_access_decision_log_created ON access_decision_log(created_at);
CREATE INDEX IF NOT EXISTS idx_access_decision_log_actor ON access_decision_log(actor);
CREATE INDEX IF NOT EXISTS idx_tickets_owning_group ON tickets(owning_group);
CREATE INDEX IF NOT EXISTS idx_tickets_security_classification ON tickets(security_classification);
