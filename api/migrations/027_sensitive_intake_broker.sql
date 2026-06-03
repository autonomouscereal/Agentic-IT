-- General sensitive intake broker.
-- Stores encrypted values behind references so raw sensitive data does not
-- enter chat transcripts, tickets, provider sync payloads, event logs, or
-- agent prompts.

CREATE TABLE IF NOT EXISTS sensitive_intake_requests (
    id SERIAL PRIMARY KEY,
    request_ref VARCHAR(80) NOT NULL UNIQUE,
    form_token_hash VARCHAR(128) NOT NULL UNIQUE,
    status VARCHAR(40) NOT NULL DEFAULT 'pending',
    purpose TEXT NOT NULL DEFAULT '',
    ticket_id INTEGER REFERENCES tickets(id) ON DELETE SET NULL,
    session_id INTEGER REFERENCES ops_chat_sessions(id) ON DELETE SET NULL,
    requested_by VARCHAR(240) NOT NULL DEFAULT 'system',
    requester_name VARCHAR(240),
    requester_email VARCHAR(300),
    channel VARCHAR(80) NOT NULL DEFAULT 'dashboard',
    fields JSONB NOT NULL DEFAULT '[]',
    metadata JSONB NOT NULL DEFAULT '{}',
    expires_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '24 hours'),
    submitted_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sensitive_intake_values (
    id SERIAL PRIMARY KEY,
    value_ref VARCHAR(80) NOT NULL UNIQUE,
    request_id INTEGER NOT NULL REFERENCES sensitive_intake_requests(id) ON DELETE CASCADE,
    field_key VARCHAR(120) NOT NULL,
    field_label VARCHAR(240) NOT NULL,
    field_type VARCHAR(80) NOT NULL DEFAULT 'freeform_sensitive',
    ciphertext TEXT NOT NULL,
    value_sha256 VARCHAR(64) NOT NULL,
    value_len INTEGER NOT NULL DEFAULT 0,
    submitted_by VARCHAR(240),
    status VARCHAR(40) NOT NULL DEFAULT 'submitted',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (request_id, field_key)
);

CREATE TABLE IF NOT EXISTS sensitive_intake_events (
    id SERIAL PRIMARY KEY,
    request_id INTEGER REFERENCES sensitive_intake_requests(id) ON DELETE CASCADE,
    actor VARCHAR(240) NOT NULL DEFAULT 'system',
    action VARCHAR(120) NOT NULL,
    details JSONB NOT NULL DEFAULT '{}',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sensitive_intake_requests_ticket
    ON sensitive_intake_requests(ticket_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_sensitive_intake_requests_session
    ON sensitive_intake_requests(session_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_sensitive_intake_requests_status
    ON sensitive_intake_requests(status, expires_at);

CREATE INDEX IF NOT EXISTS idx_sensitive_intake_values_request
    ON sensitive_intake_values(request_id);

CREATE INDEX IF NOT EXISTS idx_sensitive_intake_events_request
    ON sensitive_intake_events(request_id, created_at DESC);
