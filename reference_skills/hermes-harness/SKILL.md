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
- Command path: `hermes chat -Q --query ... --toolsets terminal,file`

## Validation

Run these checks from the deployed dashboard host or inside the API container as
appropriate:

```bash
curl -sS http://localhost:4001/health
curl -sS http://localhost:4001/v1/models
curl -sS -H "X-Dashboard-Service-Token: <vault token>" http://localhost:25480/api/agents/runner-health
curl -sS -H "X-Dashboard-Service-Token: <vault token>" http://localhost:25480/api/agents/processes
```

Then run a short queue proof through the dashboard:

```bash
python3 scripts/smoke_setup_agent.py http://localhost:25480 deepseek/deepseek-v4-flash
```

For direct harness probes, use the operator's mounted Hermes auth state and
keep secrets out of command lines:

```bash
HERMES_ACCEPT_HOOKS=1 hermes chat -Q --provider nous -m deepseek/deepseek-v4-flash --toolsets terminal,file --max-turns 8 --source operator-smoke --query "Reply exactly HERMES_EXTERNAL_OK."
HERMES_ACCEPT_HOOKS=1 hermes chat -Q --provider dashboard-proxy -m qwen/qwen3.6-27b --toolsets terminal,file --max-turns 8 --source operator-smoke --query "Reply exactly HERMES_LOCAL_OK."
```

## Guardrails

- Do not pass Nous, OpenAI, Anthropic, or other provider tokens in source,
  screenshots, docs, or committed config.
- Use host/runtime auth state, environment injection, or vault-backed runtime
  configuration.
- Keep sudo disabled for queue workers by default. If a deployment truly needs
  host elevation, expose it through approval-gated provider actions or a
  vault-backed runtime secret specific to that environment.
- Use `terminal,file` for dashboard queue work. The old `hermes-cli` label is
  not a built-in toolset on the live Hermes v0.13.0 install.
- Use `hermes chat -Q --query` for dashboard queue work. Top-level `-z`
  can produce final text without enough tool-use evidence.
- Spawned agents use a scoped signed dashboard session plus curl guards for
  protected dashboard API calls; do not pass the trusted proxy secret or global
  service token to the harness.
- Judge agent health from runner-health, process state, proxy activity,
  output logs, checkpoints, ticket notes, audit records, and memory events, not
  `progress_pct` alone.
- Hermes/N Nous may return transient HTTP 503 capacity failures. The dashboard
  runner should preserve the workspace and requeue the same task using
  `AGENT_TRANSIENT_MODEL_RETRY_MAX` and
  `AGENT_TRANSIENT_MODEL_RETRY_DELAY_SECONDS`; do not treat a single provider
  capacity error as proof that the agentic flow is broken.

## Latest Proofs

2026-05-19:

- Setup smoke: ticket `613`, agent `248`, task `245`, completed at 100%.
- Access-wall approval/resume: ticket `614`, access child `615`, original
  agent `249`, resumed agent `250`, change `176`, access granted.
- Note steering: ticket `617`, iTop `UserRequest::398`, agent `252`, task
  `249`, dashboard and iTop steering events consumed, ticket resolved.
- Wazuh lease-gated access: ticket `618`, original agent `253`, resumed agent
  `254`, change `177`, Wazuh access granted.
- One-line installer alternate proof: setup ticket `1`, setup agent `1`,
  bounded `SETUP_ONBOARDING_BOOTSTRAP_COMPLETE` note, task completed at 100%.
- Live route reconciliation: `AGENT_LLM_BASE_URL=http://ai-proxy:4001` inside
  Docker, deployment-host local proxy on `localhost:4401`, post-route smoke
  ticket `620`, agent `255`, task `252`, no active processes after hook
  shutdown.
- Complex live Hermes proof: ticket `621`, iTop `Incident::401`, agents
  `256`/`257`/`258`, Wazuh access request `29`, gates `178` and `179`,
  postmortem `105`, workflow `4` updated, no active processes afterward.
