-- Seed the shared PostgreSQL agent memory skill for existing deployments.
-- Raw PostgreSQL only. Idempotent by skill name.

INSERT INTO agent_skills (name, description, category, prompt_template, enabled, assigned_to_all)
VALUES (
    'agent-memory',
    'Search and write durable shared agent memory through the PostgreSQL memory service.',
    'memory',
    'Before substantial work, search shared memory for relevant prior context with the agent-memory skill or scripts/agent_memory.py. After meaningful completion, store a concise durable note with the outcome, test evidence, changed files, and any caveats. Do not store secrets; use redacted placeholders or vault references.',
    true,
    true
)
ON CONFLICT (name) DO UPDATE SET
    description = EXCLUDED.description,
    category = EXCLUDED.category,
    prompt_template = EXCLUDED.prompt_template,
    enabled = EXCLUDED.enabled,
    assigned_to_all = EXCLUDED.assigned_to_all,
    updated_at = NOW();
