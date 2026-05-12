---
name: searxng-deployment
description: >
  Deploy and manage SearXNG as a local/private web research provider for agent
  harnesses and the web_research skill. Use when an environment needs local
  search, cannot rely on built-in browsing, or needs reproducible research
  tooling behind audit controls.
allowed-tools:
  - Read
  - Bash(python *)
  - Bash(docker *)
  - Bash(curl *)
---

# SearXNG Deployment

SearXNG is an optional but recommended reference module for private research.
Deploy it when the agent harness does not provide reliable web search or when
the customer requires local, auditable search routing.

## Guardrails

- Do not store engine API keys in source.
- Keep the service private to the environment unless explicitly approved.
- Log search metadata needed for audit, but do not log secrets or private query attachments.
- Treat customer KB/wiki scraping as ticket/context data subject to access policy.

## Current Lab Instance

- URL: `http://192.168.50.222:7999`
- Used by: `web_research` skill

## Deployment Pattern

1. Create a SearXNG deployment directory.
2. Generate `settings.yml` from environment-specific choices.
3. Start the container with a non-conflicting host port.
4. Test `/search?q=test&format=json`.
5. Point `web_research.py --server` or `DEFAULT_SEARXNG_URL` at the instance.
6. Add the module to the setup wizard as deployed or existing.

## Health Checks

```bash
curl -sS "http://SEARXNG_HOST:7999/search?q=test&format=json"
```

Expected result: JSON with a `results` array or a clear engine-level error.

## Agent Workflow Use

Agents should use SearXNG for discovery, then fetch source pages and summarize
into ticket notes or knowledge articles. Any use of retrieved content in
customer action plans must include source URL, timestamp, and confidence.
