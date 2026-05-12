# SOC Dashboard

FastAPI + raw PostgreSQL + vanilla JS control plane for a modular, product-agnostic agentic IT/SOC platform. The local open-source stack is a reference deployment; customer environments can integrate existing ITSM, SIEM, EDR, IAM, email, and CI/CD products through provider adapters.

## Current Deployment

- UI/API: `http://192.168.50.222:25480`
- API health: `http://192.168.50.222:25480/health`
- Server path: `/home/cereal/SOC_TESTING/soc-dashboard`
- Containers: `soc-dashboard-api`, `soc-dashboard-db`
- Database: PostgreSQL 16 only, accessed through `asyncpg` with parameterized raw SQL

## Documentation Map

- [Architecture](docs/ARCHITECTURE.md)
- [Full Platform Blueprint](docs/FULL_PLATFORM.md)
- [One-Line Installer](docs/ONE_LINE_INSTALLER.md)
- [Module Registry](docs/MODULE_REGISTRY.md)
- [Skill Sync And Git Workflow](docs/SKILL_SYNC.md)
- [Workflow Tests](docs/WORKFLOW_TESTS.md)
- [Installer E2E Results](docs/INSTALLER_E2E_RESULTS.md)
- [API Reference](docs/API.md)
- [Deployment Runbook](docs/DEPLOYMENT.md)
- [Agent Operations](docs/AGENT_OPERATIONS.md)
- [Provider Adapter Guide](docs/PROVIDER_ADAPTERS.md)
- [Security And Approvals](docs/SECURITY_APPROVALS.md)
- [Testing Runbook](docs/TESTING.md)
- [Known Issues And Fix Log](docs/KNOWN_ISSUES.md)
- [Demo Runbook](docs/DEMO_RUNBOOK.md)

## Hard Rules

- No ORM.
- No Pydantic application models.
- No SQLAlchemy.
- No plaintext passwords, API keys, tokens, or fallback secrets in source, examples, or docs.
- Keep credentials in the server-manager vault or environment.

## Agent Runner

The dashboard owns canonical tickets, notes, postmortems, workflows, approvals, and audit logs in PostgreSQL. External ticketing systems are providers behind that canonical model; iTop is the current provider, while local-only tickets are used for tests and demos. Future providers such as ServiceNow or Jira should implement the same provider interface instead of changing dashboard routes or frontend code.

## Platform Setup

The Setup page reads `platform/manifest.json` and builds a deployment plan from capabilities. Operators can mark products as already existing, exclude modules, deploy missing reference modules, or keep planned modules as blueprint work. Creating a setup ticket turns deployment into an auditable task with the same notes, approvals, agent logs, workflows, and postmortems as normal operations.

Installer entrypoints:

```bash
./install.sh --profile soc --ai-base-url http://YOUR_AI_PROXY:4001
```

```powershell
.\install.ps1 --profile soc --ai-base-url http://YOUR_AI_PROXY:4001
```

The installer starts the control plane and writes `install_state/last-plan.json`; product-specific integration continues in the dashboard Setup page.

Side-by-side installs are supported by passing unique `--target`, `--dashboard-port`, `--db-port`, and optional `--project-name` values. Docker Compose service names are project-scoped instead of hardcoded.

Production skills are synchronized into the portable `reference_skills/` bundle with:

```bash
python scripts/sync_reference_skills.py stage
python scripts/sync_reference_skills.py check
```

This is the bridge toward Git-managed skills and prevents `.agents`, `.claude`, and the dashboard bundle from silently drifting.

The dashboard currently spawns Claude Code as the first agent harness from the API container. Claude Code is not treated as the permanent architecture center; it is selected through `AGENT_HARNESS=claude-code`, with the command/env contract isolated in `api/services/agent_harness.py`.

Each task gets:

- `agent_tasks` row for queue/status/progress/output.
- `agents` row for dashboard lifecycle state.
- isolated work directory under `AGENT_WORK_BASE`, default `/app/agent_work/<agent_id>`.
- `.claude/CLAUDE.md` with ticket context, skill instructions, and checkpoint protocol.
- `.claude/settings.json` with only non-secret runtime settings.
- `checkpoint.json` that the agent updates as it works.
- `output.log` with stdout/stderr captured for audit.
- proxy-aware endpoint settings from `AGENT_LLM_BASE_URL`; the current AI server deployment uses `http://192.168.50.222:4001`.
- a dashboard API base, default `http://localhost:8000`, so agents can fetch ticket context, write notes, request approvals, and persist postmortems/workflows through the canonical API.

Claude is invoked with:

```bash
claude --allowedTools "Read,Write,Bash(curl *)" -p --settings <work_dir>/.claude/settings.json --model <selected_model> --permission-mode acceptEdits --no-session-persistence --output-format stream-json --verbose "<prompt>"
```

The runner uses the configured proxy endpoint for Claude Code requests. For local models, `AGENT_LLM_AUTH_TOKEN` defaults to the non-secret `lmstudio` marker expected by the local proxy; external provider credentials stay in Claude Code OAuth files or the proxy environment, not in source. `AGENT_LLM_BASE_URL` is required so each environment chooses a normal routable endpoint instead of relying on Docker host aliases.

Managed agents run with `acceptEdits` plus the narrow allowlist `Read,Write,Bash(curl *)`. This permits dashboard API calls without allowing arbitrary shell operations. Claude Code refuses full bypass mode when running as root, and full bypass is not needed because destructive work is guarded by dashboard change requests.

Runner diagnostics are available at:

```bash
curl -sS http://localhost:25480/api/agents/runner-health
curl -sS http://localhost:25480/api/agents/processes
```

This reports the effective API base URL, whether `/v1/models` is reachable from inside the API container, and the runner-side `ps` process view. The API image installs `procps` so process inspection is available inside the slim Python container.

Agent output is captured in streaming JSON mode so the dashboard can show Claude Code init, assistant/result events, stdout/stderr tails, and process heartbeat progress even before the agent writes its own checkpoint file. The runner does not modify `checkpoint.json` after provisioning; that file is agent-owned.

When a checkpoint says `done` or `completed`, the tracker records task completion and terminates the harness process so local GPU work does not continue after the useful artifact is complete. The runner mirrors the final checkpoint before deciding final task state, so operator stops or tracker termination after a done checkpoint still resolve as completed.

Wake/restart semantics are explicit:

- `Wake` checks for an already queued/running task. If one exists, it refreshes the heartbeat and returns the active task id.
- If no task is active, `Wake` spawns a replacement agent using the latest stored prompt and task type.
- `Restart` stops the current active task when possible, terminates the old agent row, then spawns a replacement using the latest stored prompt and task type.

## Models

Models are configured in `agent_models.json`:

```json
{
  "models": [
    "qwen/qwen3.6-27b",
    "qwen/qwen3.6-27b2",
    "qwen/qwen3.6-27b3",
    "qwen/qwen3.6-27b4",
    "qwen/qwen3.6-27b5"
  ],
  "default": "qwen/qwen3.6-27b"
}
```

The dashboard reads `/api/agents/models` and populates model selectors from this file.

## API Highlights

- `POST /api/tickets`: create a canonical local/provider ticket.
- `GET /api/tickets/{id}/context`: complete agent context bundle, including notes, attachments, related tickets, KB, workflows, postmortems, changes, tasks, and global skills.
- `POST /api/tickets/{id}/notes`: add an internal/user-visible note.
- `POST /api/tickets/{id}/attachments`: record attachment metadata.
- `POST /api/tickets/{id}/push-provider`: push an existing canonical ticket to its provider.
- `GET /api/providers`: list ticket providers.
- `POST /api/providers/{provider}/sync-all`: sync a provider.
- `POST /api/providers/{provider}/sync-ticket`: sync a single provider ticket.
- `POST /api/agents/spawn`: spawn an agent for an existing ticket.
- `POST /api/agents/create-from-prompt`: create a local ticket and spawn an agent from free text.
- `GET /api/agents/tasks`: list task queue/history.
- `GET /api/agents/runner-health`: Claude Code, credentials, proxy, and model API diagnostics.
- `GET /api/agents/processes`: runner-side process snapshot using `ps`, plus in-memory tracked tasks.
- `GET /api/agents/tasks/{task_id}/logs`: output log tail for a task.
- `GET /api/agents/{id}`: agent detail, latest task, checkpoints, output, changes, audit.
- `GET /api/agents/{id}/logs`: output log tail for the latest agent task.
- `POST /api/agents/{id}/stop`: terminate active task and mark stopped.
- `POST /api/agents/{id}/restart`: terminate current agent and spawn a replacement.
- `GET /api/dashboard/audit`: merged `audit_log` and `event_log`.
- `GET /api/dashboard/audit`: supports `actor`, `action`, `source`, `category`, `level`, `target`, `q`, `ticket_id`, `agent_id`, and `limit`.
- `POST /api/tickets/{id}/postmortem`: spawn a postmortem agent for a ticket.
- `POST /api/tickets/{id}/workflow`: spawn a workflow-build agent for a ticket class/use case.
- `GET/POST/PUT /api/postmortems`: durable postmortem records and human review state.
- `GET/POST/PUT /api/workflows`: reusable workflow blueprints, test plans, approval policies, and review state.
- `GET/POST/PUT /api/knowledge`: reusable knowledge articles.
- `GET/POST/PUT /api/skills`: agent skill registry.

## Agentic Ticket Workflow

Default ticket assignment is optimized for fast resolution, not automatic playbook creation. Agents are prompted to read the current ticket, keep checking for notes/attachments/context, inspect prior tickets and skills when available, work non-destructively where possible, and create change requests before environment-changing actions.

Postmortems are separate follow-up tasks. They review ticket context, task logs, checkpoints, approvals, errors, and gaps, then propose reusable workflows, candidate skills, tests, guardrails, and documentation updates. Workflow-build tasks then create or improve skills/scripts in test-safe paths, run safe tests, document the full runbook, and stop before production deployment for human review.

External ticket links are built from `ITOP_WEB_BASE` when available, falling back to `ITOP_HOST`/`ITOP_PORT`. Local `LOCAL-*` tickets intentionally do not receive an external URL.

## Deployment

Use the server-manager skill. Do not use raw SSH.

```powershell
C:\Users\cereal\.agents\skills\server-manager\.venv\Scripts\python.exe C:\Users\cereal\.agents\skills\server-manager\ssh_client.py --server ai --upload-dir "C:\path\to\soc-dashboard" "/home/cereal/SOC_TESTING/soc-dashboard"
```

Then on the AI server:

```bash
cd /home/cereal/SOC_TESTING/soc-dashboard
docker compose up -d --build api
docker exec -i soc-dashboard-db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < api/migrations/002_agent_runner_hardening.sql
docker exec -i soc-dashboard-db sh -c 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"' < api/migrations/003_agentic_system_objects.sql
curl -sS http://localhost:25480/health
```

If `agent_work` was created by an earlier root-run container, fix ownership before switching runtime users or bind mounts:

```bash
sudo chown -R cereal:cereal /home/cereal/SOC_TESTING/soc-dashboard/agent_work
```

## Test Checklist

1. `python -m py_compile` over all API modules.
2. `node --check` over all frontend JS files.
3. Secret and prohibited-library sweep: search for old placeholder credentials, dummy local-model keys, API key literals, Pydantic, and SQLAlchemy. The command should return no matches outside intentional policy text.
4. Rebuild API container.
5. Health check:
   ```bash
   curl -sS http://localhost:25480/health
   curl -sS http://localhost:25480/api/agents/runner-health
   curl -sS http://localhost:25480/api/agents/processes
   ```
6. Spawn a short proof agent:
   ```bash
   curl -sS -X POST http://localhost:25480/api/agents/create-from-prompt \
     -H 'Content-Type: application/json' \
     -d '{"model":"qwen/qwen3.6-27b","prompt":"Write checkpoint.json with step=test, status=done, progress_pct=100, and output=agent runner smoke test complete. Then respond with a one-line summary."}'
   ```
7. Poll `/api/agents/tasks` until the task is `completed` or `failed`.
8. Open the UI and verify the Agents page shows model, task status, progress, checkpoints, stop/restart controls, and output/error detail.

## Agentic Smoke Tests

Run these from the deployed server path after rebuild/migration:

```bash
cd /home/cereal/SOC_TESTING/soc-dashboard
python3 scripts/smoke_agentic_system.py http://localhost:25480
python3 scripts/smoke_setup_platform.py http://localhost:25480
python3 scripts/smoke_phishing_workflow_lifecycle.py http://localhost:25480
python3 scripts/smoke_local_model_agent.py http://localhost:25480 qwen/qwen3.6-27b
python3 scripts/smoke_setup_agent.py http://localhost:25480 qwen/qwen3.6-27b
curl -sS http://localhost:25480/api/agents/processes
```

Expected results:

- `smoke_agentic_system.py` creates and verifies a local canonical ticket, note, attachment metadata, KB article, skill, approval-gated change, postmortem, workflow, and unified context bundle.
- `smoke_setup_platform.py` verifies the module manifest, product-agnostic setup planning, setup ticket creation, exclusions, and installer dry-run.
- `smoke_phishing_workflow_lifecycle.py` verifies a safe phishing ticket lifecycle across approval, workflow, postmortem, context, and audit objects without invoking a model.
- `smoke_local_model_agent.py` spawns Claude Code through the local proxy using `qwen/qwen3.6-27b`; the agent reads context, writes a ticket note through the dashboard API, writes a done checkpoint, completes the task, and leaves no active Claude processes.
- `smoke_setup_agent.py` verifies a setup ticket can be worked by a short local-model agent without deploying anything.
