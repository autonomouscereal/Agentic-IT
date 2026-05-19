-- RACI-driven auto agent assignment policy.
-- Raw PostgreSQL only; no ORM-managed schema.

ALTER TABLE service_raci_rules
    ADD COLUMN IF NOT EXISTS auto_assign_agent BOOLEAN NOT NULL DEFAULT false,
    ADD COLUMN IF NOT EXISTS auto_agent_model VARCHAR(200) DEFAULT 'deepseek/deepseek-v4-flash',
    ADD COLUMN IF NOT EXISTS auto_agent_prompt TEXT;

UPDATE service_raci_rules
SET auto_assign_agent = true,
    auto_agent_model = COALESCE(auto_agent_model, 'deepseek/deepseek-v4-flash'),
    auto_agent_prompt = COALESCE(
        auto_agent_prompt,
        'Auto-work Security Operations phishing tickets end to end. Read all canonical context and provider evidence, create approval gates for remediation actions, complete approved lab-safe actions with evidence, and recommend postmortem/workflow improvements.'
    ),
    updated_at = NOW()
WHERE name = 'Phishing report';

CREATE INDEX IF NOT EXISTS idx_service_raci_rules_auto_agent
    ON service_raci_rules(auto_assign_agent)
    WHERE enabled = true;
