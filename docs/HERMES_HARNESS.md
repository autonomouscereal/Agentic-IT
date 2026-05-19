# Hermes Harness Integration

Last updated: 2026-05-19.

Hermes Agent is supported as a first-class dashboard harness alongside Claude
Code. Use `AGENT_HARNESS=hermes` to make it the default queue worker.

## Runtime Contract

- Dashboard runner: `api/services/agent_harness.py`
- Default model: `deepseek/deepseek-v4-flash`
- Default provider: `nous`
- Local provider: `dashboard-proxy`
- Workspace context: `AGENTS.md` plus `.claude/CLAUDE.md`
- Checkpoint: `checkpoint.json` in the agent work directory
- Shared memory: Hermes shell hooks call the PostgreSQL agent-memory hook
- Source marker: `HERMES_AGENT_SOURCE=soc-dashboard` environment variable

Hermes reads project context from `AGENTS.md`, so the runner writes the same
ticket, approval, vault, steering, and checkpoint instructions to both
`AGENTS.md` and `.claude/CLAUDE.md`.

## Required Environment

```ini
AGENT_HARNESS=hermes
AGENT_LLM_BASE_URL=http://<proxy-host>:4001
AGENT_LLM_AUTH_TOKEN=
HERMES_BIN=/home/cereal/.hermes/hermes-agent/venv/bin/hermes
HERMES_HOME=/home/cereal/.hermes
HERMES_HOME_DIR=/home/cereal/.hermes
HERMES_UV_PYTHON_DIR=/home/cereal/.local/share/uv
HERMES_DEFAULT_PROVIDER=nous
HERMES_LOCAL_PROVIDER=dashboard-proxy
HERMES_AGENT_SOURCE=soc-dashboard
HERMES_TOOLSETS=terminal,file
HERMES_MAX_TURNS=90
HERMES_RUN_AS_UID=1000
HERMES_RUN_AS_GID=1000
HERMES_RUN_HOME=/home/cereal
HERMES_RUN_USER=cereal
HOME=/home/cereal
USER=cereal
LOGNAME=cereal
XDG_CACHE_HOME=/home/cereal/.cache
AGENT_TRANSIENT_MODEL_RETRY_MAX=3
AGENT_TRANSIENT_MODEL_RETRY_DELAY_SECONDS=30
AGENT_TRANSIENT_MODEL_FALLBACK_ENABLED=true
AGENT_TRANSIENT_MODEL_FALLBACK_MODEL=qwen/qwen3.6-27b
```

For the lab deployment, mount the host Hermes home into the API container at
the same path. Hermes was installed with uv, so also mount the uv-managed
Python runtime at `/home/cereal/.local/share/uv`. This preserves the Nous
Portal OAuth/agent-key state without copying secrets into the repository.

## Proxy Providers

The reference proxy in `deploy/ai-proxy/ai_proxy.py` supports:

- `GET /v1/models`
- `POST /v1/messages` for Claude Code / Anthropic-compatible traffic
- `POST /v1/chat/completions` for Hermes / OpenAI-compatible traffic

Routing policy:

- `deepseek/deepseek-v4-flash` goes to Nous Portal through the caller's bearer
  token, or `NOUS_API_KEY` when provided by deployment vault/runtime.
- `qwen/*`, `lmstudio/*`, or requests with token `lmstudio` go to LM Studio.
- `anthropic/claude-*` messages traffic goes to Anthropic unless the local
  token forces local routing.

## Hooks

Hermes hook events are different from Claude Code hooks. Configure shell hooks
for the closest equivalent events:

- `on_session_start` -> `UserPromptSubmit`
- `post_tool_call` -> `PostToolUse`
- `on_session_end` and `on_session_finalize` -> `Stop`

Use a wrapper script that locates `agent_memory_hook.py` from either
`/root/.agents/skills/agent-memory/scripts/` inside the API container or the
deployed `reference_skills/agent-memory/scripts/` path on the host. Hooks must
exit zero so memory failures never break agent work.

## Sudo Policy

The dashboard sets `SUDO_PASSWORD` to empty for Hermes harness processes by
default and launches Hermes through `setpriv` as uid/gid `1000` in the current
lab. This disables password-backed sudo in the agent worker even if the
operator enabled sudo in the interactive Hermes setup, and it prevents the API
container root process from taking ownership of the host Hermes auth files.
The runner also sets `HOME`, `USER`, `LOGNAME`, and `XDG_CACHE_HOME` to the
mounted Hermes user's home before invoking `setpriv`, overriding the API
container's inherited `/root` home; otherwise Python
dependencies used by Hermes can still resolve the API container's `/root`
home after privileges are dropped. If a deployment truly needs elevated host
operations, expose that through a scoped approval-gated provider adapter or set
`HERMES_SUDO_PASSWORD` from a vault-backed runtime secret for that environment
only.

## Validation

Minimum validation after deployment:

```bash
curl -sS http://localhost:4001/health
curl -sS http://localhost:4001/v1/models
HERMES_ACCEPT_HOOKS=1 hermes chat -Q --provider nous -m deepseek/deepseek-v4-flash --toolsets terminal,file --max-turns 8 --source operator-smoke --query "Reply exactly HERMES_EXTERNAL_OK."
HERMES_ACCEPT_HOOKS=1 hermes chat -Q --provider dashboard-proxy -m qwen/qwen3.6-27b --toolsets terminal,file --max-turns 8 --source operator-smoke --query "Reply exactly HERMES_LOCAL_OK."
python3 scripts/smoke_local_model_agent.py http://localhost:25480 deepseek/deepseek-v4-flash
```

For queue work, inspect `/api/agents/runner-health`, `/api/agents/processes`,
agent `output.log`, `checkpoint.json`, ticket notes, and memory search evidence.
Do not judge task health from `progress_pct` alone.

## Transient Provider Capacity Handling

Hermes/N Nous and OpenRouter can return temporary upstream capacity failures
such as HTTP `429` or `503` for free/external routes. The dashboard runner now
treats HTTP `429`, `500`, `502`, `503`, `504`, rate-limit, overloaded,
temporarily unavailable, upstream-capacity, and daily-limit messages as
transient provider failures.

When this happens, the runner preserves the same agent workspace, checkpoint,
steering inbox, and ticket evidence, marks the task back to `queued`, writes an
operator note, and requeues the same task after
`AGENT_TRANSIENT_MODEL_RETRY_DELAY_SECONDS` until
`AGENT_TRANSIENT_MODEL_RETRY_MAX` is exhausted. Non-provider failures such as
permission denials still fail or gate normally.

If `AGENT_TRANSIENT_MODEL_FALLBACK_ENABLED=true`, exhausting external retries
updates the same agent's `selected_model` to
`AGENT_TRANSIENT_MODEL_FALLBACK_MODEL`, writes an explicit ticket note, emits
`agent_transient_model_fallback_scheduled`, and queues the same task on the
local/provider route. This keeps the policy clear: Hermes/DeepSeek external
first, bounded retries second, local qwen fallback only when the external route
is unavailable.

## Proxy Fallback Order

The built-in proxy is the model gateway for Hermes queue work. The preferred
external model stays `deepseek/deepseek-v4-flash`, but provider routing is now
explicit:

1. Nous Portal for the configured DeepSeek route.
2. OpenRouter as the first external fallback. The runtime vault/environment
   supplies `OPENROUTER_API_KEY`; no token is committed. The demo-safe fallback
   alias is `openrouter/free`, because `deepseek/deepseek-v4-flash:free`
   advertised tool support but returned upstream rate-limit during validation.
3. Local LM Studio/qwen through the local proxy route.

Validation on 2026-05-19:

- Direct OpenRouter `openrouter/free` chat/completions with a simple tool
  schema returned one tool call.
- Proxy `/v1/models` advertised Nous, OpenRouter, and LM Studio aliases.
- Proxy chat for `deepseek/deepseek-v4-flash` fell through from unavailable
  Nous auth/capacity to OpenRouter and returned a successful completion without
  exposing provider secrets in logs.
- Proxy chat for `openrouter/free` returned a successful tool-call response.

## Dashboard API Auth For Agents

In enforced dashboard auth mode, spawned agents do not receive the global
service token or trusted proxy secret. Instead the runner mints a short-lived,
signed `dashboard_session` cookie with the agent's spawn-time subject:

- roles and capabilities are copied from the spawning user or service account
  and trimmed by the requested permission envelope
- a ticket-specific scope is added for the assigned ticket
- the cookie is written to `dashboard_auth.json` in the isolated work directory
- the per-agent and container-level curl guards attach the cookie only for
  dashboard API requests from that workspace
- secret values are not printed in prompts, logs, docs, or ticket notes

The container-level curl guard exists because Hermes terminal tool shells may
prefer system `curl` over the per-workspace PATH wrapper. The global guard is
inert unless it can find `dashboard_auth.json` in the current directory tree
and the target URL is the dashboard API.

## Live Validation

2026-05-19 lab validation:

- Hermes setup smoke passed on ticket `613`, agent `248`, task `245`.
- Access-wall approval/resume passed on ticket `614`, original agent `249`,
  resumed agent `250`, change `176`.
- Note steering passed on ticket `617`, iTop `UserRequest::398`, agent `252`,
  task `249`, with two steering events and no active processes afterward.
- Wazuh lease-gated access passed on ticket `618`, original agent `253`,
  resumed agent `254`, change `177`.
- One-line installer alternate-port proof created setup ticket `1`, setup
  agent `1`, and completed the bounded
  `SETUP_ONBOARDING_BOOTSTRAP_COMPLETE` onboarding check at 100%.
- Live route reconciliation aligned `AGENT_LLM_BASE_URL` to the
  Compose-managed proxy at `http://ai-proxy:4001` inside Docker while keeping
  the deployment-host local proxy on `http://localhost:4401`; Hermes setup
  smoke passed afterward on ticket `620`, agent `255`, task `252`, and no
  active processes remained.
- URL-safe complex phishing plus EDR proof passed on ticket `690`, iTop
  `Incident::470`, initial agent `265`, continuation agents `266`/`267`,
  Wazuh access request `31`, gates `181` and `182`, postmortem `106`, URL
  sandbox attachment `92`, workflow `4` updated, ticket resolved, and no
  active processes remained. The run started on Hermes with
  `deepseek/deepseek-v4-flash`; transient provider retries were visible in
  ticket notes and audit, and DeepSeek recovered before local fallback was
  required.
- Fresh URL-safe phishing/EDR hybrid proof on ticket `695`, iTop
  `Incident::475`, agents `273`/`274`, gates `185`/`186`, postmortem `107`,
  requester/steering evidence, URL sandbox evidence, and no direct suspicious
  URL fetch. This run exposed and fixed a provider-status drift edge: terminal
  dashboard evidence existed, but iTop remained open when the harness missed
  the final close call. The supervisor now resolves from terminal evidence,
  sends a compact iTop close note, and keeps the full evidence in dashboard
  notes. Forced provider sync kept ticket `695` resolved.
- Approval audit now names the approver explicitly: changes `181` and `182`
  show `demo_account_1 approved change 181/182` in `/api/dashboard/audit`,
  with `approved_by` and `approval_actor` in audit and event details.

2026-05-18 lab validation:

- Enforced auth smoke passed against `http://192.168.50.222:25480`.
- Authenticated browser UI pass loaded `Agentic Operations`, rendered 14 Demo
  Proof rows, showed `demo_account_1 / header / platform-admin`, minted an
  HttpOnly `dashboard_session`, and produced no console or network failures.
- Hermes setup-agent smoke passed on ticket `606`, agent `243`, task `240`:
  the agent called protected dashboard APIs through the scoped session and
  wrote the expected setup note.
- Permission/provider matrix passed with marker
  `PERMISSION_PROVIDER_MATRIX_1779148832`: Dev Y could not see Dev Z data,
  auditor mutation was denied, denied GitLab/iTop leases returned
  `missing_agent_vault_lease`, the access request synced to iTop tickets
  `391`/`392`, approval/completion granted lease `297`, and no active agents
  remained.

2026-05-15 lab validation:

- Direct container Hermes through Nous/DeepSeek returned
  `HERMES_FINAL_NOUS_OK`.
- Direct container Hermes through `dashboard-proxy` to local Qwen returned
  `HERMES_FINAL_LOCAL_OK`.
- Dashboard queue smoke completed on ticket `568`, agent `222`, task `219`,
  persisted a `done` checkpoint at `100%`, and left no active OS process.
- Proxy compatibility endpoints `/health`, `/v1/models`, `/api/v1/models`,
  `/api/tags`, `/v1/props`, `/props`, `/version`, and
  `/v1/models/qwen/qwen3.6-27b` returned HTTP `200`.

Note: Hermes Agent v0.13.0 does not support top-level `--source` or
`--max-turns` with one-shot `-z`; those flags are supported under
`hermes chat -Q --query`, which is the dashboard runner command path.
