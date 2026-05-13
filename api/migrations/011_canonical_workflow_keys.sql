ALTER TABLE agent_workflows
    ADD COLUMN IF NOT EXISTS workflow_key VARCHAR(160);

UPDATE agent_workflows
SET workflow_key = CASE
    WHEN lower(name || ' ' || COALESCE(description, '') || ' ' || COALESCE(blueprint, '')) LIKE '%phish%'
      OR lower(name || ' ' || COALESCE(description, '') || ' ' || COALESCE(blueprint, '')) LIKE '%credential harvest%'
      OR lower(name || ' ' || COALESCE(description, '') || ' ' || COALESCE(blueprint, '')) LIKE '%suspicious email%'
      THEN regexp_replace(lower(COALESCE(ticket_class, 'global')), '[^a-z0-9]+', '-', 'g') || ':phishing'
    WHEN lower(name || ' ' || COALESCE(description, '') || ' ' || COALESCE(blueprint, '')) LIKE '%sysmon%'
      OR lower(name || ' ' || COALESCE(description, '') || ' ' || COALESCE(blueprint, '')) LIKE '%edr%'
      OR lower(name || ' ' || COALESCE(description, '') || ' ' || COALESCE(blueprint, '')) LIKE '%wazuh alert%'
      THEN regexp_replace(lower(COALESCE(ticket_class, 'global')), '[^a-z0-9]+', '-', 'g') || ':edr-sysmon'
    WHEN lower(name || ' ' || COALESCE(description, '') || ' ' || COALESCE(blueprint, '')) LIKE '%ci/cd%'
      OR lower(name || ' ' || COALESCE(description, '') || ' ' || COALESCE(blueprint, '')) LIKE '%semgrep%'
      OR lower(name || ' ' || COALESCE(description, '') || ' ' || COALESCE(blueprint, '')) LIKE '%trivy%'
      OR lower(name || ' ' || COALESCE(description, '') || ' ' || COALESCE(blueprint, '')) LIKE '%owasp zap%'
      OR lower(name || ' ' || COALESCE(description, '') || ' ' || COALESCE(blueprint, '')) LIKE '%nuclei%'
      THEN regexp_replace(lower(COALESCE(ticket_class, 'global')), '[^a-z0-9]+', '-', 'g') || ':cicd-security'
    ELSE regexp_replace(lower(COALESCE(ticket_class, 'global')), '[^a-z0-9]+', '-', 'g') || ':' ||
         substring(regexp_replace(lower(name), '[^a-z0-9]+', '-', 'g') from 1 for 80)
END
WHERE workflow_key IS NULL OR workflow_key = '';

UPDATE agent_workflows
SET workflow_key = 'incident:phishing',
    status = 'active',
    reviewed_by = COALESCE(reviewed_by, 'codex-workflow-canonicalization'),
    reviewed_at = COALESCE(reviewed_at, NOW()),
    test_results = COALESCE(test_results, '') ||
        CASE WHEN COALESCE(test_results, '') = '' THEN '' ELSE E'\n' END ||
        'Canonicalized as the single active phishing workflow after duplicate workflow audit.',
    updated_at = NOW()
WHERE name = 'phishing-smoke-lifecycle';

WITH ranked AS (
    SELECT w.id,
           w.workflow_key,
           ROW_NUMBER() OVER (
               PARTITION BY w.workflow_key
               ORDER BY
                 CASE WHEN w.name = 'phishing-smoke-lifecycle' THEN 0 ELSE 1 END,
                 CASE WHEN w.status = 'active' AND w.reviewed_at IS NOT NULL THEN 0
                      WHEN w.status = 'active' THEN 1
                      WHEN w.status = 'approved' THEN 2
                      ELSE 3
                 END,
                 COALESCE(run_stats.completed_count, 0) DESC,
                 w.updated_at DESC
           ) AS rank_num
    FROM agent_workflows w
    LEFT JOIN LATERAL (
        SELECT COUNT(*) FILTER (WHERE status IN ('completed', 'passed')) AS completed_count
        FROM workflow_runs wr
        WHERE wr.workflow_id = w.id
    ) run_stats ON true
    WHERE w.workflow_key IS NOT NULL
      AND w.status IN ('active', 'approved')
)
UPDATE agent_workflows w
SET status = 'superseded',
    test_results = COALESCE(w.test_results, '') ||
        CASE WHEN COALESCE(w.test_results, '') = '' THEN '' ELSE E'\n' END ||
        'Superseded during canonical workflow-key cleanup; only one workflow per key may remain active.',
    updated_at = NOW()
FROM ranked r
WHERE w.id = r.id
  AND r.rank_num > 1;

UPDATE agent_workflows
SET approval_policy = COALESCE(approval_policy, '{}'::jsonb) || jsonb_build_object('workflow_key', workflow_key)
WHERE workflow_key IS NOT NULL
  AND NOT (COALESCE(approval_policy, '{}'::jsonb) ? 'workflow_key');

CREATE INDEX IF NOT EXISTS idx_agent_workflows_workflow_key
    ON agent_workflows(workflow_key);

CREATE UNIQUE INDEX IF NOT EXISTS ux_agent_workflows_active_workflow_key
    ON agent_workflows(workflow_key)
    WHERE workflow_key IS NOT NULL AND status IN ('active', 'approved');
