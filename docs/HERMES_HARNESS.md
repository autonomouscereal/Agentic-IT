# Hermes Harness Integration

Last updated: 2026-05-15.

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
HERMES_TOOLSETS=hermes-cli
HERMES_RUN_AS_UID=1000
HERMES_RUN_AS_GID=1000
HERMES_RUN_HOME=/home/cereal
HERMES_RUN_USER=cereal
HOME=/home/cereal
USER=cereal
LOGNAME=cereal
XDG_CACHE_HOME=/home/cereal/.cache
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
HERMES_ACCEPT_HOOKS=1 hermes --provider nous -m deepseek/deepseek-v4-flash --toolsets hermes-cli -z "Reply exactly HERMES_EXTERNAL_OK."
HERMES_ACCEPT_HOOKS=1 hermes --provider dashboard-proxy -m qwen/qwen3.6-27b --toolsets hermes-cli -z "Reply exactly HERMES_LOCAL_OK."
python3 scripts/smoke_local_model_agent.py http://localhost:25480 deepseek/deepseek-v4-flash
```

For queue work, inspect `/api/agents/runner-health`, `/api/agents/processes`,
agent `output.log`, `checkpoint.json`, ticket notes, and memory search evidence.
Do not judge task health from `progress_pct` alone.

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

Note: Hermes Agent v0.13.0 does not support a `--source` CLI flag. Keep source
identity in `HERMES_AGENT_SOURCE` and memory hook metadata, not in the command
argument list.

Hermes Agent v0.13.0 also does not expose a `--max-turns` CLI flag. Queue
limits should be enforced by the dashboard runner timeout, stall detector,
approval gates, and task supervision rather than Hermes argv.
