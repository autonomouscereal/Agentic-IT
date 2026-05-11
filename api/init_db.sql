-- SOC Dashboard Database Schema
-- Raw PostgreSQL, no ORM

-- SOC tools inventory
CREATE TABLE IF NOT EXISTS tools (
    id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    type VARCHAR(50) NOT NULL,
    host VARCHAR(255),
    port INTEGER,
    status VARCHAR(20) DEFAULT 'unknown',
    last_check TIMESTAMP,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Tickets mirrored from iTop
CREATE TABLE IF NOT EXISTS tickets (
    id SERIAL PRIMARY KEY,
    itop_ref VARCHAR(100) NOT NULL,
    itop_class VARCHAR(50) NOT NULL DEFAULT 'Incident',
    title VARCHAR(500) NOT NULL,
    description TEXT,
    status VARCHAR(50) NOT NULL,
    priority VARCHAR(50),
    impact INTEGER,
    urgency INTEGER,
    assignee VARCHAR(255),
    assignee_team VARCHAR(255),
    agent_id INTEGER,
    provider VARCHAR(80) DEFAULT 'itop',
    provider_ref VARCHAR(200),
    provider_class VARCHAR(120),
    provider_url TEXT,
    provider_sync_status VARCHAR(40) DEFAULT 'unknown',
    provider_last_error TEXT,
    provider_payload JSONB DEFAULT '{}',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    synced_at TIMESTAMP,
    CONSTRAINT tickets_itop_ref_class_unique UNIQUE (itop_ref, itop_class)
);

-- Agent instances
CREATE TABLE IF NOT EXISTS agents (
    id SERIAL PRIMARY KEY,
    ticket_id INTEGER REFERENCES tickets(id) ON DELETE CASCADE,
    model VARCHAR(100) NOT NULL DEFAULT 'qwen/qwen3.6-27b',
    selected_model VARCHAR(200) DEFAULT 'qwen/qwen3.6-27b',
    status VARCHAR(30) NOT NULL DEFAULT 'spawned',
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    finished_at TIMESTAMP,
    heartbeat TIMESTAMP,
    logs_ref TEXT,
    assigned_by VARCHAR(100) DEFAULT 'orchestrator',
    workbook_ref TEXT,
    error_message TEXT,
    attempts INTEGER DEFAULT 0,
    last_task_id INTEGER
);

-- Agent tasks (replaces heartbeat monitoring)
CREATE TABLE IF NOT EXISTS agent_tasks (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    ticket_id INTEGER REFERENCES tickets(id),
    task_type VARCHAR(50) NOT NULL DEFAULT 'ticket_resolution',
    prompt TEXT NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'queued',
    output TEXT,
    error_message TEXT,
    checkpoints JSONB DEFAULT '[]',
    progress_pct INTEGER DEFAULT 0,
    work_dir VARCHAR(500),
    pid INTEGER,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Agent skills
CREATE TABLE IF NOT EXISTS agent_skills (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL UNIQUE,
    description TEXT,
    category VARCHAR(100),
    prompt_template TEXT NOT NULL,
    enabled BOOLEAN NOT NULL DEFAULT true,
    assigned_to_all BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Agent skill mappings
CREATE TABLE IF NOT EXISTS agent_skill_mappings (
    agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    skill_id INTEGER NOT NULL REFERENCES agent_skills(id) ON DELETE CASCADE,
    PRIMARY KEY (agent_id, skill_id)
);

-- Change requests for approval
CREATE TABLE IF NOT EXISTS change_requests (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER REFERENCES agents(id) ON DELETE CASCADE,
    ticket_id INTEGER REFERENCES tickets(id) ON DELETE SET NULL,
    itop_change_ref VARCHAR(100),
    action VARCHAR(255) NOT NULL,
    target VARCHAR(255) NOT NULL,
    reason TEXT,
    command TEXT,
    status VARCHAR(30) NOT NULL DEFAULT 'pending',
    requested_by VARCHAR(100),
    approved_by VARCHAR(100),
    approved_at TIMESTAMP,
    rejected_reason TEXT,
    result TEXT,
    risk_level VARCHAR(40) DEFAULT 'unknown',
    approval_policy JSONB DEFAULT '{}',
    requested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP
);

-- Audit log for all actions
CREATE TABLE IF NOT EXISTS audit_log (
    id SERIAL PRIMARY KEY,
    actor VARCHAR(100) NOT NULL,
    action VARCHAR(100) NOT NULL,
    target VARCHAR(255),
    details JSONB,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Event log (structured system-wide logging)
CREATE TABLE IF NOT EXISTS event_log (
    id SERIAL PRIMARY KEY,
    category VARCHAR(50) NOT NULL,
    level VARCHAR(20) NOT NULL DEFAULT 'info',
    actor VARCHAR(100),
    action VARCHAR(200) NOT NULL,
    target VARCHAR(200),
    details JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Tool health check history
CREATE TABLE IF NOT EXISTS tool_checks (
    id SERIAL PRIMARY KEY,
    tool_id INTEGER REFERENCES tools(id) ON DELETE CASCADE,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status VARCHAR(20) NOT NULL,
    response_time_ms INTEGER,
    error TEXT,
    details JSONB
);

-- Ticket notes and attachment metadata
CREATE TABLE IF NOT EXISTS ticket_notes (
    id SERIAL PRIMARY KEY,
    ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    source VARCHAR(50) NOT NULL DEFAULT 'dashboard',
    author VARCHAR(100) NOT NULL DEFAULT 'system',
    body TEXT NOT NULL,
    visibility VARCHAR(30) NOT NULL DEFAULT 'internal',
    external_ref VARCHAR(200),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ticket_attachments (
    id SERIAL PRIMARY KEY,
    ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    note_id INTEGER REFERENCES ticket_notes(id) ON DELETE SET NULL,
    filename VARCHAR(500) NOT NULL,
    content_type VARCHAR(200),
    storage_ref TEXT,
    sha256 VARCHAR(64),
    size_bytes BIGINT,
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS knowledge_articles (
    id SERIAL PRIMARY KEY,
    title VARCHAR(500) NOT NULL,
    body TEXT NOT NULL,
    category VARCHAR(120),
    source VARCHAR(120) DEFAULT 'dashboard',
    external_ref VARCHAR(200),
    tags JSONB DEFAULT '[]',
    enabled BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS postmortems (
    id SERIAL PRIMARY KEY,
    ticket_id INTEGER REFERENCES tickets(id) ON DELETE SET NULL,
    agent_id INTEGER REFERENCES agents(id) ON DELETE SET NULL,
    task_id INTEGER REFERENCES agent_tasks(id) ON DELETE SET NULL,
    status VARCHAR(40) NOT NULL DEFAULT 'draft',
    summary TEXT,
    went_well TEXT,
    improvements TEXT,
    workflow_proposal TEXT,
    skill_proposals JSONB DEFAULT '[]',
    test_cases JSONB DEFAULT '[]',
    guardrails JSONB DEFAULT '[]',
    documentation TEXT,
    review_notes TEXT,
    created_by VARCHAR(100) NOT NULL DEFAULT 'system',
    reviewed_by VARCHAR(100),
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_workflows (
    id SERIAL PRIMARY KEY,
    name VARCHAR(240) NOT NULL UNIQUE,
    description TEXT,
    ticket_class VARCHAR(100),
    trigger_type VARCHAR(80) NOT NULL DEFAULT 'manual',
    status VARCHAR(40) NOT NULL DEFAULT 'draft',
    version INTEGER NOT NULL DEFAULT 1,
    blueprint TEXT NOT NULL,
    test_plan TEXT,
    test_results TEXT,
    approval_policy JSONB DEFAULT '{}',
    skill_ids JSONB DEFAULT '[]',
    created_by VARCHAR(100) NOT NULL DEFAULT 'dashboard',
    reviewed_by VARCHAR(100),
    reviewed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS workflow_runs (
    id SERIAL PRIMARY KEY,
    workflow_id INTEGER NOT NULL REFERENCES agent_workflows(id) ON DELETE CASCADE,
    ticket_id INTEGER REFERENCES tickets(id) ON DELETE SET NULL,
    agent_id INTEGER REFERENCES agents(id) ON DELETE SET NULL,
    task_id INTEGER REFERENCES agent_tasks(id) ON DELETE SET NULL,
    status VARCHAR(40) NOT NULL DEFAULT 'queued',
    result TEXT,
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Dashboard settings
CREATE TABLE IF NOT EXISTS dashboard_settings (
    key VARCHAR(100) PRIMARY KEY,
    value JSONB NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

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

-- Insert default SOC tools (ComfyUI removed)
INSERT INTO tools (name, type, host, port, description) VALUES
    ('iTop ITSM', 'itsm', 'localhost', 25432, 'iTop ITSM v3.2.1 - Ticket management'),
    ('Wazuh SIEM', 'siem', 'localhost', 26500, 'Wazuh SIEM Manager'),
    ('Wazuh Indexer', 'siem', 'localhost', 26920, 'Wazuh Indexer (alert storage)'),
    ('Wazuh Dashboard', 'siem-ui', 'localhost', 26443, 'Wazuh SIEM Dashboard'),
    ('Zeek IDS', 'ids', 'localhost', 26001, 'Zeek network analysis framework'),
    ('Suricata IDS', 'ids', 'localhost', NULL, 'Suricata IDS/IPS'),
    ('Mailcow', 'email', 'localhost', 25, 'Mailcow email server'),
    ('Keycloak', 'iam', 'localhost', 8443, 'Keycloak identity provider'),
    ('SOC Bridge', 'bridge', 'localhost', NULL, 'iTop <-> Mailcow notification bridge'),
    ('SIEM-Ticket Bridge', 'bridge', 'localhost', NULL, 'Wazuh <-> iTop alert bridge'),
    ('SearXNG', 'search', 'localhost', 7999, 'Local search engine for research'),
    ('GitLab', 'vcs', 'localhost', 80, 'GitLab CE for source management'),
    ('TheHive', 'soc-platform', 'localhost', NULL, 'TheHive incident response')
ON CONFLICT (name) DO NOTHING;

-- Delete ComfyUI if exists
DELETE FROM tools WHERE name = 'ComfyUI';

-- Insert default dashboard settings
INSERT INTO dashboard_settings (key, value) VALUES
    ('theme', '{"mode": "dark", "primary": "#00d4ff", "accent": "#ff6b35"}'),
    ('sync_enabled', '{"itop": true, "interval": 30}'),
    ('health_check_enabled', '{"enabled": true, "interval": 60}'),
    ('agent_config', '{"model": "qwen/qwen3.6-27b", "max_concurrent": 3, "timeout_minutes": 60}')
ON CONFLICT (key) DO NOTHING;

INSERT INTO dashboard_roles (name, description) VALUES
    ('platform-admin', 'Full platform administration'),
    ('soc-manager', 'Manage tickets, workflows, agents, and approvals'),
    ('analyst', 'View and work assigned tickets'),
    ('auditor', 'Read-only access to tickets, logs, approvals, and evidence'),
    ('agent-operator', 'Create agents and supervise runs')
ON CONFLICT (name) DO UPDATE SET description = EXCLUDED.description;

-- Baseline global skills for fresh installs
INSERT INTO agent_skills (name, description, category, prompt_template, enabled, assigned_to_all)
VALUES
    (
        'ticket-context-reader',
        'Fetch the full dashboard context bundle for a ticket before taking action.',
        'ticketing',
        'Use GET /api/tickets/{ticket_id}/context before working. Review ticket, notes, attachments, related tickets, knowledge articles, workflows, postmortems, change requests, and assigned skills.',
        true,
        true
    ),
    (
        'ticket-note-writer',
        'Write concise internal or user-visible ticket notes.',
        'ticketing',
        'Use POST /api/tickets/{ticket_id}/notes with body, author, source, and visibility. Summarize evidence, actions, blockers, approvals, and next steps.',
        true,
        true
    ),
    (
        'change-request-gate',
        'Create and poll approval-gated change requests before risky actions.',
        'change-management',
        'Before any environment-changing or destructive action, POST /api/changes/request with action, target, reason, command, and risk_level. Poll GET /api/changes/{change_id}/status until approved or rejected. Do not proceed unless approved.',
        true,
        true
    ),
    (
        'postmortem-builder',
        'Create structured postmortems after ticket completion.',
        'learning',
        'Use POST /api/postmortems to record summary, what worked, improvements, workflow proposal, skill proposals, tests, guardrails, and documentation. Mark status ready_for_review when complete.',
        true,
        true
    ),
    (
        'workflow-builder',
        'Create reusable workflow blueprints from completed work.',
        'automation',
        'Use POST /api/workflows to create draft workflows with blueprint, test_plan, approval_policy, and required skill ids. Keep workflows in draft/tested until reviewed.',
        true,
        true
    ),
    (
        'phishing-triage',
        'Reusable phishing investigation checklist.',
        'security',
        'For phishing: extract sender, recipients, headers, URLs, attachments, authentication results, delivery scope, and risk. Defang URLs in notes. Request approval before mailbox remediation, blocking, quarantine, or account changes.',
        true,
        false
    )
ON CONFLICT (name) DO UPDATE SET
    description = EXCLUDED.description,
    category = EXCLUDED.category,
    prompt_template = EXCLUDED.prompt_template,
    enabled = EXCLUDED.enabled,
    assigned_to_all = EXCLUDED.assigned_to_all,
    updated_at = NOW();

-- Create indexes for performance
CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);
CREATE INDEX IF NOT EXISTS idx_tickets_itop_ref ON tickets(itop_ref);
CREATE INDEX IF NOT EXISTS idx_tickets_provider_ref ON tickets(provider, provider_ref);
CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status);
CREATE INDEX IF NOT EXISTS idx_agents_ticket_id ON agents(ticket_id);
CREATE INDEX IF NOT EXISTS idx_change_requests_status ON change_requests(status);
CREATE INDEX IF NOT EXISTS idx_change_requests_agent_id ON change_requests(agent_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_created_at ON audit_log(created_at);
CREATE INDEX IF NOT EXISTS idx_tool_checks_tool_id ON tool_checks(tool_id);
CREATE INDEX IF NOT EXISTS idx_tool_checks_timestamp ON tool_checks(timestamp);
CREATE INDEX IF NOT EXISTS idx_agent_tasks_agent_id ON agent_tasks(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_tasks_status ON agent_tasks(status);
CREATE INDEX IF NOT EXISTS idx_agent_tasks_ticket_id ON agent_tasks(ticket_id);
CREATE INDEX IF NOT EXISTS idx_event_log_created_at ON event_log(created_at);
CREATE INDEX IF NOT EXISTS idx_event_log_category ON event_log(category);
CREATE INDEX IF NOT EXISTS idx_event_log_level ON event_log(level);
CREATE INDEX IF NOT EXISTS idx_ticket_notes_ticket_id ON ticket_notes(ticket_id);
CREATE INDEX IF NOT EXISTS idx_ticket_notes_created_at ON ticket_notes(created_at);
CREATE INDEX IF NOT EXISTS idx_ticket_attachments_ticket_id ON ticket_attachments(ticket_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_articles_enabled ON knowledge_articles(enabled);
CREATE INDEX IF NOT EXISTS idx_postmortems_ticket_id ON postmortems(ticket_id);
CREATE INDEX IF NOT EXISTS idx_postmortems_status ON postmortems(status);
CREATE INDEX IF NOT EXISTS idx_agent_workflows_status ON agent_workflows(status);
CREATE INDEX IF NOT EXISTS idx_agent_workflows_ticket_class ON agent_workflows(ticket_class);
CREATE INDEX IF NOT EXISTS idx_workflow_runs_workflow_id ON workflow_runs(workflow_id);
CREATE INDEX IF NOT EXISTS idx_dashboard_users_provider ON dashboard_users(provider, provider_ref);
CREATE INDEX IF NOT EXISTS idx_dashboard_user_roles_user ON dashboard_user_roles(user_id);
