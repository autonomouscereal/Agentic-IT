# SOC Dashboard — Architecture & Deployment Blueprint

## System Architecture

```
┌───────────────────────────────────────────────────────────────┐
│                    AI Server (192.168.50.222)                  │
│                                                               │
│  ┌─────────────────────────────────────────────────────┐      │
│  │  soc-dashboard-api (FastAPI :8000 → host :25480)    │      │
│  │                                                     │      │
│  │  Routes:                                            │      │
│  │  /api/tickets    — CRUD + iTop sync + agent assign  │      │
│  │  /api/agents     — lifecycle + wake/restart/stop    │      │
│  │  /api/changes    — request/approve/reject/complete  │      │
│  │  /api/dashboard  — stats + audit + charts           │      │
│  │  /api/tools      — health checks + status           │      │
│  │  /ws             — WebSocket real-time events       │      │
│  │  /               — serve frontend static files      │      │
│  │  /health         — health check endpoint            │      │
│  │                                                     │      │
│  │  Services:                                          │      │
│  │  itop_sync.py      — bidirectional iTop sync loop   │      │
│  │  agent_monitor.py  — agent heartbeat monitoring     │      │
│  │  health_check.py   — tool health checking           │      │
│  │  ticket_provider.py — abstract provider interface   │      │
│  │                                                     │      │
│  │  Frontend (mounted read-only):                       │      │
│  │  index.html, dashboard.css,                         │      │
│  │  dashboard.js, charts.js, agents.js, websocket.js   │      │
│  └──────────────┬──────────────────────────────────────┘      │
│                 │                                             │
│                 │ asyncpg (raw SQL, no ORM)                    │
│                 ▼                                             │
│  ┌─────────────────────────────────────────────────────┐      │
│  │  soc-dashboard-db (PostgreSQL 16 :5432 → host :5433)│      │
│  │                                                     │      │
│  │  Tables: tools, tool_checks, tickets, agents,       │      │
│  │          change_requests, audit_log, dashboard_settings │      │
│  └─────────────────────────────────────────────────────┘      │
│                                                               │
│  External services (monitored + integrated):                   │
│  ┌──────────┐  ┌──────────┐  ┌────────┐  ┌────────┐         │
│  │ iTop     │  │ Wazuh    │  │ GitLab │  │Keycloak│         │
│  │ :25432   │  │ :26443   │  │ :80    │  │ :8443  │         │
│  └──────────┘  └──────────┘  └────────┘  └────────┘         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐                   │
│  │ Mailcow  │  │ Zeek     │  │ Suricata │                   │
│  │ :25      │  │ IDS      │  │ IDS/IPS  │                   │
│  └──────────┘  └──────────┘  └──────────┘                   │
└───────────────────────────────────────────────────────────────┘
```

## Data Flow

### Ticket Sync (iTop → Dashboard)

1. `itop_sync.py` runs a continuous loop with two modes:
   - **Fast discovery** (every 2s): Scans each iTop class for new keys beyond the last-known maximum. Stops after 3 consecutive misses per class. Results cached in `.itop_max_keys.json`.
   - **Full sync** (every 60s): Re-syncs all known tickets across all 5 classes (Incident, RoutineChange, NormalChange, EmergencyChange, UserRequest).

2. Tickets are mirrored into local PostgreSQL with full metadata (title, description, status, priority, impact, urgency, assignee, team).

3. Changes can flow back to iTop via `POST /api/tickets/{id}/sync` or the full sync endpoint.

4. Sync events broadcast over WebSocket to update the dashboard in real-time.

### Agent Orchestration

1. User assigns an agent to a ticket via `POST /api/tickets/{id}/assign-agent`
2. Agent is created with status 'spawned', model selection, and heartbeat timestamp
3. `agent_monitor.py` runs every 15 seconds, checking all active agents
4. Agents exceeding 120s without heartbeat are marked 'stalled' with error message
5. Stalled agents can be woken, restarted, or stopped via the API
6. All agent state changes log to `audit_log` table
7. Agent events broadcast over WebSocket

### Change Approval Workflow

1. Agent or system submits a change request via `POST /api/changes/request`
2. Change enters 'pending' state with a 300-second expiry
3. Dashboard shows pending changes on Overview page and Changes page
4. Admin approves (`POST /api/changes/{id}/approve`) or rejects (`POST /api/changes/{id}/reject`)
5. Approved changes can be marked completed with a result
6. All actions log to `audit_log`

### Tool Health Monitoring

1. 14 tools pre-registered in the `tools` table on first boot
2. `health_check.py` runs every 60 seconds
3. Each tool is checked via either:
   - **Port scan** (async TCP connection) for non-HTTP services
   - **HTTP request** (aiohttp) for web-based services (siem-ui, soc-platform, iam, vcs, search types)
4. Results recorded in `tool_checks` table with response time and error
5. Tool uptime percentages calculated from check history

## Technology Stack

### Backend
- **FastAPI 0.115.0** — Async web framework with lifespan lifecycle
- **uvicorn + uvloop** — ASGI server with libuv event loop
- **PostgreSQL 16** — Raw SQL only via asyncpg driver (NO ORM, NO Pydantic, NO SQLAlchemy)
- **Python 3.11-slim** — Container base image
- **aiohttp 3.10.0** — Async HTTP client for iTop API and health checks

### Frontend
- **Vanilla JavaScript** — No framework, no build step
- **CSS custom properties** — Dark operations theme with CSS variables
- **Chart.js 4.4.7** — Three charts (line, doughnut, horizontal bar)
- **WebSocket** — Real-time event streaming with auto-reconnect
- **No package manager** — All JS served as static files from mounted volume

### Database Rules (CRITICAL)
- **NO ORM, NO Pydantic, NO SQLAlchemy** — raw SQL only
- Manual connection pooling with asyncpg (min 2, max 10 connections)
- Proper parameterized queries with `$1`, `$2` placeholders to prevent SQL injection
- JSONB columns for flexible metadata storage

## Deployment Configuration

### Docker Compose (v3.9)

```yaml
services:
  db:
    image: postgres:16-alpine
    container_name: soc-dashboard-db
    restart: unless-stopped
    environment:
      POSTGRES_DB: soc_dashboard
      POSTGRES_USER: ${SOC_DB_USER:-soc_user}
      POSTGRES_PASSWORD: ${SOC_DB_PASSWORD}
    ports:
      - "5433:5432"
    volumes:
      - db-data:/var/lib/postgresql/data
      - ./api/init_db.sql:/docker-entrypoint-initdb.d/init_db.sql:ro
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${SOC_DB_USER:-soc_user} -d soc_dashboard"]
      interval: 5s
      timeout: 3s
      retries: 10

  api:
    build: ./api
    container_name: soc-dashboard-api
    restart: unless-stopped
    ports:
      - "25480:8000"
    environment:
      DB_HOST: db
      DB_PORT: 5432
      # ... see Configuration section
    depends_on:
      db:
        condition: service_healthy
    volumes:
      - ./data/agent_logs:/app/data/agent_logs
      - ./data/active_agents.json:/app/data/active_agents.json:rw
      - ./frontend:/frontend:ro

volumes:
  db-data:
```

### Dockerfile (API)

```dockerfile
FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir fastapi uvicorn[standard] asyncpg jinja2 python-multipart
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN mkdir -p /app/frontend
EXPOSE 8000
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8000", "--loop", "uvloop"]
```

### Network

- Docker network: `soc-dashboard_default` (bridge, auto-created by compose)
- API binds to `0.0.0.0:8000` inside container
- Host port mapping: `25480 → 8000`
- DB port mapping: `5433 → 5432`
- Frontend served as static files from mounted volume (read-only)

### Startup Sequence

1. PostgreSQL container starts, runs `init_db.sql` on first boot
2. Health check waits for `pg_isready` to succeed
3. API container starts after DB is healthy
4. FastAPI lifespan runs:
   - Verifies DB connection
   - Wires up WebSocket broadcast function
   - Starts 3 background tasks (iTop sync, health check, agent monitor)
5. Frontend becomes available at `http://192.168.50.222:25480`

## Service Layer Details

### itop_sync.py

Implements `iTopProvider(TicketProvider)` class with:
- Async aiohttp session for iTop REST API v1.4
- Key-based discovery with `.itop_max_keys.json` state file
- 5 ticket classes: Incident, RoutineChange, NormalChange, EmergencyChange, UserRequest
- Bidirectional sync (read from iTop, push status changes back)
- WebSocket broadcast on each sync event
- Configurable discovery and full sync intervals

### agent_monitor.py

Background monitoring with:
- Configurable heartbeat interval (default 15s)
- Configurable stalled threshold (default 120s)
- Marks stalled agents with error message
- Writes audit log entries for state changes
- Broadcast function for WebSocket integration
- Spawn, wake, restart, stop operations

### health_check.py

Tool health monitoring with:
- Async port scanning via `asyncio.open_connection`
- Async HTTP checks via aiohttp for web services
- Response time tracking (milliseconds)
- Results stored in `tool_checks` table
- Individual and bulk check endpoints

### ticket_provider.py

Abstract `TicketProvider` interface defining:
- `connect()`, `is_connected()`, `discover_new()`
- `sync_ticket()`, `full_sync()`, `get_ticket()`
- `update_ticket()`, `close_ticket()`, `sync_loop()`

Allows swapping iTop for any other ticketing system (ServiceNow, Jira, etc.) by implementing this interface.

## Integration Points

### iTop (192.168.50.222:25432)
- iTop v3.2.1 with MariaDB backend
- REST API v1.4 at `/webservices/rest.php`
- Authentication via BasicAuth + API credentials in request payload
- Sync runs continuously via background task

### Keycloak (internal)
- Keycloak 26.6.0 as central IDP
- Realms: itop, wazuh, mailcow, gitlab, master
- Monitored via health checks (port 8443)

### Wazuh (192.168.50.222:26443)
- Wazuh 4.14.4 SIEM platform
- Monitored via health checks (dashboard port 26443, API port 26500, indexer port 26920)

### GitLab (192.168.50.222:80)
- GitLab 17.x with Keycloak OIDC SSO
- Monitored via health checks

### Other Monitored Services
- Zeek IDS, Suricata IDS, Mailcow, SOC Bridge, SIEM-Ticket Bridge, SearXNG, and TheHive

## Environment Configuration

All sensitive values are supplied by `.env`, environment management, or the server-manager vault. Compose files must not contain usable default passwords. iTop credentials are passed to the API container for sync operations at runtime only.
