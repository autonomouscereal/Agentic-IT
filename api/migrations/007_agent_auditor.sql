-- Agent auditor reviews agent progress, detects drift/stalls, and records recovery actions.

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

CREATE INDEX IF NOT EXISTS idx_agent_audit_reviews_agent ON agent_audit_reviews(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_audit_reviews_task ON agent_audit_reviews(task_id);
CREATE INDEX IF NOT EXISTS idx_agent_audit_reviews_created ON agent_audit_reviews(created_at);
