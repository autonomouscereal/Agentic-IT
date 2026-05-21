-- Track who opened a ticket, who requested the work, and who is affected.
-- Raw PostgreSQL only.

ALTER TABLE tickets
    ADD COLUMN IF NOT EXISTS opened_by_name VARCHAR(240),
    ADD COLUMN IF NOT EXISTS opened_by_email VARCHAR(300),
    ADD COLUMN IF NOT EXISTS requester_name VARCHAR(240),
    ADD COLUMN IF NOT EXISTS requester_email VARCHAR(300),
    ADD COLUMN IF NOT EXISTS affected_user_name VARCHAR(240),
    ADD COLUMN IF NOT EXISTS affected_user_email VARCHAR(300);

CREATE INDEX IF NOT EXISTS idx_tickets_requester_email ON tickets (lower(requester_email));
CREATE INDEX IF NOT EXISTS idx_tickets_affected_user_email ON tickets (lower(affected_user_email));
