---
name: agentic-ops-dashboard-ui
description: Validate and safely deploy Agentic Operations dashboard UI changes on the AI server, including authenticated Playwright checks, ticket pagination, setup module UX, agent harness controls, and narrow API service recycling.
---

# Agentic Ops Dashboard UI

Use this skill when changing, deploying, or testing the Agentic Operations
dashboard UI at `https://127.0.0.1:25443/`.

## Rules

- Work from `D:\IT AGENT PROJECT`.
- Use server-manager for all AI server work. Do not use raw SSH.
- Use the dashboard HTTPS edge for browser/Playwright validation:
  `https://127.0.0.1:25443/`.
- Login at `/login` as `demo_account_1`; retrieve the password from the
  server-manager vault key `demo_account_1`.
- For chat/intake UI proof, use Element at
  `https://127.0.0.1:3303/#/user/@agentic-ops:agentic-ops.local` with a
  demo chat account such as `demo_chat_alice`, `demo_chat_jeff`, or
  `demo_chat_exec` from the same vault.
- Never print or commit secrets.
- Check active agents before recreating the API service.
- Static `frontend/` changes can be synced without restarting containers.
- Backend Python changes require rebuilding and recreating only the `api`
  service.
- Before demo cleanup or API recreation, confirm there are no active agents.
  The 2026-05-21 demo baseline should show zero open tickets, zero active
  agents, zero open tasks, and zero pending/approved changes.

## Preflight

From the AI server deployment directory:

```bash
cd /opt/agentic-it/SOC_TESTING/soc-dashboard
docker compose ps
curl -k -fsS https://127.0.0.1:25443/nginx-health
docker compose exec -T api python - <<'PY'
import asyncio, json, sys
sys.path.insert(0, "/app")
async def main():
    from database import fetchall
    rows = await fetchall("""
        SELECT at.id AS task_id, at.status AS task_status, a.id AS agent_id,
               a.status AS agent_status, at.task_type
        FROM agent_tasks at
        JOIN agents a ON a.id = at.agent_id
        WHERE at.status IN ('queued','running')
           OR a.status IN ('spawned','running','working')
        ORDER BY at.created_at DESC
        LIMIT 30
    """)
    print(json.dumps([dict(r) for r in rows], default=str, indent=2))
asyncio.run(main())
PY
```

If active tasks exist, prefer static-only deployment or wait for operator
approval before API recreation.

## Static-Only Deploy

Sync these files to `/opt/agentic-it/SOC_TESTING/soc-dashboard`:

- `frontend/index.html`
- `frontend/js/dashboard.js`
- `frontend/js/agents.js`
- `frontend/css/dashboard.css`
- `agent_models.json`
- relevant docs

No restart is needed for mounted static files.

## Backend Deploy

Only when agent interruption is acceptable or no active tasks exist:

```bash
cd /opt/agentic-it/SOC_TESTING/soc-dashboard
python3 -m py_compile api/services/agent_runner.py api/routes/agents.py api/routes/tickets.py api/routes/setup.py
docker compose build api
docker compose up -d --no-deps --force-recreate api
docker compose exec -T api python - <<'PY'
import sys
sys.path.insert(0, "/app")
from services.agent_runner import get_agent_runtime_config
print("ready")
PY
```

## Playwright Smoke

Use local Playwright with `ignoreHTTPSErrors: true`.

Required assertions:

- Auth succeeds and dashboard shell is visible.
- Tickets page loads `200` rows initially, then more rows after scrolling.
- Ticket footer shows the true total, for example `Showing 400 of 1095 tickets`.
- Tickets page `Demo Proofs` shows the curated order:
  `1384`, `1385`, `1386`, `1309`, `1282`, `1176`, `695`, `690`, `83`,
  `580`, `525`, `539`, `531`, `422`, `575`, `530`, `118`, `363`, `430`,
  `578`.
- Setup page module search/filter is visible and returns a sensible count.
- Agents page shows harness options `hermes`, `claude-code`, and `codex`.
- Saving default harness/model returns `Saved server default.`
- `/api/agents/config` readback matches the selected default.
- Global search is visible above every dashboard page and can find a unique
  marker from tickets, ticket notes, agents, audit, workflows, postmortems,
  tools, and CI/CD records according to the logged-in user's scope. Its result
  modal must expose type/status filters plus sort controls.
- Overview metric tiles must route to the corresponding page/filter.
- Intake sessions, changes, workflows, postmortems, CI/CD runs, tools, skills,
  access users, and audit rows must be sortable/filterable.
- Learning is knowledge-only; Skills is a standalone page with view/edit,
  activate/deactivate, and runtime-profile assignment.
- Settings profile editor must render a skill checklist.
- Tools must distinguish active health-checked services from blueprint/no-probe
  modules.
- Setup must not show the removed Runtime Handoff or Generated Setup Plan
  panels.
- Audit must render compact expandable rows, not giant always-open JSON cards.
- Ticket modals must render operator-safe task summaries. Sequence of Events
  and Agent Work should use checkpoint/result summaries and must not expose raw
  harness JSONL, `AGENT_MEMORY_SKILL_DIR`, `aggregated_output`, shell command
  fragments, or giant copied chat history in the demo-facing view.
- Ops Chat Element proof can log in through Keycloak, open the Agentic Ops Agent
  profile, send a direct message, and show a dashboard ticket or no-ticket
  answer according to the request.
- Overflow count is zero for the checked viewport.
- Console errors are zero after filtering expected network interruptions only.

## Current Evidence

The 2026-05-20 deploy evidence is documented in:

`docs/AGENTIC_OPS_UI_DEPLOYMENT_2026-05-20.md`

The broad search/filter/sort console overhaul is documented in:

`docs/UI_OVERHAUL_2026-05-21.md`

Ticket `1409` is the current regression proof for ticket-modal readability:
authenticated Playwright opens the ticket, waits for Evidence Trail, confirms
task `375` renders a checkpoint summary, confirms prior chat context is
compacted, and confirms raw task markers are absent from the demo-facing view.

Ops Chat and global-search readiness are documented in:

- `docs/GLOBAL_SEARCH_AND_OPS_CHAT.md`
- `docs/DEMO_TICKET_CATALOG.md`

Current polished proof tickets:

- `1384`, `1385`, and `1386`: newer Ops Chat proof that one workspace can
  create, cancel, replace, and separately route multiple tickets without
  duplicate bloat.
- `1309`: chat-created DevSecOps delivery-gate ticket with iTop sync and
  urgency follow-up.
- `1282`: requester/affected-user metadata proof for software install intake.
- `1176`: reassignment/escalation proof from Endpoint Support to Tier 2.
- `695`: lead URL-safe phishing plus EDR hybrid with user response, steering,
  access wall, containment gate, postmortem, and provider close recovery.
- `690`: cleaner learning/workflow proof for the same incident type.
- `83`: GitLab CI/CD gate, agent remediation branch, MR, final passing
  pipeline, and deployment approval.
- `580`: Roundcube Report Phish to Mailcow quarantine.
- `525` and `539`: least-privilege access walls and scoped lease/resume.
- `docs/OPS_CHAT_DEPLOYMENT_BLUEPRINT.md`
- `docs/OPS_CHAT_AGENTIC_UI_TESTING_AND_DEMO_READINESS.md`
