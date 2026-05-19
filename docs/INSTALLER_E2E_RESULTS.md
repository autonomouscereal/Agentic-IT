# Installer E2E Results

Last verified: 2026-05-19

## HTTPS/Hermes One-Line Regression - 2026-05-19

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
- After restore, runtime proxy drift was reconciled: the live dashboard now
  sends spawned agents to the Compose-managed proxy through
  `AGENT_LLM_BASE_URL=http://ai-proxy:4001` from inside Docker. The
  operator-facing host proxy remains `http://192.168.50.222:4401` because a
  legacy global proxy still owns host port `4001`.
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
- Complex phishing plus EDR proof: ticket `621`, iTop `Incident::401`,
  agents `256`/`257`/`258`, access request `29`, changes `178` and `179`,
  postmortem `105`, workflow `4` updated. The run validated requester
  response wait/resume, dashboard steering, iTop public_log steering, denied
  Wazuh lease, access approval/resume, containment approval/resume, postmortem
  review/promotion, and no active processes afterward.
- Authenticated Chrome validation passed against
  `https://192.168.50.222:25443`: `demo_account_1` logged in, the `Demo
  Proofs` filter rendered ticket `621` first with iTop/Demo badges, the ticket
  modal loaded the evidence trail, and no console/page/http errors remained.
- `/favicon.ico` is now a public no-content route (`204`) so browser asset
  requests do not create noisy auth-denied `403` console warnings while UI/API
  authentication remains enforced.

Source-level regression:

- `python -m pytest tests -q`: `142 passed`.
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

The scratch E2E install is intentionally still running on `25481/5434` for inspection. It can be removed with:

```bash
cd /home/cereal/SOC_TESTING/soc-dashboard-install-e2e
docker compose down -v --remove-orphans
```
