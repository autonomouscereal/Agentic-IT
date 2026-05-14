-- Non-interrupting ticket note steering for active agents.
-- Raw PostgreSQL only; no ORM-managed schema.

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

CREATE INDEX IF NOT EXISTS idx_agent_steering_events_agent_status
    ON agent_steering_events(agent_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_agent_steering_events_ticket_created
    ON agent_steering_events(ticket_id, created_at DESC);

CREATE UNIQUE INDEX IF NOT EXISTS idx_agent_steering_events_agent_note_once
    ON agent_steering_events(agent_id, note_id)
    WHERE note_id IS NOT NULL;
