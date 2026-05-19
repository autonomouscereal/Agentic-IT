-- Reconcile live/source defaults with the Hermes + external DeepSeek route.
-- Raw PostgreSQL only; no ORM-managed schema.

ALTER TABLE agents
    ALTER COLUMN model SET DEFAULT 'deepseek/deepseek-v4-flash';

ALTER TABLE agents
    ALTER COLUMN selected_model SET DEFAULT 'deepseek/deepseek-v4-flash';

ALTER TABLE service_raci_rules
    ALTER COLUMN auto_agent_model SET DEFAULT 'deepseek/deepseek-v4-flash';

UPDATE service_raci_rules
SET auto_agent_model = 'deepseek/deepseek-v4-flash',
    updated_at = NOW()
WHERE auto_assign_agent = true
  AND (
      auto_agent_model IS NULL
      OR auto_agent_model IN (
          'qwen/qwen3.6-27b',
          'qwen/qwen3.6-27b2',
          'qwen/qwen3.6-27b3',
          'qwen/qwen3.6-27b4',
          'qwen/qwen3.6-27b5'
      )
  );

UPDATE dashboard_settings
SET value = jsonb_set(
        COALESCE(value, '{}'::jsonb),
        '{model}',
        to_jsonb('deepseek/deepseek-v4-flash'::text),
        true
    )
WHERE key = 'agent_config'
  AND COALESCE(value->>'model', '') IN (
      '',
      'qwen/qwen3.6-27b',
      'qwen/qwen3.6-27b2',
      'qwen/qwen3.6-27b3',
      'qwen/qwen3.6-27b4',
      'qwen/qwen3.6-27b5'
  );
