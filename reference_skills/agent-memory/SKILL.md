---
name: agent-memory
description: Deploy, test, search, and integrate the shared PostgreSQL/pgvector async memory backend for Codex, Claude Code, SOC dashboard agents, and other local agent harnesses. Use when configuring persistent agent memory, debugging memory hooks, auditing prompts/tool calls, wiring memory into agent workspaces, or adding the memory service to the agentic IT/SOC platform installer.
---

# Agent Memory

Shared long-term agent memory backed by raw PostgreSQL with pgvector. The bundled scripts use `asyncpg`, deterministic CPU embeddings, JSONB metadata, full-text search, trigram search, scoped memory spaces, a lightweight entity graph, and hook ingestion for prompts, tool calls, and session lifecycle events.

## Quick Commands

Set `AGENT_MEMORY_SKILL_DIR` to this skill folder when running manually:

```bash
"${AGENT_MEMORY_SKILL_DIR}/.venv/Scripts/python.exe" "${AGENT_MEMORY_SKILL_DIR}/scripts/agent_memory.py" --json status
"${AGENT_MEMORY_SKILL_DIR}/.venv/Scripts/python.exe" "${AGENT_MEMORY_SKILL_DIR}/scripts/agent_memory.py" --json self-test
"${AGENT_MEMORY_SKILL_DIR}/.venv/Scripts/python.exe" "${AGENT_MEMORY_SKILL_DIR}/scripts/agent_memory.py" search "what happened with memory hooks" --space agent-memory/backend --limit 10
"${AGENT_MEMORY_SKILL_DIR}/.venv/Scripts/python.exe" "${AGENT_MEMORY_SKILL_DIR}/scripts/agent_memory.py" search "what happened with memory hooks" --all-spaces --limit 10
"${AGENT_MEMORY_SKILL_DIR}/.venv/Scripts/python.exe" "${AGENT_MEMORY_SKILL_DIR}/scripts/agent_memory.py" spaces
```

Create the venv first when installing or using the skill outside a container:

```bash
python -m venv "${AGENT_MEMORY_SKILL_DIR}/.venv"
"${AGENT_MEMORY_SKILL_DIR}/.venv/Scripts/python.exe" -m pip install -r "${AGENT_MEMORY_SKILL_DIR}/requirements.txt"
```

On Linux containers or servers, use `.venv/bin/python` instead of `.venv/Scripts/python.exe`.
`requirements.txt` includes `asyncpg` for PostgreSQL and `cryptography` for optional server-manager vault reads.

Store a deliberate note:

```bash
"${AGENT_MEMORY_SKILL_DIR}/.venv/Scripts/python.exe" "${AGENT_MEMORY_SKILL_DIR}/scripts/agent_memory.py" add \
  --agent Codex \
  --event-type note \
  --space agent-memory/backend \
  --memory-kind decision \
  --role assistant \
  --source manual \
  --tags memory,decision \
  --content "High-value fact to retrieve later."
```

Link concepts when a memory should intentionally bridge ideas:

```bash
"${AGENT_MEMORY_SKILL_DIR}/.venv/Scripts/python.exe" "${AGENT_MEMORY_SKILL_DIR}/scripts/agent_memory.py" relate \
  --space agent-memory/backend \
  --source "Memory Spaces" \
  --relation "mitigates" \
  --target "Context Blending" \
  --description "Scoped search keeps unrelated projects separate while --all-spaces enables broad retrieval."

"${AGENT_MEMORY_SKILL_DIR}/.venv/Scripts/python.exe" "${AGENT_MEMORY_SKILL_DIR}/scripts/agent_memory.py" graph "Memory Spaces" --space agent-memory/backend
```

Run a hook ingestion test:

```bash
printf '{"session_id":"hook-test","prompt":"memory hook sentinel"}' | \
"${AGENT_MEMORY_SKILL_DIR}/.venv/Scripts/python.exe" "${AGENT_MEMORY_SKILL_DIR}/scripts/agent_memory_hook.py" \
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
| `AGENT_MEMORY_SPACE` | Default memory space for add/search/audit/hook events. |
| `AGENT_MEMORY_AGENT` | Agent name used by manual CLI and hooks when not passed explicitly. |

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

The hook reads JSON from stdin first and argv fallback second. It logs successes to `logs/agent_memory_hook_events.jsonl`, logs failures to `logs/agent_memory_hook_errors.jsonl`, redacts obvious secret fields, and exits zero on failure so memory cannot break the agent harness. Hooks write into `AGENT_MEMORY_SPACE` when set; otherwise they infer a stable space from `cwd` such as `codex/2026-05-12/project-name`, `soc-dashboard`, or `agent-memory/backend`.

## Memory Space Pattern

- Use one space per project, ticket family, experiment, or major idea.
- Search the current space first. Use `--all-spaces` only when deliberately looking for reusable context elsewhere.
- Store durable decisions with `--memory-kind decision`; store run evidence with `--memory-kind test_report` or `integration_report`.
- Use `relate` to connect concepts across workstreams instead of relying on accidental semantic similarity.
- Use `entities` and `graph` to inspect whether memories are clustering around the right concepts.

## SOC Dashboard Pattern

For the agentic IT/SOC dashboard:

1. Deploy `agent-memory-db` as a `pgvector/pgvector:pg16` Compose service.
2. Generate `AGENT_MEMORY_DB_PASSWORD` in `.env`.
3. Create a venv inside the mounted skill path and install `requirements.txt` when the runtime does not already provide `asyncpg`.
4. Pass `MEMORY_DB_HOST=agent-memory-db`, `MEMORY_DB_PORT=5432`, `MEMORY_DB_NAME=agent_memory`, `MEMORY_DB_USER=agent_memory`, and `MEMORY_DB_PASSWORD=${AGENT_MEMORY_DB_PASSWORD}` into the API container and spawned agent settings.
5. Mount `reference_skills/agent-memory` into `/root/.claude/skills/agent-memory` and `/root/.agents/skills/agent-memory`.
6. Write spawned-agent hooks into each workspace `.claude/settings.json`.
7. Set `AGENT_MEMORY_SPACE` per agent workspace, preferably from ticket/project identity, so spawned agents do not merge unrelated tickets by default.
8. Seed a global dashboard skill that tells agents to search their current space before substantial work, use `--all-spaces` only for cross-project retrieval, and store durable notes after meaningful completion.

## Validation

Minimum validation after any change:

```bash
"${AGENT_MEMORY_SKILL_DIR}/.venv/Scripts/python.exe" "${AGENT_MEMORY_SKILL_DIR}/scripts/agent_memory.py" --json init
"${AGENT_MEMORY_SKILL_DIR}/.venv/Scripts/python.exe" "${AGENT_MEMORY_SKILL_DIR}/scripts/agent_memory.py" --json self-test
"${AGENT_MEMORY_SKILL_DIR}/.venv/Scripts/python.exe" "${AGENT_MEMORY_SKILL_DIR}/scripts/agent_memory.py" --json status
"${AGENT_MEMORY_SKILL_DIR}/.venv/Scripts/python.exe" "${AGENT_MEMORY_SKILL_DIR}/scripts/agent_memory.py" spaces
"${AGENT_MEMORY_SKILL_DIR}/.venv/Scripts/python.exe" "${AGENT_MEMORY_SKILL_DIR}/scripts/agent_memory.py" entities --query memory --all-spaces --limit 5
"${AGENT_MEMORY_SKILL_DIR}/.venv/Scripts/python.exe" -m py_compile "${AGENT_MEMORY_SKILL_DIR}/scripts/agent_memory.py" "${AGENT_MEMORY_SKILL_DIR}/scripts/agent_memory_hook.py"
```

For hook reliability, run at least one stdin hook test and one concurrent ingestion test. Then confirm:

- search retrieves the sentinel
- `logs/agent_memory_hook_errors.jsonl` has no new entries
- JSONB metadata decodes as structured JSON
- secret-like fields are redacted in hook metadata/logs

## References

Read `references/deployment.md` when deploying this memory service from scratch or wiring it into the SOC dashboard installer.
