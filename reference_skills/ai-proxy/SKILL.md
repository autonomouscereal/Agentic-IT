---
name: ai-proxy
description: >
  Deploy and manage the local/cloud AI model proxy used by the agentic platform.
  Use when configuring LiteLLM-compatible/OpenAI-compatible routing for local
  LM Studio models, external providers, Claude Code-compatible Anthropic
  Messages routes, Hermes-compatible OpenAI chat routes, model aliases, health
  checks, and dashboard agent model routing.
allowed-tools:
  - Read
  - Bash(python *)
  - Bash(docker *)
  - Bash(curl *)
---

# AI Proxy

The AI proxy is an optional provider module. Deploy it when the environment needs
one stable endpoint for local models, external models, or mixed routing. If the
customer already has a router, configure the dashboard to use that endpoint
instead of deploying this reference module.

## Guardrails

- Do not hardcode provider keys, master keys, OAuth tokens, or customer URLs with embedded secrets.
- Store secrets in the server-manager vault or runtime environment.
- Prefer routable LAN or localhost URLs over Docker-only hostnames.
- Keep model IDs configurable per agent. Do not assume one global model is always safe to use.
- Do not use model-invocation heartbeats for agent liveness; monitor process/task state and logs.

## Reference Shape

Proxy deployment contract:

- Base URL: set `AGENT_LLM_BASE_URL` to the environment's routed proxy URL.
- Default Hermes/Nous model: `deepseek/deepseek-v4-flash`
- First external fallback: OpenRouter `openrouter/free`, supplied by
  runtime/vault `OPENROUTER_API_KEY`.
- Fast local model: `qwen/qwen3.6-27b`
- Slower local model aliases may exist for older GPUs.
- Default fallback order for Hermes queue work: Nous Portal -> OpenRouter ->
  local LM Studio/qwen.

## Deployment Pattern

1. Create a deployment directory on the target host.
2. Generate a master key and place it in the vault or environment.
3. Create a proxy configuration with model aliases and provider routes.
4. Start the proxy as a managed service or container.
5. Test `/v1/models` and at least one chat/completions request per route.
6. Set dashboard `AGENT_LLM_BASE_URL` and agent model aliases.
7. Document model capacities, concurrency limits, and routing policy.

The deployable reference proxy source is tracked at
`deploy/ai-proxy/ai_proxy.py`. It supports:

- Claude Code: `POST /v1/messages`
- Hermes: `POST /v1/chat/completions`
- Discovery: `GET /v1/models`

## Health Checks

```bash
curl -sS http://PROXY_HOST:4001/v1/models
curl -sS http://PROXY_HOST:4001/health
```

## Dashboard Integration

Set:

```ini
AGENT_LLM_BASE_URL=http://PROXY_HOST:4001
AGENT_LLM_AUTH_TOKEN=<from vault or environment when required>
AGENT_DEFAULT_MODEL=deepseek/deepseek-v4-flash
OPENROUTER_API_KEY=<from vault/runtime, never source>
AGENT_HARNESS=hermes
HERMES_DEFAULT_PROVIDER=nous
HERMES_LOCAL_PROVIDER=dashboard-proxy
```

The dashboard can override the model per agent/task. Use this to keep the
operator's current model separate from spawned worker agents.

## Test Expectations

- Model discovery returns configured aliases including local, Nous, and
  OpenRouter models.
- A short local model request completes through the proxy using OpenAI chat.
- A short Nous Portal request completes through the proxy using OpenAI chat.
- A short OpenRouter request completes through the proxy using OpenAI chat.
- A simple tool schema sent to `openrouter/free` returns a tool-call response
  when the upstream free route has capacity.
- A short Claude Code request completes through the proxy using Anthropic Messages when Claude Code remains enabled.
- A missing or invalid auth token fails clearly.
- Agent spawn logs show the selected model and proxy URL without leaking secrets.
- Long-running local model tasks do not trip arbitrary model-level heartbeat timeouts.
