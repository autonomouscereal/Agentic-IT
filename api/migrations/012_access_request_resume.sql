-- Account access request escalation and approval-resume support.
-- Raw PostgreSQL only; no ORM-managed schema.

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

CREATE INDEX IF NOT EXISTS idx_access_requests_parent
    ON access_requests(parent_ticket_id);

CREATE INDEX IF NOT EXISTS idx_access_requests_access_ticket
    ON access_requests(access_ticket_id);

CREATE INDEX IF NOT EXISTS idx_access_requests_change
    ON access_requests(change_id);

INSERT INTO service_raci_rules (
    name, intent, keywords, ticket_class, priority, assignment_group,
    responsible, accountable, consulted, informed, approval_required,
    approval_action, risk_level, knowledge_tags, auto_assign_agent,
    auto_agent_model, auto_agent_prompt, enabled
) VALUES
    (
        'GitLab repository access',
        'repo-access',
        '["gitlab access", "repository access", "repo permission", "merge request access", "maintainer role", "developer role", "pipeline access"]',
        'UserRequest',
        'P3',
        'DevSecOps',
        'DevSecOps',
        'Repository Owner',
        '["Identity & Access", "Compliance & Audit"]',
        '["Requester Manager"]',
        true,
        'Approve repository role or project membership before granting access.',
        'medium',
        '["iam", "gitlab", "least-privilege", "devsecops"]',
        false,
        'qwen/qwen3.6-27b',
        NULL,
        true
    ),
    (
        'SIEM analyst access',
        'siem-access',
        '["wazuh access", "siem access", "alert index access", "security dashboard access", "read alerts", "analyst role", "wazuh dashboard"]',
        'UserRequest',
        'P2',
        'Identity & Access',
        'Identity & Access',
        'Security Operations Manager',
        '["Security Operations", "Compliance & Audit"]',
        '["Requester Manager"]',
        true,
        'Approve SIEM read role, alert index access, or dashboard group membership before granting access.',
        'medium',
        '["iam", "siem", "wazuh", "least-privilege"]',
        false,
        'qwen/qwen3.6-27b',
        NULL,
        true
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
    auto_assign_agent = EXCLUDED.auto_assign_agent,
    auto_agent_model = EXCLUDED.auto_agent_model,
    auto_agent_prompt = EXCLUDED.auto_agent_prompt,
    enabled = EXCLUDED.enabled,
    updated_at = NOW();

INSERT INTO agent_skills (name, description, category, prompt_template, enabled, assigned_to_all)
VALUES (
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
