-- Agentic Operations Database Schema
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
    opened_by_name VARCHAR(240),
    opened_by_email VARCHAR(300),
    requester_name VARCHAR(240),
    requester_email VARCHAR(300),
    affected_user_name VARCHAR(240),
    affected_user_email VARCHAR(300),
    owning_group VARCHAR(160),
    security_classification VARCHAR(80) NOT NULL DEFAULT 'internal',
    access_scope JSONB NOT NULL DEFAULT '{}',
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
    model VARCHAR(100) NOT NULL DEFAULT 'deepseek/deepseek-v4-flash',
    selected_model VARCHAR(200) DEFAULT 'deepseek/deepseek-v4-flash',
    harness VARCHAR(80),
    runtime_profile_id VARCHAR(80),
    runtime_config JSONB NOT NULL DEFAULT '{}',
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
    status VARCHAR(40) NOT NULL DEFAULT 'queued',
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
    status VARCHAR(40) NOT NULL,
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
    workflow_key VARCHAR(160),
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
    password_hash TEXT,
    password_changed_at TIMESTAMPTZ,
    failed_login_count INTEGER NOT NULL DEFAULT 0,
    last_failed_login_at TIMESTAMPTZ,
    last_login_at TIMESTAMPTZ,
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

CREATE TABLE IF NOT EXISTS service_groups (
    id SERIAL PRIMARY KEY,
    name VARCHAR(160) NOT NULL UNIQUE,
    description TEXT,
    default_assignee VARCHAR(200),
    risk_level VARCHAR(40) DEFAULT 'low',
    enabled BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS service_raci_rules (
    id SERIAL PRIMARY KEY,
    name VARCHAR(200) NOT NULL UNIQUE,
    intent VARCHAR(120) NOT NULL,
    keywords JSONB NOT NULL DEFAULT '[]',
    ticket_class VARCHAR(80) NOT NULL DEFAULT 'UserRequest',
    priority VARCHAR(40) DEFAULT 'P3',
    assignment_group VARCHAR(160) NOT NULL,
    responsible VARCHAR(160) NOT NULL,
    accountable VARCHAR(160) NOT NULL,
    consulted JSONB NOT NULL DEFAULT '[]',
    informed JSONB NOT NULL DEFAULT '[]',
    approval_required BOOLEAN NOT NULL DEFAULT false,
    approval_action VARCHAR(240),
    risk_level VARCHAR(40) DEFAULT 'low',
    knowledge_tags JSONB NOT NULL DEFAULT '[]',
    auto_assign_agent BOOLEAN NOT NULL DEFAULT false,
    auto_agent_model VARCHAR(200) DEFAULT 'deepseek/deepseek-v4-flash',
    auto_agent_prompt TEXT,
    security_classification VARCHAR(80) NOT NULL DEFAULT 'internal',
    access_scope JSONB NOT NULL DEFAULT '{}',
    enabled BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS service_intake_sessions (
    id SERIAL PRIMARY KEY,
    requester_name VARCHAR(240),
    requester_email VARCHAR(300),
    channel VARCHAR(80) NOT NULL DEFAULT 'dashboard',
    message TEXT NOT NULL,
    attachments JSONB NOT NULL DEFAULT '[]',
    classification JSONB NOT NULL DEFAULT '{}',
    ticket_id INTEGER REFERENCES tickets(id) ON DELETE SET NULL,
    status VARCHAR(40) NOT NULL DEFAULT 'created',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS access_requests (
    id SERIAL PRIMARY KEY,
    parent_ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    access_ticket_id INTEGER REFERENCES tickets(id) ON DELETE SET NULL,
    agent_id INTEGER REFERENCES agents(id) ON DELETE SET NULL,
    change_id INTEGER REFERENCES change_requests(id) ON DELETE SET NULL,
    requester VARCHAR(240),
    account_ref VARCHAR(240),
    resource VARCHAR(300) NOT NULL,
    permission VARCHAR(240) NOT NULL,
    reason TEXT,
    assignment_group VARCHAR(160) NOT NULL DEFAULT 'Identity & Access',
    status VARCHAR(40) NOT NULL DEFAULT 'pending_approval',
    approval_actor VARCHAR(160),
    grant_evidence TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_steering_events (
    id SERIAL PRIMARY KEY,
    ticket_id INTEGER NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
    agent_id INTEGER NOT NULL REFERENCES agents(id) ON DELETE CASCADE,
    task_id INTEGER REFERENCES agent_tasks(id) ON DELETE SET NULL,
    note_id INTEGER REFERENCES ticket_notes(id) ON DELETE SET NULL,
    source VARCHAR(80) NOT NULL DEFAULT 'dashboard',
    author VARCHAR(120) NOT NULL DEFAULT 'dashboard',
    body TEXT NOT NULL,
    status VARCHAR(40) NOT NULL DEFAULT 'pending',
    metadata JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    delivered_at TIMESTAMPTZ,
    acknowledged_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS ops_chat_sessions (
    id SERIAL PRIMARY KEY,
    requester_name VARCHAR(240),
    requester_email VARCHAR(300),
    channel VARCHAR(80) NOT NULL DEFAULT 'ops-chat',
    external_thread_id TEXT,
    latest_ticket_id INTEGER REFERENCES tickets(id) ON DELETE SET NULL,
    status VARCHAR(40) NOT NULL DEFAULT 'open',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ops_chat_messages (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES ops_chat_sessions(id) ON DELETE CASCADE,
    role VARCHAR(40) NOT NULL,
    body TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    ticket_id INTEGER REFERENCES tickets(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS cicd_security_runs (
    id SERIAL PRIMARY KEY,
    provider VARCHAR(100) NOT NULL DEFAULT 'local',
    repo_ref TEXT NOT NULL,
    branch VARCHAR(200),
    commit_sha VARCHAR(120),
    target_url TEXT,
    status VARCHAR(40) NOT NULL DEFAULT 'completed',
    summary TEXT,
    findings JSONB NOT NULL DEFAULT '[]',
    tool_results JSONB NOT NULL DEFAULT '{}',
    ticket_id INTEGER REFERENCES tickets(id) ON DELETE SET NULL,
    change_id INTEGER REFERENCES change_requests(id) ON DELETE SET NULL,
    created_by VARCHAR(120) NOT NULL DEFAULT 'cicd-security-pipeline',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS agent_audit_reviews (
    id SERIAL PRIMARY KEY,
    agent_id INTEGER REFERENCES agents(id) ON DELETE SET NULL,
    task_id INTEGER REFERENCES agent_tasks(id) ON DELETE SET NULL,
    ticket_id INTEGER REFERENCES tickets(id) ON DELETE SET NULL,
    severity VARCHAR(40) NOT NULL DEFAULT 'info',
    finding VARCHAR(240) NOT NULL,
    recommended_action VARCHAR(160),
    action_taken VARCHAR(160),
    approval_blocked BOOLEAN NOT NULL DEFAULT false,
    details JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
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
    ('Keycloak', 'iam', 'host.docker.internal', 8443, 'Keycloak identity provider and Admin Console'),
    ('SOC Bridge', 'bridge', 'localhost', NULL, 'iTop <-> Mailcow notification bridge'),
    ('SIEM-Ticket Bridge', 'bridge', 'localhost', NULL, 'Wazuh <-> iTop alert bridge'),
    ('Agent Memory', 'memory', 'agent-memory-db', 5432, 'Shared PostgreSQL/pgvector memory service for dashboard agents'),
    ('Roundcube Webmail', 'email-ui', 'host.docker.internal', 2581, 'Roundcube webmail client for Mailcow demo/report-phish workflows'),
    ('Element Ops Chat', 'chat-ui', 'host.docker.internal', 3301, 'Element Web Matrix client connected to the Agentic Operations intake bridge'),
    ('Matrix Synapse Ops Chat', 'chat', 'host.docker.internal', 3302, 'Matrix Synapse homeserver for real chat intake with Keycloak OIDC'),
    ('Ops Chat Matrix Bridge', 'bridge', 'ops-chat-bridge', 29318, 'Matrix application-service bridge that creates dashboard tickets and queues real agents'),
    ('SearXNG', 'search', 'localhost', 7999, 'Local search engine for research'),
    ('GitLab', 'vcs', 'localhost', 80, 'GitLab CE for source management')
ON CONFLICT (name) DO UPDATE SET
    type = EXCLUDED.type,
    host = EXCLUDED.host,
    port = EXCLUDED.port,
    description = EXCLUDED.description,
    updated_at = NOW();

-- Delete ComfyUI if exists
DELETE FROM tools WHERE name = 'ComfyUI';
-- TheHive is optional/legacy in the current platform and should not appear
-- unless an operator configures an actual reachable TheHive endpoint.
DELETE FROM tools WHERE name = 'TheHive' AND port IS NULL;

-- Insert default dashboard settings
INSERT INTO dashboard_settings (key, value) VALUES
    ('theme', '{"mode": "dark", "primary": "#00d4ff", "accent": "#ff6b35"}'),
    ('sync_enabled', '{"itop": true, "interval": 30}'),
    ('health_check_enabled', '{"enabled": true, "interval": 60}'),
    ('agent_config', '{"model": "deepseek/deepseek-v4-flash", "max_concurrent": 3, "timeout_minutes": 60}')
ON CONFLICT (key) DO NOTHING;

INSERT INTO dashboard_roles (name, description) VALUES
    ('platform-admin', 'Full platform administration'),
    ('soc-manager', 'Manage tickets, workflows, agents, and approvals'),
    ('analyst', 'View and work assigned tickets'),
    ('auditor', 'Read-only access to tickets, logs, approvals, and evidence'),
    ('agent-operator', 'Create agents and supervise runs')
ON CONFLICT (name) DO UPDATE SET description = EXCLUDED.description;

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
ON CONFLICT (role_name, permission_key) DO UPDATE SET description = EXCLUDED.description;

INSERT INTO service_groups (name, description, default_assignee, risk_level) VALUES
    ('Security Operations', 'Security alert triage, phishing, incident response, and threat hunting.', 'soc-tier-1', 'medium'),
    ('Identity & Access', 'Password resets, MFA, access requests, account lockouts, and joiner/mover/leaver support.', 'iam-operator', 'medium'),
    ('Infrastructure Operations', 'Servers, storage, virtualization, backups, and platform availability.', 'infra-operator', 'medium'),
    ('Network Operations', 'Connectivity, DNS, firewall, segmentation, and routing.', 'network-operator', 'medium'),
    ('Endpoint Support', 'Workstation, EDR agent, Sysmon, and desktop support.', 'endpoint-operator', 'low'),
    ('Email Operations', 'Mailbox, distribution group, mail flow, spam, and report-phish support.', 'mail-operator', 'low'),
    ('DevSecOps', 'Repositories, CI/CD, merge requests, security scans, and deployment gates.', 'devsecops-operator', 'medium'),
    ('Business Applications', 'Line-of-business application support and feature requests.', 'apps-operator', 'low'),
    ('Compliance & Audit', 'Audit evidence, access reviews, policy exceptions, and reporting.', 'audit-operator', 'low'),
    ('Change Advisory Board', 'Human approval gate for production changes and elevated-risk automation.', 'cab-reviewer', 'high')
ON CONFLICT (name) DO UPDATE SET
    description = EXCLUDED.description,
    default_assignee = EXCLUDED.default_assignee,
    risk_level = EXCLUDED.risk_level,
    updated_at = NOW();

INSERT INTO service_raci_rules (
    name, intent, keywords, ticket_class, priority, assignment_group,
    responsible, accountable, consulted, informed, approval_required,
    approval_action, risk_level, knowledge_tags
) VALUES
    ('Phishing report', 'phishing', '["phish", "phishing", "suspicious email", "malicious email", "reported email", "bad link", "email header"]', 'Incident', 'P2', 'Security Operations', 'Security Operations', 'Security Operations Manager', '["Email Operations", "Identity & Access"]', '["Compliance & Audit"]', true, 'Approve mailbox search, message quarantine, URL block, or account containment before execution.', 'medium', '["phishing", "email", "incident-response"]'),
    ('Account locked or MFA help', 'identity-help', '["locked out", "password reset", "mfa", "2fa", "authenticator", "cannot login", "access denied"]', 'UserRequest', 'P3', 'Identity & Access', 'Identity & Access', 'IAM Service Owner', '["Service Desk"]', '["Security Operations"]', false, null, 'low', '["iam", "service-desk"]'),
    ('Access request', 'access-request', '["need access", "grant access", "permission", "role", "group membership", "shared mailbox", "distribution group"]', 'UserRequest', 'P3', 'Identity & Access', 'Identity & Access', 'Data Owner', '["Compliance & Audit"]', '["Requester Manager"]', true, 'Approve entitlement, role, or group membership change before execution.', 'medium', '["iam", "approval", "least-privilege"]'),
    ('GitLab repository access', 'repo-access', '["gitlab access", "repository access", "repo permission", "merge request access", "maintainer role", "developer role", "pipeline access"]', 'UserRequest', 'P3', 'DevSecOps', 'DevSecOps', 'Repository Owner', '["Identity & Access", "Compliance & Audit"]', '["Requester Manager"]', true, 'Approve repository role or project membership before granting access.', 'medium', '["iam", "gitlab", "least-privilege", "devsecops"]'),
    ('SIEM analyst access', 'siem-access', '["wazuh access", "siem access", "alert index access", "security dashboard access", "read alerts", "analyst role", "wazuh dashboard"]', 'UserRequest', 'P2', 'Identity & Access', 'Identity & Access', 'Security Operations Manager', '["Security Operations", "Compliance & Audit"]', '["Requester Manager"]', true, 'Approve SIEM read role, alert index access, or dashboard group membership before granting access.', 'medium', '["iam", "siem", "wazuh", "least-privilege"]'),
    ('VPN connectivity issue', 'vpn-connectivity', '["vpn stopped connecting", "vpn connectivity", "vpn issue", "vpn tunnel", "vpn client", "cannot connect vpn", "finance file share via vpn", "file share via vpn", "vpn after reboot"]', 'Incident', 'P3', 'Network Operations', 'Network Operations', 'Network Service Owner', '["Endpoint Support", "Identity & Access"]', '["Requester Manager"]', false, null, 'medium', '["network", "vpn", "service-desk"]'),
    ('Service outage', 'outage', '["down", "outage", "unavailable", "cannot reach", "service offline", "site broken", "network down"]', 'Incident', 'P1', 'Infrastructure Operations', 'Infrastructure Operations', 'Infrastructure Manager', '["Network Operations", "Business Applications"]', '["Security Operations", "Compliance & Audit"]', true, 'Approve production restart, failover, firewall, DNS, or routing change before execution.', 'high', '["incident", "availability", "change-management"]'),
    ('EDR/SIEM security alert', 'edr-siem-alert', '["wazuh", "sysmon", "edr", "siem alert", "security breach", "critical security", "suricata", "zeek", "malware", "endpoint alert"]', 'Incident', 'P1', 'Security Operations', 'Security Operations', 'Security Operations Manager', '["Endpoint Support", "Infrastructure Operations", "Identity & Access"]', '["Compliance & Audit"]', true, 'Approve endpoint containment, account disablement, network block, or active response before execution.', 'high', '["edr", "siem", "incident-response", "endpoint"]'),
    ('Endpoint issue', 'endpoint-support', '["laptop", "desktop", "workstation", "edr", "sysmon", "agent missing", "software install"]', 'UserRequest', 'P3', 'Endpoint Support', 'Endpoint Support', 'Endpoint Service Owner', '["Security Operations"]', '[]', false, null, 'low', '["endpoint", "support"]'),
    ('Deployment or code change', 'devsecops', '["deploy", "merge request", "pull request", "pipeline", "repository", "semgrep", "trivy", "zap", "nuclei", "ci/cd"]', 'Change', 'P2', 'DevSecOps', 'DevSecOps', 'Change Advisory Board', '["Security Operations", "Compliance & Audit"]', '["Requester Manager"]', true, 'Run CI/CD security pipeline and require approval before production deployment.', 'high', '["devsecops", "cicd", "security-gate"]'),
    ('Audit evidence', 'audit-evidence', '["audit", "evidence", "compliance", "control", "report", "access review"]', 'UserRequest', 'P3', 'Compliance & Audit', 'Compliance & Audit', 'Compliance Lead', '["Security Operations", "Identity & Access"]', '[]', false, null, 'low', '["audit", "evidence"]'),
    ('General service request', 'general', '[]', 'UserRequest', 'P4', 'Business Applications', 'Business Applications', 'Service Desk Manager', '["Service Desk"]', '[]', false, null, 'low', '["service-desk"]')
ON CONFLICT (name) DO UPDATE SET
    intent = EXCLUDED.intent,
    keywords = EXCLUDED.keywords,
    ticket_class = EXCLUDED.ticket_class,
    priority = EXCLUDED.priority,
    assignment_group = EXCLUDED.assignment_group,
    responsible = EXCLUDED.responsible,
    accountable = EXCLUDED.accountable,
    consulted = EXCLUDED.consulted,
    informed = EXCLUDED.informed,
    approval_required = EXCLUDED.approval_required,
    approval_action = EXCLUDED.approval_action,
    risk_level = EXCLUDED.risk_level,
    knowledge_tags = EXCLUDED.knowledge_tags,
    enabled = true,
    updated_at = NOW();

UPDATE service_raci_rules
SET auto_assign_agent = true,
    auto_agent_model = COALESCE(auto_agent_model, 'deepseek/deepseek-v4-flash'),
    auto_agent_prompt = 'Auto-work Security Operations phishing tickets end to end using compact evidence first. Required actions: write a triage note listing sender, recipients, URLs, clicked users, exposed credentials if any, endpoints, and provider ticket refs. Never directly browse, curl, wget, screenshot, or otherwise retrieve a suspicious URL from the agent runner or production network. Use passive/sandboxed evidence only: email headers, mail gateway logs, DNS/proxy/firewall logs, Wazuh/SIEM evidence, known-safe internal allowlists, URL/domain parsing, VirusTotal/urlscan-style provider adapters when configured, or approved isolated detonation. If a suspicious URL is present, create an approval-gated URL block change. If a recipient/mailbox is known, create an approval-gated mailbox search/quarantine change. If credential exposure is suspected, create an approval-gated password reset/session revocation review. Poll approvals and complete approved lab-safe actions with evidence. Do not resolve after triage only unless you write a No Containment Justification note explaining why URL block, mailbox quarantine/search, endpoint scan, and account actions are all unnecessary. Write a final resolution note with residual risk and postmortem/workflow recommendations. Do not browse full ticket context unless compact evidence is missing a specific fact.',
    updated_at = NOW()
WHERE name = 'Phishing report';

UPDATE service_raci_rules
SET auto_assign_agent = true,
    auto_agent_model = COALESCE(auto_agent_model, 'deepseek/deepseek-v4-flash'),
    auto_agent_prompt = 'Auto-work Security Operations EDR/SIEM alert tickets end to end using compact evidence first. Required actions: identify alert source, severity, affected host/user/IP, related telemetry, and provider ticket refs; classify incident scope; create approval-gated changes for endpoint scan, containment, account/session action, or network block only when evidence supports them; poll approvals; complete approved lab-safe actions with evidence; write a final resolution note with residual risk and postmortem/workflow recommendations. Do not browse full ticket context unless compact evidence is missing a specific fact.',
    updated_at = NOW()
WHERE name = 'EDR/SIEM security alert';

UPDATE service_raci_rules
SET auto_assign_agent = true,
    auto_agent_model = COALESCE(auto_agent_model, 'local/agent-default'),
    auto_agent_prompt = 'Auto-work Identity & Access chat intake tickets safely. Required actions: read compact ticket context, identify whether this is account lockout, MFA, password reset, or access denial; ask the user for one concise clarification if needed; check related tickets/known outage evidence from dashboard context; do not change credentials or entitlements without an approval gate; create an approval-gated change for password reset, MFA reset, session revocation, or account unlock when required; write a user-readable resolution or next-step note; if no action is possible without external IAM integration, document the missing integration and keep the ticket routed to Identity & Access.',
    updated_at = NOW()
WHERE name = 'Account locked or MFA help';

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
    ),
    (
        'service-desk-intake-router',
        'Classify user requests, correlate context, and create complete routed tickets.',
        'ticketing',
        'Use /api/intake/classify and /api/intake/submit to turn plain-language user asks into the correct canonical ticket class, assignment group, RACI context, approval gate, related tickets, and knowledge references. Keep intake simple for the requester and capture missing context as ticket notes.',
        true,
        true
    ),
    (
        'cicd-security-pipeline',
        'Run modular Semgrep, Trivy, OWASP ZAP, and Nuclei gates before deployment.',
        'devsecops',
        'For code or deployment work, run the modular CI/CD security pipeline in test first. Record Semgrep, Trivy, OWASP ZAP, and Nuclei results with /api/cicd/runs. Create or update a change request before production deployment and do not proceed until approval is granted.',
        true,
        true
    ),
    (
        'agent-memory',
        'Search and write durable shared agent memory through the PostgreSQL memory service.',
        'memory',
        'Before substantial work, search shared memory for relevant prior context with the agent-memory skill or scripts/agent_memory.py. After meaningful completion, store a concise durable note with the outcome, test evidence, changed files, and any caveats. Do not store secrets; use redacted placeholders or vault references.',
        true,
        true
    ),
    (
        'permission-wall-access-request',
        'Escalate permission blockers into auditable access request tickets and approval gates, then resume the original ticket after approval.',
        'identity-access',
        'When a ticket cannot proceed because the agent lacks a required role, group, system, repository, mailbox, or SIEM permission, do not work around the control. POST /api/tickets/{ticket_id}/access-request with agent_id, resource, permission, requester/account, reason, and assignment_group. Add a ticket note saying you are waiting for access, update checkpoint.json with status waiting_for_access and progress below 100, then stop. After approval, re-read the ticket context, verify the approved grant evidence or lab-safe grant note, complete the access change with evidence, and resume the original task.',
        true,
        true
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
CREATE INDEX IF NOT EXISTS idx_agent_workflows_workflow_key ON agent_workflows(workflow_key);
CREATE UNIQUE INDEX IF NOT EXISTS ux_agent_workflows_active_workflow_key
    ON agent_workflows(workflow_key)
    WHERE workflow_key IS NOT NULL AND status IN ('active', 'approved');
CREATE INDEX IF NOT EXISTS idx_workflow_runs_workflow_id ON workflow_runs(workflow_id);
CREATE INDEX IF NOT EXISTS idx_dashboard_users_provider ON dashboard_users(provider, provider_ref);
CREATE INDEX IF NOT EXISTS idx_dashboard_users_enabled_login ON dashboard_users(username, enabled) WHERE password_hash IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_dashboard_user_roles_user ON dashboard_user_roles(user_id);
CREATE INDEX IF NOT EXISTS idx_dashboard_role_permissions_role ON dashboard_role_permissions(role_name);
CREATE INDEX IF NOT EXISTS idx_dashboard_user_scopes_user ON dashboard_user_scopes(user_id);
CREATE INDEX IF NOT EXISTS idx_dashboard_user_scopes_scope ON dashboard_user_scopes(scope_type, scope_value);
CREATE INDEX IF NOT EXISTS idx_agent_permission_context_ticket ON agent_permission_context(ticket_id);
CREATE INDEX IF NOT EXISTS idx_agent_vault_leases_agent ON agent_vault_leases(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_vault_leases_lookup ON agent_vault_leases(agent_id, system, resource_type, action, lease_status);
CREATE INDEX IF NOT EXISTS idx_access_decision_log_created ON access_decision_log(created_at);
CREATE INDEX IF NOT EXISTS idx_access_decision_log_actor ON access_decision_log(actor);
CREATE INDEX IF NOT EXISTS idx_tickets_owning_group ON tickets(owning_group);
CREATE INDEX IF NOT EXISTS idx_tickets_security_classification ON tickets(security_classification);
CREATE INDEX IF NOT EXISTS idx_service_groups_enabled ON service_groups(enabled);
CREATE INDEX IF NOT EXISTS idx_service_raci_rules_enabled ON service_raci_rules(enabled);
CREATE INDEX IF NOT EXISTS idx_service_raci_rules_intent ON service_raci_rules(intent);
CREATE INDEX IF NOT EXISTS idx_service_raci_rules_auto_agent ON service_raci_rules(auto_assign_agent) WHERE enabled = true;
CREATE INDEX IF NOT EXISTS idx_service_intake_ticket ON service_intake_sessions(ticket_id);
CREATE INDEX IF NOT EXISTS idx_service_intake_created ON service_intake_sessions(created_at);
CREATE INDEX IF NOT EXISTS idx_ops_chat_messages_session_created ON ops_chat_messages(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_ops_chat_messages_ticket ON ops_chat_messages(ticket_id);
CREATE INDEX IF NOT EXISTS idx_ops_chat_sessions_external_thread ON ops_chat_sessions(external_thread_id);
CREATE INDEX IF NOT EXISTS idx_ops_chat_sessions_latest_ticket ON ops_chat_sessions(latest_ticket_id);
CREATE INDEX IF NOT EXISTS idx_access_requests_parent ON access_requests(parent_ticket_id);
CREATE INDEX IF NOT EXISTS idx_access_requests_access_ticket ON access_requests(access_ticket_id);
CREATE INDEX IF NOT EXISTS idx_access_requests_change ON access_requests(change_id);
CREATE INDEX IF NOT EXISTS idx_agent_steering_events_agent_status ON agent_steering_events(agent_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_agent_steering_events_ticket_created ON agent_steering_events(ticket_id, created_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_steering_events_agent_note_once
    ON agent_steering_events(agent_id, note_id)
    WHERE note_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_cicd_security_runs_created ON cicd_security_runs(created_at);
CREATE INDEX IF NOT EXISTS idx_cicd_security_runs_ticket ON cicd_security_runs(ticket_id);
CREATE INDEX IF NOT EXISTS idx_agent_audit_reviews_agent ON agent_audit_reviews(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_audit_reviews_task ON agent_audit_reviews(task_id);
CREATE INDEX IF NOT EXISTS idx_agent_audit_reviews_created ON agent_audit_reviews(created_at);
