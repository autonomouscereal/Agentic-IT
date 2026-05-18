---
name: hermes-harness
description: >
  Configure, validate, and troubleshoot Hermes Agent as a first-class Agentic
  Operations dashboard harness. Use when checking Hermes CLI availability,
  Nous Portal auth, dashboard-proxy routing, model selection, memory hooks,
  least-privilege execution, or runner-health evidence.
---

# Hermes Harness

Use this skill when the Agentic Operations platform is configured with
`AGENT_HARNESS=hermes`, or when onboarding a new deployment that may use Hermes
instead of Claude Code.

## Contract

- Runner integration: `api/services/agent_harness.py`
- Primary docs: `docs/HERMES_HARNESS.md`
- Preferred default model: `deepseek/deepseek-v4-flash`
- External provider route: `nous`
- Local/provider-proxy route: `dashboard-proxy`
- Model gateway: `AGENT_LLM_BASE_URL`, normally `http://ai-proxy:4001` inside Docker
- Workspace context: `AGENTS.md` plus `.claude/CLAUDE.md`
- Checkpoint file: `checkpoint.json`
- Memory: PostgreSQL agent-memory hooks, never local-only logs as the primary audit trail

## Validation

Run these checks from the deployed dashboard host or inside the API container as
appropriate:

```bash
curl -sS http://localhost:4001/health
curl -sS http://localhost:4001/v1/models
curl -sS http://localhost:25480/api/agents/runner-health
curl -sS http://localhost:25480/api/agents/processes
```

Then run a short queue proof through the dashboard:

```bash
python3 scripts/smoke_local_model_agent.py http://localhost:25480 deepseek/deepseek-v4-flash
```

For direct harness probes, use the operator's mounted Hermes auth state and
keep secrets out of command lines:

```bash
HERMES_ACCEPT_HOOKS=1 hermes --provider nous -m deepseek/deepseek-v4-flash --toolsets hermes-cli -z "Reply exactly HERMES_EXTERNAL_OK."
HERMES_ACCEPT_HOOKS=1 hermes --provider dashboard-proxy -m qwen/qwen3.6-27b --toolsets hermes-cli -z "Reply exactly HERMES_LOCAL_OK."
```

## Guardrails

- Do not pass Nous, OpenAI, Anthropic, or other provider tokens in source,
  screenshots, docs, or committed config.
- Use host/runtime auth state, environment injection, or vault-backed runtime
  configuration.
- Keep sudo disabled for queue workers by default. If a deployment truly needs
  host elevation, expose it through approval-gated provider actions or a
  vault-backed runtime secret specific to that environment.
- Do not add unsupported Hermes CLI flags to dashboard argv. Hermes v0.13.0
  does not support `--source` or `--max-turns`; use environment metadata and
  dashboard supervision instead.
- Judge agent health from runner-health, process state, proxy activity,
  output logs, checkpoints, ticket notes, audit records, and memory events, not
  `progress_pct` alone.
