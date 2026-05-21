-- Codex harness + animation/file artifact support.
-- Raw PostgreSQL only; no ORM-managed schema.

INSERT INTO agent_skills (name, description, category, prompt_template, enabled, assigned_to_all)
VALUES
(
    'codex-harness',
    'Configure, validate, and troubleshoot OpenAI Codex CLI as an Agentic Operations harness behind the AI proxy.',
    'agent-harness',
    'Use the codex-harness skill when selecting or testing the Codex CLI harness. Route Codex through the dashboard AI proxy with runtime/vault auth only, never committed secrets.',
    true,
    true
),
(
    'animation-video',
    'Create, render, and validate deterministic MP4/GIF/WebM animation artifacts for diagrams, explainers, chat demos, and UI motion.',
    'artifact-generation',
    'Use animation-video for user requests that need a short code-rendered animation. Render deterministically, validate the video artifact, and return the resulting file through Ops Chat when appropriate.',
    true,
    true
)
ON CONFLICT (name) DO UPDATE SET
    description = EXCLUDED.description,
    category = EXCLUDED.category,
    prompt_template = EXCLUDED.prompt_template,
    enabled = true,
    assigned_to_all = true;

INSERT INTO tools (name, type, host, port, description)
VALUES (
    'Codex Agent Harness',
    'agent-harness',
    'api',
    0,
    'OpenAI Codex CLI harness option for dashboard agents, routed through the Agentic Operations AI proxy.'
)
ON CONFLICT (name) DO UPDATE SET
    type = EXCLUDED.type,
    host = EXCLUDED.host,
    port = EXCLUDED.port,
    description = EXCLUDED.description,
    updated_at = NOW();
