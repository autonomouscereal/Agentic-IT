-- Harden agent runner schema for existing deployments.
-- Raw PostgreSQL only.

ALTER TABLE tickets DROP CONSTRAINT IF EXISTS tickets_itop_ref_key;
ALTER TABLE tickets DROP CONSTRAINT IF EXISTS tickets_itop_ref_class_unique;
ALTER TABLE tickets
    ADD CONSTRAINT tickets_itop_ref_class_unique UNIQUE (itop_ref, itop_class);

ALTER TABLE agents ADD COLUMN IF NOT EXISTS selected_model VARCHAR(200) DEFAULT 'deepseek/deepseek-v4-flash';
ALTER TABLE agents ADD COLUMN IF NOT EXISTS last_task_id INTEGER;

ALTER TABLE agent_tasks ADD COLUMN IF NOT EXISTS work_dir VARCHAR(500);
CREATE INDEX IF NOT EXISTS idx_agent_tasks_agent_id ON agent_tasks(agent_id);
CREATE INDEX IF NOT EXISTS idx_agent_tasks_status ON agent_tasks(status);
CREATE INDEX IF NOT EXISTS idx_agent_tasks_ticket_id ON agent_tasks(ticket_id);

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
CREATE INDEX IF NOT EXISTS idx_event_log_created_at ON event_log(created_at);
CREATE INDEX IF NOT EXISTS idx_event_log_category ON event_log(category);
CREATE INDEX IF NOT EXISTS idx_event_log_level ON event_log(level);
