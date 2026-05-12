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

## Schema

The script creates:

- `vector` and `pg_trgm` extensions
- `agent_memory_events`
- indexes for created time, agent/event type, tags, full-text search, trigram search, and HNSW vector search

Schema initialization is idempotent and race-tolerant without advisory locks. Concurrent setup attempts may race on extension/index creation; duplicate-object outcomes are treated as already-done.

## Agent Hooks

Spawned agent workspaces should receive:

- memory DB env vars
- `AGENT_MEMORY_AGENT` set to a stable agent label
- `AGENT_MEMORY_SESSION_ID` when available
- hooks for `UserPromptSubmit`, `PostToolUse`, and `Stop`

The hook must use stdin JSON where possible. It exits zero on memory failures and writes structured local error logs.

## Tests

Run:

```bash
python scripts/agent_memory.py --json init
python scripts/agent_memory.py --json self-test
printf '{"session_id":"demo","prompt":"memory sentinel"}' | python scripts/agent_memory_hook.py --event UserPromptSubmit --agent Demo --source manual
python scripts/agent_memory.py search "memory sentinel" --agent Demo
```

For concurrency, spawn 10+ hook processes with unique sentinels and confirm all are searchable.
