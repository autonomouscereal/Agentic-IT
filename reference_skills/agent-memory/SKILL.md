---
name: agent-memory
description: Deploy, test, search, and integrate the shared PostgreSQL/pgvector async memory backend for Codex, Claude Code, SOC dashboard agents, and other local agent harnesses. Use when configuring persistent agent memory, debugging memory hooks, auditing prompts/tool calls, wiring memory into agent workspaces, or adding the memory service to the agentic IT/SOC platform installer.
---

# Agent Memory

Shared long-term agent memory backed by raw PostgreSQL with pgvector. The bundled scripts use `asyncpg`, deterministic CPU embeddings, JSONB metadata, full-text search, trigram search, and hook ingestion for prompts, tool calls, and session lifecycle events.

## Quick Commands

Set `AGENT_MEMORY_SKILL_DIR` to this skill folder when running manually:

```bash
python "${AGENT_MEMORY_SKILL_DIR}/scripts/agent_memory.py" --json status
python "${AGENT_MEMORY_SKILL_DIR}/scripts/agent_memory.py" --json self-test
python "${AGENT_MEMORY_SKILL_DIR}/scripts/agent_memory.py" search "what happened with memory hooks" --limit 10
```

Store a deliberate note:

```bash
python "${AGENT_MEMORY_SKILL_DIR}/scripts/agent_memory.py" add \
  --agent Codex \
  --event-type note \
  --role assistant \
  --source manual \
  --tags memory,decision \
  --content "High-value fact to retrieve later."
```

Run a hook ingestion test:

```bash
printf '{"session_id":"hook-test","prompt":"memory hook sentinel"}' | \
python "${AGENT_MEMORY_SKILL_DIR}/scripts/agent_memory_hook.py" \
  --event UserPromptSubmit --agent HookTest --source manual
```

## Configuration

The scripts read these environment variables:

| Variable | Purpose |
|---|---|
| `MEMORY_DB_HOST` | PostgreSQL host. Defaults to `192.168.50.222`. |
| `MEMORY_DB_PORT` | PostgreSQL port. Defaults to `25490`. |
| `MEMORY_DB_NAME` | Database name. Defaults to `agent_memory`. |
| `MEMORY_DB_USER` | Database user. Defaults to `agent_memory`. |
| `MEMORY_DB_PASSWORD` | Direct password, preferred in containers. |
| `MEMORY_DB_VAULT_KEY` | server-manager vault key. Defaults to `agent_memory_pg`. |
| `SERVER_MANAGER_SKILL_DIR` | server-manager skill path for vault reads. |

Never hardcode passwords in source, skills, docs, or hook config. Use `MEMORY_DB_PASSWORD` from a generated environment file inside deployments, or use the server-manager vault on local workstations.

## Hook Integration

For Claude Code or compatible harnesses, add hooks that call `agent_memory_hook.py`:

```json
{
  "hooks": {
    "UserPromptSubmit": [
      {
        "matcher": ".*",
        "hooks": [
          {
            "type": "command",
            "command": "python /root/.claude/skills/agent-memory/scripts/agent_memory_hook.py --event UserPromptSubmit --agent DashboardAgent --source dashboard_hook"
          }
        ]
      }
    ],
    "PostToolUse": [
      {
        "matcher": ".*",
        "hooks": [
          {
            "type": "command",
            "command": "python /root/.claude/skills/agent-memory/scripts/agent_memory_hook.py --event PostToolUse --agent DashboardAgent --source dashboard_hook"
          }
        ]
      }
    ],
    "Stop": [
      {
        "matcher": ".*",
        "hooks": [
          {
            "type": "command",
            "command": "python /root/.claude/skills/agent-memory/scripts/agent_memory_hook.py --event Stop --agent DashboardAgent --source dashboard_hook"
          }
        ]
      }
    ]
  }
}
```

The hook reads JSON from stdin first and argv fallback second. It logs successes to `logs/agent_memory_hook_events.jsonl`, logs failures to `logs/agent_memory_hook_errors.jsonl`, redacts obvious secret fields, and exits zero on failure so memory cannot break the agent harness.

## SOC Dashboard Pattern

For the agentic IT/SOC dashboard:

1. Deploy `agent-memory-db` as a `pgvector/pgvector:pg16` Compose service.
2. Generate `AGENT_MEMORY_DB_PASSWORD` in `.env`.
3. Pass `MEMORY_DB_HOST=agent-memory-db`, `MEMORY_DB_PORT=5432`, `MEMORY_DB_NAME=agent_memory`, `MEMORY_DB_USER=agent_memory`, and `MEMORY_DB_PASSWORD=${AGENT_MEMORY_DB_PASSWORD}` into the API container and spawned agent settings.
4. Mount `reference_skills/agent-memory` into `/root/.claude/skills/agent-memory`.
5. Write spawned-agent hooks into each workspace `.claude/settings.json`.
6. Seed a global dashboard skill that tells agents to search memory before substantial work and store durable notes after meaningful completion.

## Validation

Minimum validation after any change:

```bash
python "${AGENT_MEMORY_SKILL_DIR}/scripts/agent_memory.py" --json init
python "${AGENT_MEMORY_SKILL_DIR}/scripts/agent_memory.py" --json self-test
python "${AGENT_MEMORY_SKILL_DIR}/scripts/agent_memory.py" --json status
python -m py_compile "${AGENT_MEMORY_SKILL_DIR}/scripts/agent_memory.py" "${AGENT_MEMORY_SKILL_DIR}/scripts/agent_memory_hook.py"
```

For hook reliability, run at least one stdin hook test and one concurrent ingestion test. Then confirm:

- search retrieves the sentinel
- `logs/agent_memory_hook_errors.jsonl` has no new entries
- JSONB metadata decodes as structured JSON
- secret-like fields are redacted in hook metadata/logs

## References

Read `references/deployment.md` when deploying this memory service from scratch or wiring it into the SOC dashboard installer.
