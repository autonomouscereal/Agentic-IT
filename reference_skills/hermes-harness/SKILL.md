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
- Preferred product default model: `local/agent-default`
- Preferred product default route: `dashboard-proxy` through
  `AI_MODEL_ROUTE=local`
- External lab model: `deepseek/deepseek-v4-flash`
- External lab provider route: `nous`
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
python3 scripts/smoke_setup_agent.py http://localhost:25480 local/agent-default
```

For direct harness probes, use the operator's mounted Hermes auth state and
keep secrets out of command lines:

```bash
HERMES_ACCEPT_HOOKS=1 hermes chat -Q --provider dashboard-proxy -m local/agent-default --toolsets terminal,file --max-turns 8 --source operator-smoke --query "Reply exactly HERMES_LOCAL_OK."
python scripts/switch_model_route.py --route external --restart
HERMES_ACCEPT_HOOKS=1 hermes chat -Q --provider nous -m deepseek/deepseek-v4-flash --toolsets terminal,file --max-turns 8 --source operator-smoke --query "Reply exactly HERMES_EXTERNAL_OK."
python scripts/switch_model_route.py --route local --restart
```

For the current live lab, switch route profiles on server `ai` from
`/opt/agentic-it/SOC_TESTING/soc-dashboard` through the `server-manager` skill.
The live proxy is `http://ai-proxy:4001` inside Docker and
`http://127.0.0.1:4001` from the LAN:

```bash
cd /opt/agentic-it/SOC_TESTING/soc-dashboard
python3 scripts/switch_model_route.py --route external --restart
curl -sS -X POST http://127.0.0.1:4001/api/route \
  -H 'Content-Type: application/json' \
  -d '{"model":"deepseek/deepseek-v4-flash"}'
```

Use `--route local --restart` to return to local/on-prem posture before
customer or government demos that should not use external providers.

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
- The API/agent image includes Node.js plus Playwright Chromium for trusted
  internal UI validation. Agents may use `node`, `npx playwright`, or
  `playwright` for dashboard, setup, CI/CD, provider-console, or generated
  local app checks. `NODE_PATH` is set so `require("playwright")` works from
  small agent-written scripts.
- Suspicious URLs from tickets, reports, alerts, or email evidence are hostile
  until proven otherwise. Hermes agents must not directly browse, curl, wget,
  screenshot, Playwright-open, or fetch those URLs from the runner or
  production network. Use passive evidence, configured
  VirusTotal/urlscan/ANY.RUN-style adapters, or an approved isolated detonation
  service. Approval to block or quarantine a URL is not approval to fetch it.
- Judge agent health from runner-health, process state, proxy activity,
  output logs, checkpoints, ticket notes, audit records, and memory events, not
  `progress_pct` alone.
- Hermes/Nous or OpenRouter may return transient HTTP 429/503 capacity
  failures. The dashboard runner should preserve the workspace and requeue the
  same task using
  `AGENT_TRANSIENT_MODEL_RETRY_MAX` and
  `AGENT_TRANSIENT_MODEL_RETRY_DELAY_SECONDS`; do not treat a single provider
  capacity error as proof that the agentic flow is broken. If retries are
  exhausted and `AGENT_TRANSIENT_MODEL_FALLBACK_ENABLED=true`, the runner
  switches the same task to `AGENT_TRANSIENT_MODEL_FALLBACK_MODEL` with an
  explicit ticket note and `agent_transient_model_fallback_scheduled` audit
  event. Product default policy is local/on-prem first. The lab external route
  is Hermes/DeepSeek via Nous first, OpenRouter (`openrouter/free`) as the
  first external proxy fallback, and local qwen only as final fallback.

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
  Docker and host/LAN proxy on port `4001`; post-route smoke ticket `620`,
  agent `255`, task `252`, no active processes after hook shutdown. The later
  2026-05-19 cleanup removed the temporary host `4401` mapping and the old
  standalone `ai-proxy` container.
- Complex live Hermes regression case: ticket `621`, iTop `Incident::401`,
  agents `256`/`257`/`258`, Wazuh access request `29`, gates `178` and `179`,
  postmortem `105`, workflow `4` updated, no active processes afterward. This
  ticket is not a lead demo proof because review found unsafe direct suspicious
  URL retrieval semantics; use ticket `531` for the phishing/EDR demo story and
  use `621` only to explain the URL-safety guardrail regression.
- URL guard real-agent regression: ticket `632`, agent `259`, task `256`,
  model `qwen/qwen3.6-27b`; the runtime guard blocked the synthetic suspicious
  URL, the agent wrote `REGRESSION_URL_GUARD_BLOCKED`, and no active processes
  remained afterward.
- URL-safe complex phishing/EDR proof: ticket `690`, iTop `Incident::470`,
  agents `265`/`266`/`267`, Wazuh access request `31`, gates `181` and `182`,
  postmortem `106`, URL sandbox attachment `92`, workflow `4` updated, ticket
  resolved, and no active processes remained. The run started on
  `deepseek/deepseek-v4-flash`, showed provider retries in notes/audit, did
  not fetch the suspicious URL directly, and DeepSeek recovered before local
  fallback was required.
- OpenRouter fallback proof: direct `openrouter/free` returned a tool call,
  proxy `/v1/models` advertised OpenRouter aliases, and proxy chat for
  `deepseek/deepseek-v4-flash` successfully fell through to OpenRouter when
  Nous auth/capacity was unavailable.
- Fresh URL-safe phishing/EDR hybrid proof: ticket `695`, iTop
  `Incident::475`, agents `273`/`274`, gates `185`/`186`, postmortem `107`.
  It preserved requester/user-response and approval evidence, avoided direct
  suspicious URL retrieval, then exposed and fixed ticket/provider status drift
  by resolving from terminal evidence with compact iTop close notes.
- Approval audit proof: changes `181` and `182` show `demo_account_1` as
  `approved_by` / `approval_actor` in audit and event details.
