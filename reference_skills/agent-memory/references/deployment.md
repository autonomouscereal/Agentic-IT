# Agent Memory Deployment

## Service

Use PostgreSQL 16 with pgvector:

```yaml
agent-memory-db:
  image: pgvector/pgvector:pg16
  restart: unless-stopped
  environment:
    POSTGRES_DB: agent_memory
    POSTGRES_USER: agent_memory
    POSTGRES_PASSWORD: ${AGENT_MEMORY_DB_PASSWORD:?AGENT_MEMORY_DB_PASSWORD must be set}
  ports:
    - "${AGENT_MEMORY_DB_PORT:-25490}:5432"
  volumes:
    - agent-memory-db-data:/var/lib/postgresql/data
  healthcheck:
    test: ["CMD-SHELL", "pg_isready -U agent_memory -d agent_memory"]
    interval: 5s
    timeout: 3s
    retries: 10
```

Generate the password at install time and store it in the deployment `.env` or credential vault. Do not commit it.

## Skill Runtime

Install the skill with its own Python virtual environment unless it is baked
into an application container that already installs `asyncpg`.

Windows/operator workstation:

```powershell
$env:AGENT_MEMORY_SKILL_DIR = "C:/Users/cereal/.agents/skills/agent-memory"
python -m venv "$env:AGENT_MEMORY_SKILL_DIR/.venv"
& "$env:AGENT_MEMORY_SKILL_DIR/.venv/Scripts/python.exe" -m pip install -r "$env:AGENT_MEMORY_SKILL_DIR/requirements.txt"
```

Linux/container:

```bash
export AGENT_MEMORY_SKILL_DIR=/root/.agents/skills/agent-memory
python3 -m venv "${AGENT_MEMORY_SKILL_DIR}/.venv"
"${AGENT_MEMORY_SKILL_DIR}/.venv/bin/python" -m pip install -r "${AGENT_MEMORY_SKILL_DIR}/requirements.txt"
```

`requirements.txt` includes `asyncpg` for PostgreSQL access and `cryptography`
for optional encrypted vault reads through server-manager `credman.py`. Runtime
containers that inject `MEMORY_DB_PASSWORD` still need only `asyncpg`, but using
the same requirements everywhere keeps operator and hook behavior consistent.

Hook commands should call the venv Python when the global runtime does not
guarantee these dependencies:

```json
{
  "type": "command",
  "command": "/root/.agents/skills/agent-memory/.venv/bin/python /root/.agents/skills/agent-memory/scripts/agent_memory_hook.py --event UserPromptSubmit --agent DashboardAgent --source dashboard_hook"
}
```

Hook stdout is part of the Codex/Claude hook-control contract. Do not print
memory status or inserted IDs from production hooks. The hook command should
write all prompt/tool/session payloads to PostgreSQL and JSONL audit logs, then
exit with empty stdout/stderr. Use `--emit-json` only in explicit contract tests;
it emits valid hook-control JSON and still records the full payload.

## Schema

The script creates:

- `vector` and `pg_trgm` extensions
- `agent_memory_events`
- `agent_memory_spaces`
- `agent_memory_entities`
- `agent_memory_entity_mentions`
- `agent_memory_entity_edges`
- `agent_memory_event_links`
- indexes for space/time, memory kind, agent/event type, tags, full-text search, trigram search, HNSW vector search, entity lookup, and graph edges

Schema initialization is idempotent and race-tolerant without advisory locks. Concurrent setup attempts may race on extension/index creation; duplicate-object outcomes are treated as already-done.

Use memory spaces as the default isolation boundary. For spawned agents, set
`AGENT_MEMORY_SPACE` from the ticket/project/workflow identity. Leave it unset
only for broad operator-level audit work. Use `--all-spaces` for deliberate
cross-project retrieval.

## Agent Hooks

Spawned agent workspaces should receive:

- memory DB env vars
- the memory skill venv path, or a container runtime where `asyncpg` is already installed
- `AGENT_MEMORY_AGENT` set to a stable agent label
- `AGENT_MEMORY_SPACE` set to the current ticket/project/workflow space
- `AGENT_MEMORY_SESSION_ID` when available
- hooks for `UserPromptSubmit`, `PostToolUse`, and `Stop`

The hook must use stdin JSON where possible. It exits zero on memory failures and writes structured local error logs.

## Tests

Run:

```bash
"${AGENT_MEMORY_SKILL_DIR}/.venv/bin/python" scripts/agent_memory.py --json init
"${AGENT_MEMORY_SKILL_DIR}/.venv/bin/python" scripts/agent_memory.py --json self-test
printf '{"session_id":"demo","cwd":"/work/demo-space","prompt":"memory sentinel"}' | "${AGENT_MEMORY_SKILL_DIR}/.venv/bin/python" scripts/agent_memory_hook.py --event UserPromptSubmit --agent Demo --source manual --space demo-space
"${AGENT_MEMORY_SKILL_DIR}/.venv/bin/python" scripts/agent_memory.py search "memory sentinel" --agent Demo --space demo-space
"${AGENT_MEMORY_SKILL_DIR}/.venv/bin/python" scripts/agent_memory.py spaces
"${AGENT_MEMORY_SKILL_DIR}/.venv/bin/python" scripts/agent_memory.py graph "memory sentinel" --space demo-space
```

For concurrency, spawn 10+ hook processes with unique sentinels and confirm all are searchable.
Also test a `PostToolUse` payload with full `tool_input`, full `tool_response`,
and an escaped surrogate such as `\udc9d`; default hook stdout/stderr must be
empty while search/audit still returns the complete payload.
