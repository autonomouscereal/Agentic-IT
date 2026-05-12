# Live Deployment Diff - 2026-05-12

This note records the read-only comparison between the AI server deployment at
`/home/cereal/SOC_TESTING/soc-dashboard` and the local Git worktree. The live
tree was archived without runtime state: `.env`, `.git`, `data`, `agent_work`,
`demo_runs`, caches, and bytecode were excluded.

## Product Direction From Notes

The intended platform is a harness-agnostic, private/local-by-default agentic
IT/SOC replacement control plane. It must support one-line bootstrap, modular
integrations, provider-backed ticket sync, auditable agent work, approval gates,
agent self-monitoring, reusable workflow learning, CI/CD security gates, and
demo-ready end-to-end workflows.

Current priority notes call out:

- Fix credentials and remove hardcoded secrets.
- Fix Mailcow API/shim behavior, iTop UI rendering, and Sysmon/EDR workflows.
- Preserve and migrate bridges/skills rather than abandoning Claude-era work.
- Make intake auto-classify and auto-sync to the configured ticket provider.
- Add editable RACI routing and user-response/pending-response workflows.
- Improve CI/CD findings, report links, before/after scan visibility, and repo links.
- Keep tools dynamic and remove unrelated media/ComfyUI inventory.
- Test with real agent workflows after code/deployment sync is resolved.

## What Was Deployed Before Sync

The AI server source directory is not a Git checkout. It is a copied source tree
with no `.git` metadata, so live-vs-local must be compared by snapshots.

The live API at `http://192.168.50.222:25480/health` reports version `1.3.0`.
Before the 2026-05-12 deployment, the live source contained many dashboard
features but was behind local Git for several routes and UI affordances.

## Important Differences

### Live Was Missing Local Product Features

Local Git included these features that were absent from the deployed source:

- `POST /api/intake/clarify`
- RACI CRUD endpoints:
  - `POST /api/intake/raci/groups`
  - `PUT /api/intake/raci/groups/{id}`
  - `DELETE /api/intake/raci/groups/{id}`
  - `POST /api/intake/raci/rules`
  - `PUT /api/intake/raci/rules/{id}`
  - `DELETE /api/intake/raci/rules/{id}`
- User-response workflow endpoints:
  - `POST /api/tickets/{id}/request-info`
  - `POST /api/tickets/{id}/user-response`
- CI/CD run detail enrichment:
  - `repo_url`
  - parsed scanner report links from `tool_results`
  - related before/after runs
- Dashboard UI for:
  - intake clarification and RACI editing
  - change rows linking back to ticket details
  - CI/CD finding/report/repo links
  - richer audit trail links and ticket activity panels

This explained the live smoke failure on `/api/intake/clarify`: the deployed API
source and container were older than the local Git tree for the intake workflow.

### Live Has Artifacts That Should Not Be Preserved As Runtime State

The deployed source includes runtime/generated files that should not be committed
or copied back into the portable bundle:

- `reference_skills/server-manager/.server_state`
- `.env`
- `tests/__pycache__/*`
- `scripts/__pycache__/*`

The local `.gitignore` now ignores `_compare_live/` snapshots as local scratch
state.

### Live Has A Useful Credential Skill That Local Had Dropped

Live contained `reference_skills/credential-vault` with a reusable shell
`load_secret` helper. That is useful and aligned with the "fix creds" priority.
It has been restored as a first-class `.agents` skill and added to
`platform/skill_sync_config.json`, then staged into `reference_skills`.

The restored resolver delegates secret retrieval to `server-manager/credman.py`
and does not include plaintext credentials.

### Local Skill Bundle Is Cleaner Than Live

The local reference bundle removes or fixes several migration hazards found in
older live/reference material:

- no `.Codex` skill paths
- no retired direct AI-server shortcut flag in server-manager commands
- no Claude-only server-manager path dependency
- no raw Paramiko upload helper with a hardcoded password
- no hardcoded GitLab PAT fallback in GitLab scripts
- no committed `.server_state`

`scripts/audit_codex_migration.py --source-roots "C:/Users/cereal/.agents/skills"`
passes after restoring `credential-vault`.

## Sync Decision

Do not treat the live tree as authoritative wholesale. The correct merge line is:

1. Keep local Git product code for API/UI/docs because it contains committed
   functionality required by the current notes and smoke tests.
2. Preserve live-only `credential-vault` as a clean, reusable skill.
3. Drop live runtime state and generated files from any sync.
4. Deploy only after local verification passes, then rerun live smoke and real
   workflow tests.

## Verification Already Run

- `python -m compileall api scripts tests` passed locally.
- `python -m unittest discover -s tests -v` passed locally.
- `python scripts/audit_codex_migration.py --source-roots "C:/Users/cereal/.agents/skills"` passed.
- Live SSH and dashboard health checks passed through server-manager.
- Live `smoke_provider_adapters.py` passed.
- Live `smoke_service_desk_intake.py` failed because `/api/intake/clarify` is
  not deployed yet.

## Deployment Completed

The local Git tree was deployed to `/home/cereal/SOC_TESTING/soc-dashboard` on
2026-05-12 with runtime-state exclusions for `.env`, `.git`, `data`,
`agent_work`, `runtime`, caches, and bytecode. The API was rebuilt and
force-recreated so bind-mounted directories such as `/app/platform` were
attached cleanly.

Two regressions surfaced during live verification and were fixed in commit
`6a9b766`:

- Explicit `provider: "local"` ticket creation now stays local instead of
  falling through to configured iTop auto-sync.
- Postmortem promotion notes now include the source postmortem id, preserving
  the evidence link in ticket context.

Final live regression passed end to end:

- `/health`: `{"status":"ok","version":"1.3.0"}`
- `POST /api/intake/clarify`: 200 OK
- `python3 -m compileall api scripts tests`: PASS
- frontend `node --check frontend/js/*.js`: PASS
- `python3 -m unittest discover -s tests -v`: PASS, 4 tests
- `python3 scripts/audit_codex_migration.py --source-roots "$APP/reference_skills"`: PASS
- `python3 scripts/platform_doctor.py --base http://localhost:25480 --env-file .env`: PASS 18/18
- smoke suite: setup platform, provider adapters, service desk intake,
  user response, agentic system, phishing workflow lifecycle, CI/CD security
  pipeline, agent auditor, postmortem promotion, change auto-completion,
  local-model agent, and setup agent all passed.

Final containers:

- `soc-dashboard-api-1`: up on `0.0.0.0:25480->8000/tcp`
- `soc-dashboard-db-1`: up and healthy on `0.0.0.0:5433->5432/tcp`

## Next Safe Steps

1. Keep the local Git tree as the source of truth for product code.
2. Use runtime-state exclusions for future deploys.
3. Rebuild and force-recreate the API container after replacing source
   directories.
4. Run the documented live regression before considering deployment complete.
