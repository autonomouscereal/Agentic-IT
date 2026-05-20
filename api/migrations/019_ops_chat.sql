-- Ops Chat Matrix/Element client and real agent-harness intake bridge.
-- Raw PostgreSQL only; no ORM-managed schema.

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

ALTER TABLE ops_chat_sessions ADD COLUMN IF NOT EXISTS external_thread_id TEXT;
ALTER TABLE ops_chat_sessions ADD COLUMN IF NOT EXISTS latest_ticket_id INTEGER REFERENCES tickets(id) ON DELETE SET NULL;

CREATE TABLE IF NOT EXISTS ops_chat_messages (
    id SERIAL PRIMARY KEY,
    session_id INTEGER NOT NULL REFERENCES ops_chat_sessions(id) ON DELETE CASCADE,
    role VARCHAR(40) NOT NULL,
    body TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    ticket_id INTEGER REFERENCES tickets(id) ON DELETE SET NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ops_chat_messages_session_created
    ON ops_chat_messages (session_id, created_at);

CREATE INDEX IF NOT EXISTS idx_ops_chat_messages_ticket
    ON ops_chat_messages (ticket_id);

CREATE INDEX IF NOT EXISTS idx_ops_chat_sessions_external_thread
    ON ops_chat_sessions (external_thread_id);

CREATE INDEX IF NOT EXISTS idx_ops_chat_sessions_latest_ticket
    ON ops_chat_sessions (latest_ticket_id);

INSERT INTO tools (name, type, host, port, description)
VALUES (
    'Element Ops Chat',
    'chat-ui',
    'host.docker.internal',
    3301,
    'Element Web Matrix client connected to the Agentic Operations intake bridge.'
), (
    'Matrix Synapse Ops Chat',
    'chat',
    'host.docker.internal',
    3302,
    'Matrix Synapse homeserver for real chat intake with Keycloak OIDC.'
), (
    'Ops Chat Matrix Bridge',
    'bridge',
    'ops-chat-bridge',
    29318,
    'Matrix application-service bridge that creates dashboard tickets and queues real agents.'
)
ON CONFLICT (name) DO UPDATE SET
    type = EXCLUDED.type,
    host = EXCLUDED.host,
    port = EXCLUDED.port,
    description = EXCLUDED.description,
    updated_at = NOW();

DELETE FROM tools WHERE name = 'Open WebUI Ops Chat';

UPDATE service_raci_rules
SET auto_assign_agent = true,
    auto_agent_model = COALESCE(auto_agent_model, 'local/agent-default'),
    auto_agent_prompt = 'Auto-work Identity & Access chat intake tickets safely. Required actions: read compact ticket context, identify whether this is account lockout, MFA, password reset, or access denial; ask the user for one concise clarification if needed; check related tickets/known outage evidence from dashboard context; do not change credentials or entitlements without an approval gate; create an approval-gated change for password reset, MFA reset, session revocation, or account unlock when required; write a user-readable resolution or next-step note; if no action is possible without external IAM integration, document the missing integration and keep the ticket routed to Identity & Access.',
    updated_at = NOW()
WHERE name = 'Account locked or MFA help';
