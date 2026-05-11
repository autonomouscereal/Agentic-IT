-- Service desk intake, RACI routing, and CI/CD security pipeline objects.
-- Raw PostgreSQL only; no ORM-managed schema.

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
    (
        'Phishing report',
        'phishing',
        '["phish", "phishing", "suspicious email", "malicious email", "reported email", "bad link", "email header"]',
        'Incident',
        'P2',
        'Security Operations',
        'Security Operations',
        'Security Operations Manager',
        '["Email Operations", "Identity & Access"]',
        '["Compliance & Audit"]',
        true,
        'Approve mailbox search, message quarantine, URL block, or account containment before execution.',
        'medium',
        '["phishing", "email", "incident-response"]'
    ),
    (
        'Account locked or MFA help',
        'identity-help',
        '["locked out", "password reset", "mfa", "2fa", "authenticator", "cannot login", "access denied"]',
        'UserRequest',
        'P3',
        'Identity & Access',
        'Identity & Access',
        'IAM Service Owner',
        '["Service Desk"]',
        '["Security Operations"]',
        false,
        null,
        'low',
        '["iam", "service-desk"]'
    ),
    (
        'Access request',
        'access-request',
        '["need access", "grant access", "permission", "role", "group membership", "shared mailbox", "distribution group"]',
        'UserRequest',
        'P3',
        'Identity & Access',
        'Identity & Access',
        'Data Owner',
        '["Compliance & Audit"]',
        '["Requester Manager"]',
        true,
        'Approve entitlement, role, or group membership change before execution.',
        'medium',
        '["iam", "approval", "least-privilege"]'
    ),
    (
        'Service outage',
        'outage',
        '["down", "outage", "unavailable", "cannot reach", "service offline", "site broken", "network down"]',
        'Incident',
        'P1',
        'Infrastructure Operations',
        'Infrastructure Operations',
        'Infrastructure Manager',
        '["Network Operations", "Business Applications"]',
        '["Security Operations", "Compliance & Audit"]',
        true,
        'Approve production restart, failover, firewall, DNS, or routing change before execution.',
        'high',
        '["incident", "availability", "change-management"]'
    ),
    (
        'Endpoint issue',
        'endpoint-support',
        '["laptop", "desktop", "workstation", "edr", "sysmon", "agent missing", "software install"]',
        'UserRequest',
        'P3',
        'Endpoint Support',
        'Endpoint Support',
        'Endpoint Service Owner',
        '["Security Operations"]',
        '[]',
        false,
        null,
        'low',
        '["endpoint", "support"]'
    ),
    (
        'Deployment or code change',
        'devsecops',
        '["deploy", "merge request", "pull request", "pipeline", "repository", "semgrep", "trivy", "zap", "nuclei", "ci/cd"]',
        'Change',
        'P2',
        'DevSecOps',
        'DevSecOps',
        'Change Advisory Board',
        '["Security Operations", "Compliance & Audit"]',
        '["Requester Manager"]',
        true,
        'Run CI/CD security pipeline and require approval before production deployment.',
        'high',
        '["devsecops", "cicd", "security-gate"]'
    ),
    (
        'Audit evidence',
        'audit-evidence',
        '["audit", "evidence", "compliance", "control", "report", "access review"]',
        'UserRequest',
        'P3',
        'Compliance & Audit',
        'Compliance & Audit',
        'Compliance Lead',
        '["Security Operations", "Identity & Access"]',
        '[]',
        false,
        null,
        'low',
        '["audit", "evidence"]'
    ),
    (
        'General service request',
        'general',
        '[]',
        'UserRequest',
        'P4',
        'Business Applications',
        'Business Applications',
        'Service Desk Manager',
        '["Service Desk"]',
        '[]',
        false,
        null,
        'low',
        '["service-desk"]'
    )
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

INSERT INTO agent_skills (name, description, category, prompt_template, enabled, assigned_to_all)
VALUES
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
    )
ON CONFLICT (name) DO UPDATE SET
    description = EXCLUDED.description,
    category = EXCLUDED.category,
    prompt_template = EXCLUDED.prompt_template,
    enabled = EXCLUDED.enabled,
    assigned_to_all = EXCLUDED.assigned_to_all,
    updated_at = NOW();

CREATE INDEX IF NOT EXISTS idx_service_groups_enabled ON service_groups(enabled);
CREATE INDEX IF NOT EXISTS idx_service_raci_rules_enabled ON service_raci_rules(enabled);
CREATE INDEX IF NOT EXISTS idx_service_raci_rules_intent ON service_raci_rules(intent);
CREATE INDEX IF NOT EXISTS idx_service_intake_ticket ON service_intake_sessions(ticket_id);
CREATE INDEX IF NOT EXISTS idx_service_intake_created ON service_intake_sessions(created_at);
CREATE INDEX IF NOT EXISTS idx_cicd_security_runs_created ON cicd_security_runs(created_at);
CREATE INDEX IF NOT EXISTS idx_cicd_security_runs_ticket ON cicd_security_runs(ticket_id);
