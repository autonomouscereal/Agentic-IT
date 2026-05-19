ALTER TABLE dashboard_users
    ADD COLUMN IF NOT EXISTS password_hash TEXT,
    ADD COLUMN IF NOT EXISTS password_changed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS failed_login_count INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS last_failed_login_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_login_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS idx_dashboard_users_enabled_login
    ON dashboard_users(username, enabled)
    WHERE password_hash IS NOT NULL;
