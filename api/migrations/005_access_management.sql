-- Dashboard access management scaffold.
-- Raw PostgreSQL only; enforcement is controlled by environment and provider adapters.

CREATE TABLE IF NOT EXISTS dashboard_users (
    id SERIAL PRIMARY KEY,
    username VARCHAR(200) NOT NULL UNIQUE,
    display_name VARCHAR(300),
    email VARCHAR(300),
    provider VARCHAR(100) NOT NULL DEFAULT 'local',
    provider_ref VARCHAR(300),
    enabled BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS dashboard_roles (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    description TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS dashboard_user_roles (
    user_id INTEGER NOT NULL REFERENCES dashboard_users(id) ON DELETE CASCADE,
    role_id INTEGER NOT NULL REFERENCES dashboard_roles(id) ON DELETE CASCADE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, role_id)
);

CREATE INDEX IF NOT EXISTS idx_dashboard_users_provider ON dashboard_users(provider, provider_ref);
CREATE INDEX IF NOT EXISTS idx_dashboard_user_roles_user ON dashboard_user_roles(user_id);

INSERT INTO dashboard_roles (name, description) VALUES
    ('platform-admin', 'Full platform administration'),
    ('soc-manager', 'Manage tickets, workflows, agents, and approvals'),
    ('analyst', 'View and work assigned tickets'),
    ('auditor', 'Read-only access to tickets, logs, approvals, and evidence'),
    ('agent-operator', 'Create agents and supervise runs')
ON CONFLICT (name) DO UPDATE SET description = EXCLUDED.description;
