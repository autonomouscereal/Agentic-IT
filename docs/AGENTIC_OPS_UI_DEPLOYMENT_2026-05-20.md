# Agentic Operations UI Deployment - 2026-05-20

## Scope

This deployment fixed the authenticated Agentic Operations dashboard at
`https://192.168.50.222:25443/` without tearing down the environment:

- Tickets page now incrementally loads all tickets with `limit` / `offset`.
- Setup page has searchable/filterable provider-agnostic module controls.
- Agents page exposes default harness/model controls and named harness/model setups.
- `agent_models.json` is writable from the API container so non-secret runtime defaults persist.
- Changes/Postmortems action columns no longer force horizontal overflow.

## Credentials And Entry Points

- Browser/Playwright target: `https://192.168.50.222:25443/`
- Login: `/login`
- Dashboard user: `demo_account_1`
- Password source: server-manager vault key `demo_account_1`
- Internal service API: `http://127.0.0.1:25480` on the AI server only. Auth-enforced endpoints can return `403` by design.
- Public edge health: `https://127.0.0.1:25443/nginx-health` from the AI server, with `curl -k`.

Do not paste vault secrets into docs, source, shell transcripts, or chat.

## Deployed Files

Static/mounted files were synced directly into `/home/cereal/SOC_TESTING/soc-dashboard`:

- `frontend/index.html`
- `frontend/js/dashboard.js`
- `frontend/js/agents.js`
- `frontend/css/dashboard.css`
- `agent_models.json`
- `README.md`
- `docker-compose.yml` mount change: `./agent_models.json:/app/agent_models.json:rw`

Backend fix deployed by rebuilding/recreating only the API service:

- `api/services/agent_runner.py`

The backend change adds an in-place write fallback for Docker bind-mounted
single-file configs when atomic replace is rejected.

## Commands Used

Remote work used the server-manager vault-backed SSH client only:

```powershell
python "C:\Users\cereal\.agents\skills\server-manager\ssh_client.py" --server ai --command-file <script>
python "C:\Users\cereal\.agents\skills\server-manager\ssh_client.py" --server ai --upload <local> <remote>
```

The API recycle was intentionally narrow:

```bash
cd /home/cereal/SOC_TESTING/soc-dashboard
docker compose build api
docker compose up -d --no-deps --force-recreate api
```

## Validation Evidence

Final authenticated Playwright smoke used the vault credential and local CA
ignore. Result file:

`C:\Users\cereal\Documents\Codex\2026-05-20\without-rebuilding-the-environment-i-want\playwright-evidence-final-deploy\final-deploy-result-after-backend.json`

Final observed results:

- Authenticated login: pass
- Ticket API total: `1095`
- Ticket rows before scroll: `200`
- Ticket rows after scroll: `400`
- Ticket footer: `Showing 400 of 1095 tickets`
- Setup module filter for `proxy`: `3 of 42 modules`
- Agent default save: `Saved server default.`
- Server config readback: `default_harness=hermes`, `default_model=deepseek/deepseek-v4-flash`
- Named setups visible: `Hermes local default`, `Claude external fallback`
- Overflow count: `0`
- Console messages: none

Server-side checks:

- `docker compose ps api dashboard-tls-proxy` showed both services up.
- `curl -k -fsS https://127.0.0.1:25443/nginx-health` returned OK.
- `/app/agent_models.json` exists and is writable inside the API container.
- Runner health reports Hermes as the default harness and model API reachable.

## Gotchas

- `/health` on `127.0.0.1:25480` can return `403` when auth enforcement is on.
  Use the HTTPS proxy health route or an authenticated/service-token API call.
- Static frontend changes take effect without a container restart because
  `frontend/` is bind-mounted.
- Backend code changes require `docker compose build api` plus
  `docker compose up -d --no-deps --force-recreate api`.
- Avoid recreating the API while `agent_tasks` are `queued` or `running` unless
  the operator explicitly stops or accepts interruption.

## Focused UI Repair After Operator Review

After operator review, Tickets were left alone and the repair scope was narrowed
to Agents, Intake, and Setup.

Static-only redeploy:

- `frontend/index.html`
- `frontend/css/dashboard.css`
- `frontend/js/dashboard.js`

No containers were rebuilt or restarted for this focused repair.

Changes:

- Agents: compacted default harness/model controls, custom setup controls, and
  spawn prompt layout; changed the destructive custom setup action label to
  `Remove` and made it visually quieter.
- Intake: split requester and routing preview into a two-column operator layout,
  shortened the request textarea, and limited the RACI list preview to the first
  five rules so the page is scannable.
- Setup: compacted Deployment Shape into a label/control grid, kept Runtime
  Handoff from stretching the row, made Provider-Agnostic Modules full width,
  tightened module cards, reduced module note height, and wrapped toolbar
  controls cleanly.

Validation evidence:

- Local regression suite: `python -m pytest tests/test_frontend_ui_regressions.py`
  returned `12 passed`.
- Authenticated Playwright crawl used `https://192.168.50.222:25443/` with
  `demo_account_1` from the vault.
- Screenshots and metrics:
  `C:\Users\cereal\Documents\Codex\2026-05-20\without-rebuilding-the-environment-i-want\playwright-ui-fix-focused-final`
- Final Playwright metrics showed `overflows: []` for Agents, Intake, and Setup.

## Workflow Button Repair

After operator review, the Workflows page row actions were repaired without
touching backend services.

Static-only redeploy:

- `frontend/css/dashboard.css`
- `frontend/js/dashboard.js`

Changes:

- Wrapped each workflow row action set in a dedicated `.workflow-actions`
  control stack.
- Added explicit vertical gaps so `Detail` and `Approve` no longer touch.
- Changed workflow row and modal actions to quieter outlined buttons so the
  action column does not visually dominate the table.

Validation evidence:

- Local regression suite: `python -m pytest tests/test_frontend_ui_regressions.py`
  returned `12 passed`.
- Authenticated Playwright crawl used `https://192.168.50.222:25443/` with
  `demo_account_1` from the vault.
- Screenshots and metrics:
  `C:\Users\cereal\Documents\Codex\2026-05-20\without-rebuilding-the-environment-i-want\playwright-workflows-buttons`
- Final Playwright metrics showed workflow row button gap `7px` and
  `overflows: []`.

## Learning Page Tab Split

After operator review, the Learning page was simplified because Postmortems
already has its own first-class page.

Static-only redeploy:

- `frontend/index.html`
- `frontend/css/dashboard.css`
- `frontend/js/dashboard.js`

Changes:

- Removed the duplicate Postmortems table from Learning.
- Split Learning into two tabs only: `Knowledge Articles` and `Skills`.
- Moved article actions into the Knowledge tab and skill creation into the
  Skills tab.
- Added a frontend regression test so `postmortems-tbody` cannot reappear in
  the Learning page section.

Validation evidence:

- Local regression suite: `python -m pytest tests/test_frontend_ui_regressions.py`
  returned `13 passed`.
- Authenticated Playwright crawl used `https://192.168.50.222:25443/` with
  `demo_account_1` from the vault.
- Screenshots and metrics:
  `C:\Users\cereal\Documents\Codex\2026-05-20\without-rebuilding-the-environment-i-want\playwright-learning-tabs`
- Final Playwright metrics showed `duplicatePostmortemsTable: false`,
  `visiblePostmortemText: false`, and `overflows: []`.
