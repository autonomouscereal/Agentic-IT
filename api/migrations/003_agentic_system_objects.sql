-- First-class agentic SOC objects for notes, context, postmortems, workflows, and approval-gated actions.
-- Raw PostgreSQL only.

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

ALTER TABLE change_requests ADD COLUMN IF NOT EXISTS risk_level VARCHAR(40) DEFAULT 'unknown';
ALTER TABLE change_requests ADD COLUMN IF NOT EXISTS approval_policy JSONB DEFAULT '{}';
ALTER TABLE tickets ADD COLUMN IF NOT EXISTS provider VARCHAR(80) DEFAULT 'itop';
ALTER TABLE tickets ADD COLUMN IF NOT EXISTS provider_ref VARCHAR(200);
ALTER TABLE tickets ADD COLUMN IF NOT EXISTS provider_class VARCHAR(120);
ALTER TABLE tickets ADD COLUMN IF NOT EXISTS provider_url TEXT;
ALTER TABLE tickets ADD COLUMN IF NOT EXISTS provider_sync_status VARCHAR(40) DEFAULT 'unknown';
ALTER TABLE tickets ADD COLUMN IF NOT EXISTS provider_last_error TEXT;
ALTER TABLE tickets ADD COLUMN IF NOT EXISTS provider_payload JSONB DEFAULT '{}';

UPDATE tickets
SET provider = COALESCE(provider, CASE WHEN itop_ref LIKE 'LOCAL-%' THEN 'local' ELSE 'itop' END),
    provider_ref = COALESCE(provider_ref, itop_ref),
    provider_class = COALESCE(provider_class, itop_class),
    provider_sync_status = COALESCE(provider_sync_status, CASE WHEN itop_ref LIKE 'LOCAL-%' THEN 'local_only' ELSE 'synced' END);

CREATE INDEX IF NOT EXISTS idx_ticket_notes_ticket_id ON ticket_notes(ticket_id);
CREATE INDEX IF NOT EXISTS idx_ticket_notes_created_at ON ticket_notes(created_at);
CREATE INDEX IF NOT EXISTS idx_ticket_attachments_ticket_id ON ticket_attachments(ticket_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_articles_enabled ON knowledge_articles(enabled);
CREATE INDEX IF NOT EXISTS idx_postmortems_ticket_id ON postmortems(ticket_id);
CREATE INDEX IF NOT EXISTS idx_postmortems_status ON postmortems(status);
CREATE INDEX IF NOT EXISTS idx_agent_workflows_status ON agent_workflows(status);
CREATE INDEX IF NOT EXISTS idx_agent_workflows_ticket_class ON agent_workflows(ticket_class);
CREATE INDEX IF NOT EXISTS idx_workflow_runs_workflow_id ON workflow_runs(workflow_id);
CREATE INDEX IF NOT EXISTS idx_tickets_provider_ref ON tickets(provider, provider_ref);

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
