-- Baseline global skills required by fresh installs.
-- Raw PostgreSQL only. Idempotent by skill name.

INSERT INTO agent_skills (name, description, category, prompt_template, enabled, assigned_to_all)
VALUES
    (
        'ticket-context-reader',
        'Fetch the full dashboard context bundle for a ticket before taking action.',
        'ticketing',
        'Use GET /api/tickets/{ticket_id}/context before working. Review ticket, notes, attachments, related tickets, knowledge articles, workflows, postmortems, change requests, and assigned skills.',
        true,
        true
    ),
    (
        'ticket-note-writer',
        'Write concise internal or user-visible ticket notes.',
        'ticketing',
        'Use POST /api/tickets/{ticket_id}/notes with body, author, source, and visibility. Summarize evidence, actions, blockers, approvals, and next steps.',
        true,
        true
    ),
    (
        'change-request-gate',
        'Create and poll approval-gated change requests before risky actions.',
        'change-management',
        'Before any environment-changing or destructive action, POST /api/changes/request with action, target, reason, command, and risk_level. Poll GET /api/changes/{change_id}/status until approved or rejected. Do not proceed unless approved.',
        true,
        true
    ),
    (
        'postmortem-builder',
        'Create structured postmortems after ticket completion.',
        'learning',
        'Use POST /api/postmortems to record summary, what worked, improvements, workflow proposal, skill proposals, tests, guardrails, and documentation. Mark status ready_for_review when complete.',
        true,
        true
    ),
    (
        'workflow-builder',
        'Create reusable workflow blueprints from completed work.',
        'automation',
        'Use POST /api/workflows to create draft workflows with blueprint, test_plan, approval_policy, and required skill ids. Keep workflows in draft/tested until reviewed.',
        true,
        true
    ),
    (
        'phishing-triage',
        'Reusable phishing investigation checklist.',
        'security',
        'For phishing: extract sender, recipients, headers, URLs, attachments, authentication results, delivery scope, and risk. Defang URLs in notes. Request approval before mailbox remediation, blocking, quarantine, or account changes.',
        true,
        false
    )
ON CONFLICT (name) DO UPDATE SET
    description = EXCLUDED.description,
    category = EXCLUDED.category,
    prompt_template = EXCLUDED.prompt_template,
    enabled = EXCLUDED.enabled,
    assigned_to_all = EXCLUDED.assigned_to_all,
    updated_at = NOW();
