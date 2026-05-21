# Agentic Operations UI Overhaul - 2026-05-21

## Scope

This pass turns the dashboard from a mostly static control plane into a
filterable, sortable operator console for demos and production-style triage.

Updated surfaces:

- Global search result modal now supports type/status filters and sorting.
- Overview metric tiles route into the relevant operational page.
- Tickets support text, provider, and agent-state filters in addition to
  status and sortable columns.
- Intake sessions, changes, workflows, postmortems, CI/CD runs, tools, skills,
  and access users are sortable and filterable.
- Learning is focused on knowledge articles only; Skills is now its own plane.
- Skills can be viewed, edited, activated/deactivated, and linked to saved
  agent runtime profiles.
- Settings profile editor includes a skill checklist. Leaving it empty means
  all enabled default skills remain available; selected skills are pinned into
  that saved profile's agent context.
- Tools distinguish active health-checked services from blueprint modules and
  inventory records with no running health probe.
- Setup no longer shows the old Runtime Handoff or Generated Setup Plan blocks.
  The Provider-Agnostic Modules grid is the primary setup planning surface.
- Access adds policy views for summary, role capabilities, API route
  requirements, and vault broker behavior.
- Audit rows are compact and expandable with target/ticket/agent quick links.

## Backend Changes

- `GET /api/tickets` accepts:
  - `q`
  - `provider`
  - `agent_state`
- Agent runtime profile `skills` are now used during spawn. Default/global
  skills are still included, and profile-selected enabled skills are appended
  to the agent context.

No ORM, Pydantic, SQLAlchemy, SQLite, or backup database path was introduced.
The backend changes use raw async SQL through the existing database helpers.

## Validation

Local checks:

```powershell
node --check frontend/js/dashboard.js
python -m py_compile api\routes\tickets.py api\services\agent_runner.py
python -m pytest tests/test_access_control_policy.py tests/test_agent_harness.py tests/test_frontend_ui_regressions.py tests/test_setup_module_scope.py tests/test_skill_sync_preserve.py -q
```

Expected focused result:

```text
45 passed
```

Live validation should use the dashboard UI skill runbook:

1. Check active agents before rebuilding the API.
2. Sync static frontend files.
3. Rebuild/recreate only `api` for backend changes.
4. Log in to `https://192.168.50.222:25443/`.
5. Crawl Overview, Tickets, Intake, Changes, Workflows, Postmortems, CI/CD,
   Learning, Skills, Tools, Setup, Access, Audit, and Settings.
6. Confirm no console errors, no horizontal overflow, and visible filters on
   every requested plane.

Live Playwright crawl evidence:

- `docs/evidence/playwright-ui-overhaul-2026-05-21.json`

## Demo Notes

- Use the Skills plane when explaining that agents can be given different
  capability bundles by saved runtime profile.
- Use Tools to explain the difference between deployed/health-checked services
  and provider modules that are only deployment blueprints.
- Use Access policy views to explain FedRAMP-style controls without diving into
  raw JSON.
- Use compact Audit rows during demos; expand only the events that prove the
  timeline or permission boundary.
