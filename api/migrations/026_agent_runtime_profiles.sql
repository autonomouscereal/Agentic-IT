-- Agent runtime profile tracking for harness/model/reasoning settings.
-- Raw PostgreSQL only; no ORM migration framework.

ALTER TABLE agents
    ADD COLUMN IF NOT EXISTS harness VARCHAR(80);

ALTER TABLE agents
    ADD COLUMN IF NOT EXISTS runtime_profile_id VARCHAR(80);

ALTER TABLE agents
    ADD COLUMN IF NOT EXISTS runtime_config JSONB NOT NULL DEFAULT '{}';
