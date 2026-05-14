-- Per-agent credential lease manifest.
-- Stores scoped vault references only. Secret values remain in the external
-- credential vault and are never committed or returned by the dashboard.

CREATE TABLE IF NOT EXISTS agent_vault_leases (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    system VARCHAR(120) NOT NULL,
    resource_type VARCHAR(120) NOT NULL DEFAULT 'resource',
    resource_id VARCHAR(300) NOT NULL DEFAULT '*',
    action VARCHAR(120) NOT NULL DEFAULT 'read',
    credential_ref VARCHAR(300) NOT NULL,
    lease_status VARCHAR(40) NOT NULL DEFAULT 'active',
    granted_by VARCHAR(240) NOT NULL DEFAULT 'system',
    expires_at TIMESTAMPTZ,
    policy_snapshot JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (agent_id, system, resource_type, resource_id, action)
);

CREATE INDEX IF NOT EXISTS idx_agent_vault_leases_agent ON agent_vault_leases(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_vault_leases_lookup
    ON agent_vault_leases(agent_id, system, resource_type, action, lease_status);
