# Installer E2E Results

Last verified: 2026-05-19

## HTTPS/Hermes One-Line Regression - 2026-05-19

Current proxy correction after the regression: the live lab now uses one
Compose-managed proxy on host/LAN port `4001` (`0.0.0.0:4001->4001/tcp`) and
containers use `http://ai-proxy:4001`. The old standalone `ai-proxy` container
was removed and host `4401` is no longer listening. Clean installs default to
`--proxy-port 4001`; the `4401` references below are historical artifacts from
the same-port destructive test when an older standalone proxy still owned
`4001`.

Setup fan-out source regression on 2026-05-19:

- Setup planning now accepts per-module `module_actions` so each capability can
  be set to deploy reference, integrate existing, or off/not in scope.
- Setup ticket creation now returns a parent setup ticket plus scoped child
  module tickets for actionable deploy/integrate steps. Disabled modules are
  omitted from setup work, while dependent modules are reported as
  `blocked_disabled_dependency`.
- Local source validation passed with `147 passed`, JS syntax checks, and text
  hygiene. `scripts/smoke_setup_platform.py` now asserts disabled modules,
  blocked dependencies, and child module ticket creation.
- Live hardened API smoke passed against `http://127.0.0.1:25480` with service
  token auth after deployment: setup parent ticket `624` was created with `7`
  scoped module tickets, disabled module scope, and blocked dependency
  validation.
- Authenticated HTTPS Chrome check passed against
  `https://192.168.50.222:25443`: `demo_account_1` opened Setup, the per-module
  action selector rendered `Deploy reference`, `Integrate existing`, and
  `Off / not in scope`, and no console/page/http errors were observed.
- Post-rebuild live checks passed after the agent runner safety patch:
  setup-plan smoke returned `28` plan steps, `1` disabled module, and `4`
  blocked dependency steps; the container curl guard accepted explicit allowed
  host lists and still emitted the suspicious external URL block rule.
- Incremental setup module controls passed live after deployment: hardened smoke
  created parent setup ticket `670` with `7` child tickets and single-module
  reinstall ticket `678`; `/api/setup/status` correctly reports
  `soc-dashboard` as `built_in` and Wazuh from tool inventory; authenticated
  Chrome verified `41` module note fields, per-module ticket controls,
  `Undeploy`, `Reinstall`, `Keep active`, and no console/page/http errors.

Backup before destructive testing:

- Local server-manager vault backup: `2026-05-19_033810`.
- AI server deployment backup:
  `/home/cereal/agentic-it-backups/20260519T033953Z`.
- Backup contents include `.env`, compose config, dashboard PostgreSQL dump,
  agent-memory PostgreSQL dump, and a tarball of the deployed dashboard tree
  including runtime TLS assets. Private keys were not printed or copied into
  docs.

Destructive same-port rebuild:

```bash
cd /home/cereal/SOC_TESTING/soc-dashboard
bash ./install.sh \
  --profile soc \
  --source /home/cereal/SOC_TESTING/soc-dashboard \
  --target /home/cereal/SOC_TESTING/soc-dashboard-one-line-rebuild-20260519T040250Z \
  --dashboard-port 25480 \
  --https-port 25443 \
  --db-port 5433 \
  --memory-db-port 25491 \
  --proxy-port 4401 \
  --project-name soc-dashboard-rebuild-20260519T040250Z \
  --proxy-mode deploy \
  --harness hermes \
  --provider nous \
  --model deepseek/deepseek-v4-flash \
  --itop-sync-enabled false \
  --spawn-setup-agent \
  --non-interactive
```

Result:

- Fresh stack installed from one command on the same operator ports while the
  live stack was stopped.
- HTTPS edge `/nginx-health` and `/` login redirect passed.
- Built-in proxy health passed using loopback health URL
  `http://localhost:4401`; `/v1/models` returned 10 model aliases.
- Runner health showed Hermes and Claude Code available, Hermes selected,
  Nous auth present, and default model `deepseek/deepseek-v4-flash`.
- Setup ticket `1` and setup agent `1` were created in the fresh stack.
- Fresh stack was torn down with `docker compose down -v`, then the original
  live stack was restored and `scripts/smoke_dashboard_https.py
  https://localhost:25443` passed.
- After restore, runtime proxy drift was reconciled: the live dashboard sent
  spawned agents to the Compose-managed proxy through
  `AGENT_LLM_BASE_URL=http://ai-proxy:4001` from inside Docker. This was later
  cleaned up so the same Compose-managed proxy owns host/LAN port `4001` and
  host `4401` is gone.
- Post-route Hermes smoke passed on ticket `620`, agent `255`, task `252`;
  the task completed, wrote its setup note, and `/api/agents/processes` cleared
  after the Hermes memory stop hook finished.

Non-disruptive alternate-port setup-agent completion proof:

```bash
bash ./install.sh \
  --profile soc \
  --source /home/cereal/SOC_TESTING/soc-dashboard \
  --target /home/cereal/SOC_TESTING/soc-dashboard-one-line-alt-20260519T041126Z \
  --dashboard-port 31080 \
  --https-port 31443 \
  --db-port 31001 \
  --memory-db-port 31090 \
  --proxy-port 31091 \
  --project-name soc-dashboard-alt-20260519T041126Z \
  --proxy-mode deploy \
  --harness hermes \
  --provider nous \
  --model deepseek/deepseek-v4-flash \
  --itop-sync-enabled false \
  --spawn-setup-agent \
  --non-interactive
```

Result:

- Installer reported `status: installed`.
- HTTPS smoke passed on `https://localhost:31443`.
- Proxy health passed on `http://localhost:31091`; model count was 10.
- Setup agent `1`, task `1` ran through Hermes/DeepSeek and completed at
  100%.
- Ticket `1` contained the `SETUP_ONBOARDING_BOOTSTRAP_COMPLETE` agent note.
- `/api/agents/processes` reported no active processes after completion.
- Disposable stack was removed with `docker compose down -v`.

Issues found and fixed:

- `install.sh` was not executable in the deployed checkout. The source now
  records executable mode; the live checkout was repaired with `chmod +x`.
- Same-host reinstall needed a configurable agent-memory host port because
  the AI server already has another memory service on `25490`. Added
  `--memory-db-port`.
- The hardened built-in proxy binds to `127.0.0.1`, but the installer checked
  the LAN IP. Installer now uses `proxy_health_url=http://localhost:<port>` for
  built-in proxy health and model checks.
- The initial spawned setup-agent prompt was too broad for installer E2E and
  could fail while trying to reason about a full deployment. It is now a
  bounded bootstrap verification that reads setup context, runner health,
  manifest, and profiles, writes `SETUP_ONBOARDING_BOOTSTRAP_COMPLETE`, and
  exits at 100%.

Related real-agent regression proofs on the restored live stack:

- Hermes setup smoke: ticket `613`, agent `248`, task `245`, completed at
  100%.
- Access-wall approval/resume: ticket `614`, access child `615`, original
  agent `249`, resumed agent `250`, change `176`, access granted, ticket
  resolved.
- Note steering: ticket `617`, iTop `UserRequest::398`, agent `252`, task
  `249`, dashboard and iTop steering events consumed, ticket resolved, task
  completed at 100%.
- Wazuh lease-gated access: ticket `618`, original agent `253`, resumed agent
  `254`, change `177`, Wazuh access granted, ticket resolved.
- Complex phishing plus EDR regression case: ticket `621`, iTop
  `Incident::401`, agents `256`/`257`/`258`, access request `29`, changes
  `178` and `179`, postmortem `105`, workflow `4` updated. The run validated
  requester response wait/resume, dashboard steering, iTop public_log steering,
  denied Wazuh lease, access approval/resume, containment approval/resume,
  postmortem review/promotion, and no active processes afterward. It also
  exposed unsafe direct suspicious URL retrieval behavior, so it has been
  demoted from lead demo proof and converted into a URL-safety regression case.
- Authenticated Chrome validation passed against
  `https://192.168.50.222:25443`: `demo_account_1` logged in, the curated
  `Demo Proofs` filter rendered with iTop/Demo badges, the ticket modal loaded
  the evidence trail, and no console/page/http errors remained.
- Authenticated Chrome tab sweep passed across Overview, Tickets, Intake,
  Agents, Changes, Workflows, Postmortems, CI/CD, Learning, Tools, Setup,
  Access, and Audit with no console/page/http errors.
- External demo UI reachability passed for GitLab, iTop, Keycloak, Mailcow UI,
  Roundcube route, SearXNG, and the dashboard tools API showed `15/15` modules
  healthy. The later 2026-05-19 proxy cleanup intentionally exposes the
  managed AI proxy on LAN/host port `4001`; verify it with
  `curl http://localhost:4001/health`, `POST /api/route`, or dashboard
  runner-health.
- `/favicon.ico` is now a public no-content route (`204`) so browser asset
  requests do not create noisy auth-denied `403` console warnings while UI/API
  authentication remains enforced.
- URL safety correction was deployed on 2026-05-19 after review demoted ticket
  `621`: migration `017_phishing_url_safety_guardrail.sql` updated the
  phishing RACI/workflow records, the API curl guard now blocks arbitrary
  external suspicious URL retrieval, ticket `621` received security-review note
  `2087`, and the curated `Demo Proofs` list now starts with ticket `531`.
  Real-agent regression ticket `632`, agent `259`, task `256` completed at
  `100%` after the runtime guard blocked the synthetic suspicious URL and the
  agent wrote `REGRESSION_URL_GUARD_BLOCKED`.

Source-level regression:

- `python -m pytest tests -q`: `147 passed`.
- `node --check frontend/js/dashboard.js` and
  `node --check frontend/js/agents.js`: passed.
- `python scripts/text_hygiene.py`: passed.

## Source Dry-Run Installer Verification - 2026-05-16

Purpose:

- Confirm the one-line installer now plants the dashboard, built-in AI proxy
  config, harness config, model defaults, and setup-ticket handoff without
  requiring pre-existing proxy infrastructure.
- Keep the shell/Python installer as a seed bootstrap; environment-specific
  integration work remains agentic setup-ticket work with approvals.

Commands:

```bash
python installer/bootstrap.py --dry-run --profile minimal
python installer/bootstrap.py --dry-run --profile full-it --harness hermes --proxy-mode deploy
```

Result:

- Both commands returned `status=dry_run`.
- Linux/AI-server source dry-run also returned `status=dry_run` with
  `proxy_url=http://192.168.50.222:4001`.
- The installer reported a generated `runtime/proxy_config.json`.
- The full IT dry-run selected `harness=hermes`, `proxy_mode=deploy`, provider
  `nous`, and model `deepseek/deepseek-v4-flash`.
- The dry-run setup-ticket payload included proxy mode, proxy URL, harness,
  provider, model, and agentic onboarding notes.
- Focused source tests passed:
  `PYTHONPATH=. python3 -m unittest tests.test_agent_harness
  tests.test_agentic_self_repair_marker`.
- After a no-dependency API rebuild to avoid the existing live proxy port, setup
  smoke against the live dashboard created setup ticket `570` without spawning
  an agent, and `/api/agents/processes` returned no active processes.
- Isolated proxy image build passed with `docker build -q deploy/ai-proxy`.

Follow-up clean-host acceptance remains:

- `docker compose ps` healthy for `db`, `agent-memory-db`, `ai-proxy`, and
  `api`.
- Dashboard `/health` returns `ok`.
- Proxy `/health` and `/v1/models` return configured aliases.
- `/api/agents/runner-health` shows selected harness and proxy URL.
- Setup ticket is created automatically.
- Setup agent either spawns or records a clear missing-credential/access reason.

## Full One-Line Install Verification - 2026-05-12

Fresh install target:

- Target: `/home/cereal/SOC_TESTING/soc-dashboard-install-e2e-20260512`
- Compose project: `soc-dashboard-e2e-20260512`
- Dashboard/API: `http://localhost:25482`
- PostgreSQL host port: `5435`
- AI proxy: `http://192.168.50.222:4001`
- Agent model: `qwen/qwen3.6-27b`
- iTop sync: disabled for provider-agnostic/local-only installer testing

Actual one-line installer command:

```bash
cd /home/cereal/SOC_TESTING/soc-dashboard
./install.sh \
  --profile soc \
  --source /home/cereal/SOC_TESTING/soc-dashboard \
  --target /home/cereal/SOC_TESTING/soc-dashboard-install-e2e-20260512 \
  --dashboard-port 25482 \
  --db-port 5435 \
  --project-name soc-dashboard-e2e-20260512 \
  --ai-base-url http://192.168.50.222:4001 \
  --model qwen/qwen3.6-27b \
  --itop-sync-enabled false \
  --non-interactive
```

Result:

- Installer returned `status=installed`.
- `GET /health` returned `{"status":"ok","version":"1.3.0"}`.
- `docker compose ps` showed project-scoped `api` and healthy `db` containers.
- `runner-health` reached the proxy and resolved `ps_path=/usr/bin/ps`.
- `platform_doctor.py --base http://localhost:25482` passed `18/18`.

Regression suite executed against the fresh install:

```bash
python3 scripts/platform_doctor.py --base http://localhost:25482
python3 scripts/smoke_setup_platform.py http://localhost:25482
python3 scripts/smoke_provider_adapters.py http://localhost:25482
python3 scripts/smoke_service_desk_intake.py http://localhost:25482
python3 scripts/smoke_agentic_system.py http://localhost:25482
python3 scripts/smoke_phishing_workflow_lifecycle.py http://localhost:25482
python3 scripts/smoke_cicd_security_pipeline.py http://localhost:25482
python3 scripts/smoke_agent_auditor.py http://localhost:25482
docker compose exec -T api python smoke_change_auto_completion.py http://localhost:8000
python3 scripts/smoke_local_model_agent.py http://localhost:25482 qwen/qwen3.6-27b
python3 scripts/smoke_setup_agent.py http://localhost:25482 qwen/qwen3.6-27b
```

Observed outputs:

- Setup smoke: ticket `14`.
- Provider adapters: ticket `15`, local provider `local_only`, ServiceNow/Jira fail-closed as unconfigured.
- Service desk intake: ticket `16`, change `10`, phishing intent.
- Agentic system smoke: ticket `17`, local push ticket `18`, change `11`, postmortem `5`, workflow `3`, skill `24`.
- Phishing lifecycle: ticket `19`, change `12`, workflow `2`, postmortem `6`.
- CI/CD control-plane smoke: run `7`, ticket `20`, change `13`, provider `gitlab`.
- Change auto-completion: ticket `21`, agent `9`, task `9`, change `14`, status `completed`, evidence persisted.
- Local model agent smoke: ticket `22`, agent `10`, task `10`, status `completed`, note written.
- Setup agent smoke: ticket `23`, agent `11`, task `11`, status `completed`, note written.
- `/api/agents/processes` reported no active processes after the suite.

Real installed-stack CI/CD agent workflow:

```bash
cd /home/cereal/SOC_TESTING/soc-dashboard-install-e2e-20260512
SOC_DASHBOARD_URL=http://localhost:25482 \
AGENT_MODEL=qwen/qwen3.6-27b \
CICD_DOCKER_NETWORK=host \
python3 scripts/agentic_cicd_full_demo.py \
  --base http://localhost:25482 \
  --host-ip 192.168.50.222 \
  --timeout 2400
```

Latest verified result:

```text
ticket_id=13
initial_run=5 failed high=1 medium=6 low=6 info=1 unknown=2
remediation_agent=7 task=7 completed
remediation_change=8 completed
final_run=6 passed high=0 critical=0
deployment_change=9 completed
postmortem=4 ready_for_review
mr_artifact=/home/cereal/SOC_TESTING/soc-dashboard-install-e2e-20260512/agent_work/7/agent-remediation.patch
active_agent_processes=0
```

Issues found during this fresh installer run:

- `install.sh` did not preserve executable mode after file transfer. Fixed with
  `git update-index --chmod=+x install.sh`; remote source was repaired with
  `chmod +x`.
- `agentic_cicd_full_demo.py` repaired root-owned agent workdirs by fixed
  container name. Fresh installs use custom Compose project names, so the runner
  now uses `docker compose exec -T api` from the installed root and verifies
  host writability before seeding agent workspaces.
- Local-model postmortem agents can still stall or exit without writing a
  postmortem row. The runner now synthesizes a bounded `ready_for_review`
  postmortem directly when that happens, and the demo script stops the leftover
  postmortem agent after synthesis.
- The DB-coupled change-completion smoke requires API dependencies and should
  run inside the API container for one-line/container installs.

## Scratch Install

Command shape:

```bash
python3 installer/bootstrap.py \
  --profile soc \
  --source /home/cereal/SOC_TESTING/soc-dashboard \
  --target /home/cereal/SOC_TESTING/soc-dashboard-install-e2e \
  --dashboard-port 25481 \
  --db-port 5434 \
  --project-name soc-dashboard-e2e \
  --ai-base-url http://192.168.50.222:4001 \
  --itop-sync-enabled false
```

Result:

- Fresh Docker Compose project: `soc-dashboard-e2e`.
- API: `http://localhost:25481`.
- PostgreSQL: host port `5434`.
- Health returned version `1.3.0`.
- Runner health reached the model proxy at `http://192.168.50.222:4001`.
- `install_state/last-plan.json` recorded profile `soc` with 25 modules.
- `docker compose ps` showed project-scoped containers, no fixed-name collision.

## Tests Passed

```bash
python3 scripts/smoke_setup_platform.py http://localhost:25481
python3 scripts/smoke_agentic_system.py http://localhost:25481
python3 scripts/smoke_phishing_workflow_lifecycle.py http://localhost:25481
python3 scripts/sync_reference_skills.py check --source-roots reference_skills
python3 scripts/smoke_local_model_agent.py http://localhost:25481 qwen/qwen3.6-27b
python3 scripts/smoke_setup_agent.py http://localhost:25481 qwen/qwen3.6-27b
```

Observed outputs:

- Setup smoke created setup ticket `1`.
- Agentic system smoke created ticket `2`, local provider ticket `3`, change `1`, postmortem `1`, workflow `1`, and skill `19`.
- Phishing lifecycle smoke created ticket `4`, change `2`, workflow `2`, and postmortem `2`.
- Local model agent smoke created ticket `5`, agent `1`, task `1`; task completed and wrote the expected note.
- Setup agent smoke created setup ticket `6`, agent `2`, task `2`; task completed and wrote the expected setup note.
- `/api/agents/processes` reported no active processes after model-backed tests.

## Bugs Found And Fixed

- Fixed Docker install collisions by removing fixed container names and making ports/project name environment-driven.
- Fixed fresh installs missing global skills by seeding baseline skills in both `init_db.sql` and migration `004_seed_baseline_agent_skills.sql`.
- Fixed installer upgrade behavior by applying idempotent migrations after `docker compose up`.
- Fixed skill bundle drift by adding `scripts/sync_reference_skills.py`, an allowlisted `platform/skill_sync_config.json`, and sanitized `reference_skills/`.
- Removed hardcoded test/admin password fallbacks from the Keycloak-Mailcow bridge skill before bundling.

## Remaining Notes

## 2026-05-19 Harness And Phishing Regression Addendum

Live source/runtime reconciliation verified after the setup-module work:

- Runner-health reported `harness=hermes`,
  `default_model=deepseek/deepseek-v4-flash`, and
  `AGENT_LLM_BASE_URL=http://ai-proxy:4001`.
- DB/schema/RACI defaults were reconciled by
  `018_default_hermes_external_model.sql`; auto-assignment defaults now point
  to `deepseek/deepseek-v4-flash`.
- Ticket `688` was stopped and annotated because it was launched by an old
  script path with explicit `qwen/qwen3.6-27b`.
- Ticket `689` proved the corrected DeepSeek path through URL sandbox evidence
  but exposed provider-capacity exhaustion before fallback.
- Ticket `690` passed the full URL-safe phishing/EDR workflow with user
  response, dashboard and iTop steering, Wazuh access request `31`, gates
  `181`/`182`, postmortem `106`, workflow `4` update, URL sandbox attachment
  `92`, and zero active processes after completion.
- OpenRouter fallback was added to the deployed proxy after Nous and before
  local LM Studio. Direct `openrouter/free` validation returned a tool call,
  proxy `/v1/models` advertised the OpenRouter aliases, and proxy chat for
  `deepseek/deepseek-v4-flash` successfully fell through to OpenRouter when
  the primary route was unavailable.
- Ticket `695` passed the fresh URL-safe phishing/EDR hybrid proof with
  requester/user-response evidence, steering notes, completed gates
  `185`/`186`, postmortem `107`, no direct suspicious URL fetch, and no active
  runner processes. It also exposed the terminal-proof/provider-status drift
  edge; the runner now resolves from terminal evidence and iTop close uses
  compact provider notes. A forced provider sync kept ticket `695` resolved.
- Approval audit entries for changes `181` and `182` now show the approver
  (`demo_account_1`) in summary and in `approved_by` / `approval_actor`.

## 2026-05-19 Local-First Proxy Routing Addendum

Source defaults were updated so clean installs are local/on-prem first instead
of lab-external first:

- `.env.example`, `docker-compose.yml`, `installer/bootstrap.py`, and
  `agent_models.json` now default to `AI_MODEL_ROUTE=local`,
  `AI_PROXY_MODEL_ROUTE=local`, `AI_PROXY_EXTERNAL_ENABLED=false`,
  `AGENT_DEFAULT_MODEL=local/agent-default`, and
  `HERMES_DEFAULT_PROVIDER=dashboard-proxy`.
- `installer/bootstrap.py --model-route local|external` controls the generated
  proxy routing profile. Local routes use the local gateway; external routes
  enable the configured provider and fallback chain.
- `runtime/proxy_config.json` now has an explicit `routing` section with local
  and external profiles instead of embedding a single provider assumption.
- `deploy/ai-proxy/ai_proxy.py` exposes `/api/route` for operator/debug
  visibility into provider/model/fallback resolution without exposing secrets.
- `scripts/switch_model_route.py --route local|external --restart` is the demo
  switch. It edits `.env`, `runtime/proxy_config.json`, and
  `agent_models.json`, then can rebuild/restart `ai-proxy` and `api`.
- External lab fallback order remains configurable. The lab default is Nous
  Portal -> OpenRouter -> local LM Studio, but production/government installs
  should keep external providers disabled unless explicitly approved.

Validated source checks:

```bash
python -m py_compile deploy/ai-proxy/ai_proxy.py installer/bootstrap.py api/services/agent_harness.py scripts/switch_model_route.py
python installer/bootstrap.py --dry-run --profile minimal --model-route local
python installer/bootstrap.py --dry-run --profile full-it --harness hermes --proxy-mode deploy --model-route external --provider nous --model deepseek/deepseek-v4-flash
python -m pytest tests/test_agentic_self_repair_marker.py -q
```

## Remaining Notes

The scratch E2E install is intentionally still running on `25481/5434` for inspection. It can be removed with:

```bash
cd /home/cereal/SOC_TESTING/soc-dashboard-install-e2e
docker compose down -v --remove-orphans
```
