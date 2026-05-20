# Known Issues And Fix Log

Last updated: 2026-05-20.

## Found During 2026-05-20 Ops Chat And Access RACI Work

### Long live Ops Chat agent handoff can stall on the local provider lane

Status: documented and bounded; routing/control-plane fixes completed.

The Matrix/Element Ops Chat smoke created tickets and queued real Hermes agents.
The no-spawn smoke accidentally allowed a follow-up continuation agent, and the
real-spawn smoke then queued behind it. After stopping only those test agents,
the control plane was clean, but the real Hermes/local-model agent showed no
ticket notes or checkpoint progress after starting.

Fixes completed:

- `scripts/smoke_ops_chat.py` now passes `spawn_agent` on follow-up messages so
  `OPS_CHAT_SMOKE_SPAWN_AGENT=false` truly stays control-plane only.
- Account-lockout wording is now seeded into RACI keywords so chat requests like
  "cannot log into my account" route to Identity & Access instead of the
  generic Business Applications queue.
- Live demo guidance now treats long Ops Chat agent runs as provider-sensitive:
  use completed proof tickets for full workflows and keep live chat requests
  small until provider/harness reliability is hardened further.

Verification:

- Global search smoke passed on ticket `722`.
- Ops Chat no-spawn smoke passed on ticket `723`.
- Ops Chat real-spawn smoke created ticket `724` and spawned agent `279`.

## Found During 2026-05-19 Agentic Regression Push

### AI server briefly had two proxy ports, 4001 and 4401

Status: fixed on 2026-05-19. Host `4001` is again the single canonical proxy
port, and host `4401` is gone.

During route-profile work, the live Compose-managed proxy was temporarily moved
to host `127.0.0.1:4401` while an older standalone `ai-proxy` container owned
host `0.0.0.0:4001`. That created two different proxy surfaces:

- Agents used `AGENT_LLM_BASE_URL=http://ai-proxy:4001` inside Docker, which
  reached the Compose-managed proxy.
- External tools using `http://192.168.50.222:4001` reached the older
  standalone proxy, which had a minimal `/health` response and no `/api/route`.

Fix:

- Removed the standalone `ai-proxy` container.
- Set the live Compose deployment to `AI_PROXY_BIND=0.0.0.0` and
  `AI_PROXY_PORT=4001`.
- Kept `AGENT_LLM_BASE_URL=http://ai-proxy:4001` for API/agent containers.
- Kept source defaults local-first while leaving this lab environment on
  `AI_MODEL_ROUTE=external` for the current demo.
- Deleted the attempted `legacy_forwarder.py` source artifact.

Verification:

- `ss -ltnp` showed only `0.0.0.0:4001`; no listener remained on `4401`.
- `docker ps` showed only `soc-dashboard-ai-proxy-1` mapped
  `0.0.0.0:4001->4001/tcp`.
- Host `http://127.0.0.1:4001/health`, LAN
  `http://192.168.50.222:4001/api/route`, and API-container
  `http://ai-proxy:4001/api/route` all returned the managed proxy routing
  profile.
- `POST /api/route` for `deepseek/deepseek-v4-flash` returned
  `nous -> openrouter -> lmstudio`.
- Runner health reported Hermes,
  `effective_anthropic_base_url=http://ai-proxy:4001`, default model
  `deepseek/deepseek-v4-flash`, and model API status `ok`.

### Proxy source default was lab-external instead of local/on-prem first

Status: fixed in source.

The live lab needed Nous/OpenRouter for speed during demo preparation, but the
source installer and proxy examples started to read as if external providers
were the product default. That is the wrong posture for most production,
government, and private deployments, where model routing should stay local or
on-prem unless an external route is explicitly approved.

Fix:

- Add `AI_MODEL_ROUTE` / `AI_PROXY_MODEL_ROUTE` profiles with local as the
  default.
- Keep `AI_PROXY_EXTERNAL_ENABLED=false` by default.
- Default `AGENT_DEFAULT_MODEL` to `local/agent-default` and
  `HERMES_DEFAULT_PROVIDER` to `dashboard-proxy`.
- Generate `runtime/proxy_config.json` with explicit local and external
  profiles.
- Add `scripts/switch_model_route.py --route local|external` as the demo-safe
  route toggle.
- Document external Nous/OpenRouter as lab/demo routes only, with all provider
  secrets supplied by runtime vault/environment.

### Ticket evidence sequence was technically complete but hard to follow

Status: fixed in source and live deployment.

The ticket modal had all of the right primitives: notes, tasks, gates,
postmortems, and audit rows. But the audience-facing view grouped them by
object type and showed recent notes/audit in reverse order. On complex tickets
such as `695`, that made the work look out of order and made provider recovery
notes feel wacky even when the underlying timestamps were correct.

Fix:

- Add `model_turn_events` to ticket context by following the ticket's agent
  task IDs, so model turns tied to `task_###` show up on the ticket.
- Include `ticket_id` in new model-turn audit/event details for future runs.
- Render a chronological `Sequence of Events` in the ticket modal before the
  raw detail sections.
- Deduplicate audit/event model-turn pairs and keep broad raw audit rows out
  of the main human narrative.
- Split long marker notes into a short title plus readable body text.
- Shorten future terminal-evidence recovery notes while preserving full audit
  evidence.

Verification:

- Live ticket `695` context returns notes, tasks, gates, steering events,
  postmortem evidence, and deduped model-turn events.
- Playwright opened ticket `695` in the live dashboard and confirmed
  `Sequence of Events`, model-turn rows, and final resolution evidence render.

### Setup page needed incremental per-module work controls

Status: fixed in source and live deployment.

The setup flow could create a parent setup ticket and child tickets for a full
profile, but operators still had to manipulate the whole on/off plan when they
only wanted to work one module, add a module-specific note, or tear down a
deployed reference module.

Fix:

- Add inferred per-module deployment status from tool inventory and built-in
  dashboard module knowledge.
- Add `Keep active` planning state so healthy/built-in modules do not get
  redeployed by default.
- Add per-module notes fields in the Setup UI.
- Add one-module ticket creation through `POST /api/setup/module-ticket`.
- Add undeploy/reinstall ticket actions with teardown guardrails and approval
  requirements.

### API/agent runtime had Playwright CLI but no browser binaries

Status: fixed in source and live deployment.

While preparing the URL-safe 621/531 hybrid real-agent proof, the live API
container showed `npx playwright --version` working, but launching Chromium
failed because the browser binary was missing from `/root/.cache/ms-playwright`.
That means agents could appear to have browser automation capability while
failing at the first real UI validation.

After installing Playwright, live verification exposed a second runtime issue:
the global npm package was installed, but `node -e "require('playwright')"`
could not resolve it because `NODE_PATH` did not include the global npm module
directory.

Fix:

- Install a pinned Playwright CLI/package and Chromium browser dependencies in
  the API image.
- Set `NODE_PATH=/usr/lib/node_modules` so small agent-written Node
  scripts can `require('playwright')` without local npm initialization.
- Add stable agent context that explains when browser validation is appropriate
  and keeps suspicious URL analysis on sandbox/reputation paths, not direct
  browsing.
- Expand default agent tool allowlists for local browser validation commands
  while keeping secrets and unsafe target retrieval guarded.

Live verification:

- API image rebuilt on 2026-05-19.
- Inside the live API/agent container,
  `node -e "require('playwright')"` launched Chromium and read
  `PLAYWRIGHT_AGENT_OK`.

### Complex proof script defaulted to local qwen instead of Hermes external model

Status: fixed in source and superseded on live ticket `688`.

The URL-safe 621/531 hybrid proof was launched with an explicit
`qwen/qwen3.6-27b` argument, which forced Hermes to use the local
`dashboard-proxy` provider route even though the platform default is Hermes
plus `deepseek/deepseek-v4-flash` through the external Nous route. Runner
health showed `AGENT_HARNESS=hermes`, `AGENT_LLM_BASE_URL=http://ai-proxy:4001`,
and `default_model=deepseek/deepseek-v4-flash`; the local model usage came from
test/script defaults and older DB seed defaults, not from a hidden runner
fallback.

Fix:

- Stop only the superseded test-lane agent on ticket `688` and record an
  internal note explaining the model-routing reason.
- Change agentic proof/demo script defaults to `deepseek/deepseek-v4-flash`.
- Change source DB/schema/RACI defaults to `deepseek/deepseek-v4-flash`.
- Add migration `018_default_hermes_external_model.sql` to reconcile live
  defaults for fresh and existing deployments while leaving qwen aliases
  available for explicit local-model tests.

### External DeepSeek 503 exhausted retries without local fallback

Status: fixed in source and live proxy route verified on 2026-05-19.

Fresh ticket `689` proved the corrected Hermes external default model path with
`deepseek/deepseek-v4-flash` and reached requester response, dashboard
steering, iTop steering, URL sandbox evidence, and permission-wall notes.
However, the external provider returned repeated HTTP `503` capacity errors
after the URL sandbox evidence. The runner retried the same external model, but
after exhausting retries it failed the task instead of continuing on the
configured local fallback model.

Fix:

- Add `AGENT_TRANSIENT_MODEL_FALLBACK_ENABLED` and
  `AGENT_TRANSIENT_MODEL_FALLBACK_MODEL`.
- Keep the preferred behavior as external model first with bounded transient
  retries.
- After retries are exhausted, update the agent `selected_model` to the local
  fallback, preserve workspace progress, queue the same task, add a ticket note,
  and emit `agent_transient_model_fallback_scheduled`.
- Keep local qwen usage visible and explicit in the audit/ticket trail instead
  of hiding it as an unexplained model switch.
- Add OpenRouter as the first external proxy fallback after Nous and before
  local LM Studio. The validated fallback alias is `openrouter/free`; the
  provider key is runtime/vault-only.

Verification:

- Direct OpenRouter `openrouter/free` returned a tool-call response.
- Proxy `/v1/models` advertised Nous, OpenRouter, and LM Studio aliases.
- Proxy chat for `deepseek/deepseek-v4-flash` successfully fell through to
  OpenRouter when the primary route was unavailable.

### Terminal proof completed but provider ticket stayed open

Status: fixed in source and live-recovered on 2026-05-19.

Ticket `695` completed the URL-safe phishing/EDR hybrid flow with completed
approval gates and a postmortem, but the external provider ticket remained
open after the harness missed the final explicit ticket-close call. A first
supervisor recovery attempt then proved a second issue: iTop rejected the
provider-close payload because one transition field was limited to 255
characters.

Fix:

- Allow terminal evidence recovery when there is postmortem evidence even if
  the postmortem is still `ready_for_review`.
- Resolve the local dashboard ticket from persisted terminal evidence only
  when all gates are complete, final notes exist, and no open change gates
  remain.
- Close iTop with compact provider notes while preserving full evidence in the
  dashboard notes and audit log.
- Replace raw provider traceback-style ticket notes with short operator
  summaries; raw adapter detail remains in audit/provider error fields.

Verification:

- Ticket `695` was recovered to dashboard status `resolved`.
- Forced iTop sync kept provider status `resolved`.
- The cleaned ticket notes now describe the adapter issue and recovery without
  exposing long raw provider traces in the demo view.

### Compose rebuild can leave duplicate API container names after interrupted deploys

Status: discovered during Playwright runtime deployment; live cleanup in
progress.

While rebuilding the API image with Playwright support, Docker built the image
successfully but failed to recreate the API container because a duplicate
Compose-generated API container name was already reserved by another container.

Fix:

- Inspect `docker ps -a` for the exact conflicting API containers before taking
  action.
- Remove only stopped/stale duplicate API containers that belong to the
  dashboard Compose project.
- Re-run `docker compose up -d api` and verify health before continuing.

### Ticket 621 contained unsafe direct suspicious URL retrieval

Status: fixed in source and deployed to the live AI server on 2026-05-19.

Demo review found that ticket `621` included agent evidence where a suspicious
URL was handled with direct retrieval semantics. That is not acceptable for a
phishing or malware workflow: agents must not browse, curl, wget, screenshot,
or otherwise fetch suspicious URLs from the runner, dashboard host, user
workstation, or production network.

Root cause:

- Prompt guidance correctly encouraged dashboard API `curl` usage, but did not
  explicitly distinguish trusted dashboard/internal URLs from hostile URLs
  found in tickets, email, SIEM, or EDR evidence.
- The per-agent curl guard blocked broad dashboard pulls, but did not block
  arbitrary external URL retrieval.
- The active phishing RACI/workflow prompt did not encode URL detonation safety
  as a negative test.

Fix:

- Add a Suspicious URL handling rule to ticket, auto-assignment, postmortem,
  and workflow prompts.
- Add per-agent/runtime curl guard host allowlisting. Dashboard/internal URLs
  and approved reputation/sandbox providers are allowed; arbitrary external
  URLs are blocked with a clear remediation message.
- Update the phishing RACI rule and canonical phishing workflow migration so
  passive evidence, reputation adapters, and approved isolated detonation are
  the only valid analysis paths.
- Remove ticket `621` from the curated `Demo Proofs` ordering and document it
  as a regression case, not the lead demo proof.

Verification:

- Source regression passed with `147 passed`.
- Live migration `017_phishing_url_safety_guardrail.sql` updated the phishing
  RACI rule and canonical phishing workflow records.
- Live API health, proxy `/v1/models`, runner-health, and agent process checks
  passed after rebuild.
- Live API-container curl guard test returned `65` for
  `http://training-login.example.invalid/reset` and allowed the configured
  VirusTotal reputation host.
- Ticket `621` now has internal security-review note `2087` explaining the
  demotion and the new guardrail.
- Real Hermes/local-model agent regression passed on ticket `632`, agent
  `259`, task `256`: the agent attempted the single guarded curl test against
  the synthetic `.example.invalid` URL, the guard blocked it, the agent wrote a
  `REGRESSION_URL_GUARD_BLOCKED` note, wrote zero failure notes, completed at
  `100%`, and left no active processes.

Safe alternatives:

- email headers and authentication results
- mail-gateway, DNS, proxy, firewall, and Wazuh/SIEM evidence
- URL/domain parsing and known-safe internal allowlists
- VirusTotal/urlscan/ANY.RUN-style provider adapters when configured
- approved isolated detonation infrastructure

Important rule: approval to block, quarantine, or contain a URL is not approval
to fetch that URL.

### Smoke scripts must not shell-source the full live `.env`

Status: fixed in setup smoke flow; use selective env parsing for live checks.

During the setup-ticket fan-out live smoke, sourcing the full live `.env`
failed because `AGENT_ALLOWED_TOOLS` legitimately contains parentheses and
wildcards for harness allowlists. The shell stopped before auth variables were
loaded, and the hardened API correctly returned `403 access_denied`.

Fix:

- Do not `set -a; . ./.env` for smoke scripts against hardened deployments.
- Load only the needed auth variables, such as `DASHBOARD_SERVICE_TOKEN` and
  `DASHBOARD_TRUSTED_AUTH_SECRET`, using a parser that treats each line as
  config data instead of shell code.
- `scripts/smoke_setup_platform.py` now accepts the standard dashboard service
  token or trusted proxy headers from environment, matching the hardened auth
  posture.

### Curl guard path parser rejected explicit list inputs

Status: fixed in source and covered by regression tests.

The full test suite exposed that `_split_guard_paths` in the agent runner only
handled comma-separated strings. The curl guard builder also accepts explicit
lists for tests and internal callers, so a list of allowed hosts raised
`AttributeError: 'list' object has no attribute 'split'` before the guard could
be written.

Fix:

- Allow `_split_guard_paths` to normalize lists, tuples, and sets as well as
  comma-separated strings.
- Keep empty values filtered and all values string-trimmed before writing guard
  rules.

### Hermes/N Nous 503 capacity failure can interrupt a valid in-progress task

Status: fixed in source; live deployment patch/verification in progress.

During the real note-steering proof, Hermes using
`deepseek/deepseek-v4-flash` through Nous completed the dashboard steering
half of the task, wrote valid notes, advanced the checkpoint to 55%, then the
provider returned:

`HTTP 503: The requested model is temporarily unavailable due to upstream capacity limits.`

Observed evidence:

- Ticket `616`, agent `251`, task `248`.
- Marker `NOTE_STEERING_1779162432`.
- The task had already written `STEERING_READY_DASHBOARD` and
  `STEERING_OBSERVED_DASHBOARD`.
- The runner marked the task failed immediately instead of scheduling a
  transient provider retry/resume.

Fix:

- Add transient model-capacity detection in the agent runner for Hermes/proxy
  provider failures such as HTTP `429`, `500`, `502`, `503`, `504`, upstream
  capacity, temporarily unavailable, and rate-limit messages.
- Requeue the same agent task after a configurable delay while preserving the
  workspace, checkpoint, steering inbox, notes, and task evidence.
- Limit retries with `AGENT_TRANSIENT_MODEL_RETRY_MAX` and
  `AGENT_TRANSIENT_MODEL_RETRY_DELAY_SECONDS` so a bad provider cannot loop
  forever.

Follow-up verification:

- Re-run `scripts/agentic_note_steering_demo.py` after the runner patch is
  deployed.

## Fixed During 2026-05-18 Demo Credential Prep

### Mailcow admin UI still has missing tables, invalid JSON popups, and broken tabs

Status: fixed on live AI server and bundled deployer.

Reported on 2026-05-18 after the first Mailcow UI cleanup. The admin UI can
render after login, but several pages still show database exceptions, blank
content, log warnings, and DataTables invalid JSON popups.

Observed symptoms:

- `mailcow.templates` missing from `/web/inc/functions.mailbox.inc.php` through
  `/web/admin/system.php`.
- A blank page still appears on at least one Mailcow page.
- Log-related UI surfaces show many warnings/errors.
- JSON popups occur for mailboxes, TLS policy maps, address rewriting, routing,
  and related tables.
- Webmail needed a real mailbox client instead of the earlier custom demo
  surface.
- The UI exposes a Keycloak/identity-provider integration area, but it may not
  be configured through Mailcow's own UI data model.

Root causes:

- The custom Mailcow database was missing current stock-UI tables:
  `templates`, `relayhosts`, `bcc_maps`, and `tls_policy_override`.
- The custom seed had only catch-all aliases, so mail sent to
  `demo_account_1@mailcow.local` landed in `postmaster@mailcow.local` instead
  of the demo mailbox.
- The upstream SOGo container was not viable in this custom stack because it
  lacked the expected MySQL socket/web-root bootstrap context and generated
  noisy wait-loop logs.
- The Mailcow Identity Provider tab had no durable Keycloak configuration in
  Mailcow's own `identity_provider` table.

Fix:

- Extended `deploy_mailcow_api.py` to create/repair `templates`,
  `relayhosts`, `bcc_maps`, `tls_policy_override`, and default domain/mailbox
  templates.
- Seeded Mailcow's `identity_provider` table for Keycloak while preserving the
  existing client secret and never printing it.
- Added direct delivery aliases for every active user mailbox so local SMTP
  demo mail reaches the mailbox being shown.
- Deployed `roundcube-mailcow-demo` on loopback port `2582`, proxied `/webmail`
  to Roundcube, and redirected `/SOGo/*` to `/webmail/`.
- Added a Roundcube `report_phish` plugin plus hidden `/demo-report` endpoint
  so the polished webmail client still creates Mailcow quarantine evidence and
  Agentic Operations intake tickets.
- Put upstream SOGo into `SKIP_SOGO=y` sleep mode on the live lab because
  Roundcube now provides the browser webmail surface without SOGo log spam.

Verification:

- `python3 scripts/deploy_mailcow_api.py`: PASS.
- `python3 scripts/test_mailcow_api_shim.py --mysql-parity`: `13 passed, 0 failed`.
- PHP lint: `mailcow_compat_api.php`, `mailcow_demo_report.php`, and the
  Roundcube `report_phish` plugin have no syntax errors.
- Browser and HTTP login checks for `/webmail` as
  `demo_account_1@mailcow.local` work with the vault password, render the
  Roundcube inbox, and show a human-readable `Report Phish` toolbar button.
- Report Phish created dashboard ticket `578`, iTop Incident `370`, approval
  gate `167`, replacement Hermes/deepseek agent `227`, and Mailcow quarantine
  row `28cd6d435f7c88cd9a7b46983c62a1cb`.
- Roundcube Report Phish created dashboard ticket `580`, iTop Incident `372`,
  agent `229`, follow-up access request `581`, and Mailcow quarantine row
  `21a705b151642568d375c748a9ea1a6b`.
- Mailcow `/quarantine` visibly lists the quarantine id, subject, sender, and
  recipient with no invalid JSON or SQL banners.
- Agent `227` completed the approved gate and resolved ticket `578` with
  checkpoint status `done` and progress `100`.

### Mailcow admin UI loads but shows JSON/SQL warning banners

Status: fixed on live AI server and bundled deployer.

Reported on 2026-05-18 after stale-session recovery made the Mailcow admin UI
visible again. The page renders, but the browser shows UI warnings, invalid JSON
popups, and invalid-column errors from dashboard widgets/API calls.

Investigation checklist:

- Capture browser dialogs, console errors, and failed/invalid JSON responses
  after admin login.
- Inspect `nginx-mailcow-api` and `php-fpm-mailcow-api` logs during page load.
- Identify whether the broken responses are stock `json_api.php` calls, custom
  compatibility shim responses, or SQL/schema drift in the custom Mailcow seed.
- Patch the deployer so fixes survive sidecar redeploys.
- Re-run browser login with dialog/network capture and the shim deployer tests.

Root cause:

- The custom Mailcow seed was missing current UI compatibility tables/columns:
  `fido2.credentialId`, `settingsmap`, and `templates`.
- Stock `json_api.php` returned empty bodies for UI table routes such as
  `POST /api/v1/search/domain` and `GET /api/v1/get/quarantine/all`, causing
  DataTables invalid JSON dialogs.
- The Mailcow JavaScript expected native domain-search field names; a first
  compatibility response was valid JSON but lacked those fields, producing
  `undefined` and `NaN` display text.
- Upstream SOGo is intentionally not the demo browser surface in this custom
  stack; `/SOGo/*` now redirects to Roundcube.

Fix:

- Extended the Mailcow shim deployer to create/repair `fido2`, `settingsmap`,
  and `templates`.
- Added compatibility JSON handlers for domain search, quarantine inventory,
  and empty domain/mailbox template lists.
- Allowed authenticated same-origin UI reads through the compatibility shim
  while preserving API-key enforcement for unauthenticated external reads.
- Set lab quarantine Redis defaults so the quarantine-disabled banner is not
  shown during demos.
- Routed `/SOGo/*` to the Roundcube webmail surface after the webmail/report
  phish demo was upgraded; earlier cleanup routed it to `/admin/dashboard`.

Verification:

- `python3 scripts/deploy_mailcow_api.py` passes, including stale-session,
  table JSON, template JSON, and Roundcube webmail route checks.
- Browser crawl of `/admin/dashboard`, `/admin/system`, `/admin/mailbox`,
  `/admin/queue`, `/quarantine`, `/webmail`, and `/SOGo/so` shows no invalid
  JSON dialogs or SQL warning alerts. The only crawler text hit containing
  "error" is static queue help copy explaining mail-delivery error messages,
  not a UI failure.

### Wazuh Dashboard worked while native Wazuh API auth returned 401

Status: fixed on live AI server 2026-05-18.

Earlier live credential smoke showed:

- Wazuh Dashboard login endpoint for `demo_account_1`: HTTP 200.
- Native Wazuh API `/security/user/authenticate?raw=true` for the same user:
  HTTP 401.

The Wazuh UI and the Wazuh API use different auth layers and can drift
independently. The demo account has now been re-applied to both layers; latest
smoke verifies browser Dashboard login and native API token issuance.

Verification:

- Wazuh API auth for `demo_account_1`: PASS, token issued.
- Wazuh Dashboard browser login for `demo_account_1`: PASS.

### GitLab demo login returned 422 and Keycloak OIDC could not reach Keycloak

Status: fixed on live AI server and documented in reference skills.

Symptoms:

- Local GitLab login for `demo_account_1` returned GitLab's generic 422 page.
- The Keycloak login button failed with
  `Failed to open tcp connection to keycloak.internal:8443`.

Root causes:

- The GitLab container resolved `keycloak.internal` to its own localhost
  instead of the host-network Keycloak nginx proxy.
- After the network route was fixed, GitLab needed the Keycloak proxy CA in its
  trusted cert store.
- The `demo_account_1` GitLab user existed and the password was valid, but the
  user was missing its required personal namespace.

Fix:

- Added `extra_hosts: ["keycloak.internal:host-gateway"]` to the live GitLab
  compose service and the portable reference skill compose template.
- Copied the Keycloak integration CA into
  `/etc/gitlab/trusted-certs/keycloak-internal-ca.crt` and ran
  `gitlab-ctl reconfigure`.
- Created the missing GitLab personal namespace for `demo_account_1` with the
  GitLab Rails model layer.

Verification:

- GitLab health: `healthy`.
- Fresh local login POST for `demo_account_1`: HTTP 302, not 422.
- GitLab container can fetch the OIDC discovery document from
  `https://keycloak.internal:8443/realms/gitlab/.well-known/openid-configuration`.
- OmniAuth start POST redirects to the Keycloak realm authorization endpoint.

Follow-up fixes on 2026-05-18:

- Keycloak Admin Console was failing from normal demo browsers with
  `Timeout when waiting for 3rd party check iframe message` because the realm
  advertised `keycloak.internal` while the browser opened
  `192.168.50.222`.
- The live Keycloak hostname was moved to the browser-routable full URL
  `https://192.168.50.222:8443`, with the Admin Console using the same URL.
- GitLab OmniAuth was updated to the matching issuer
  `https://192.168.50.222:8443/realms/gitlab`, and the exposed historical OIDC
  client secret was rotated.
- Browser-based GitLab SSO and the Keycloak Admin Console no longer require a
  workstation hosts-file entry. The `keycloak.internal` route is retained only
  as an internal compatibility alias where needed.
- A later full SSO test still failed with GitLab OmniAuth `Unknown error`.
  Keycloak logs showed a token claim mapping error. The GitLab realm mappers
  were corrected to emit simple `preferred_username`, `groups`, and
  `realm_roles` claims, `setup_oidc.py` now updates existing mappers in place,
  and the existing GitLab local user is linked to the Keycloak subject.
- Full Playwright SSO as `demo_account_1` now lands in GitLab as SOC Demo
  Account with Projects/Admin visible.

### Mailcow demo UI was not exposed and schema drift blocked login

Status: fixed on live AI server and documented in the Mailcow skills.

Symptoms:

- The reference Mailcow deployment was usable through direct MySQL and SMTP/IMAP
  paths, but there was no browser-friendly UI URL for demos.
- The optional API sidecar initially returned a blank or failed UI because the
  mounted web root could not write Twig cache files and `dockerapi` was not
  resolvable from the php-fpm sidecar.
- After the UI loaded, admin login hit custom-schema drift: missing `logs`,
  legacy `tfa(id,data)` shape without `key_id`, and an ambiguous `kind` query.
- A first route repair briefly exposed PHP source for extensionless routes; this
  was immediately replaced with a named FastCGI rewrite.

Fix:

- Exposed the demo UI on `http://192.168.50.222:2581` while keeping the
  read-only compatibility API on `8081`.
- Mounted the web root writable for the php-fpm sidecar so Twig cache can be
  generated.
- Added the `dockerapi:127.0.0.1` sidecar host mapping and kept raw dockerapi
  access blocked from non-loopback traffic with the host firewall rule.
- Created the missing `logs` table, repaired `tfa`, added
  `mailbox.authsource`, and patched Mailcow UI queries to use `mailbox.kind`.
- Replaced unsafe `try_files $uri.php` behavior with a named rewrite that
  re-enters the FastCGI `.php` location.
- Rotated the Mailcow demo admin/mailbox hashes to the shared vault password
  using no-BOM secret handling.

Verification:

- `http://192.168.50.222:2581/` returns the Mailcow login page.
- Admin form login for `demo_account_1` returns HTTP `302` to
  `/admin/dashboard`.
- `/admin/dashboard` renders through FastCGI and does not expose PHP source.
- IMAP auth for `demo_account_1@mailcow.local` returns `OK`.


### Mailcow demo UI renders incorrectly and post-login page is blank

Status: fixed on live AI server and bundled deployer.

Reported on 2026-05-18 after the Mailcow demo UI was exposed on `:2581`.
The login page is reachable, but the browser-rendered UI is not rendering
correctly and the page after login appears blank. Treat this as a demo blocker
until the shim is verified with real browser asset loading, not only curl-level
HTTP status checks.

Investigation checklist:

- Verify CSS, JS, font, and image asset routes from `nginx-mailcow-api`.
- Verify extensionless PHP route handling does not skip FastCGI execution.
- Verify authenticated `/admin/dashboard` HTML includes complete layout output,
  not partial PHP output or an exception body.
- Verify browser console/network errors with a real browser or equivalent asset
  fetch sweep.
- Update the Mailcow shim deployer/docs after the fix so redeploys preserve it.

Root cause:

- Mailcow generated `/cache/<hash>.css` and `/cache/<hash>.js` URLs, but the
  split php-fpm/nginx sidecar deployment wrote minified assets to the php-fpm
  container's `/tmp`. The nginx sidecar served `/cache` from the mounted web
  root, so the generated CSS/JS returned 404.

Fix:

- Created and permissioned `/home/cereal/mailcow-dockerized/data/web/cache`.
- Patched `inc/header.inc.php` and `inc/footer.inc.php` in the reference shim to
  write generated CSS/JS to `/web/cache`.
- Updated the shim deployer startup script to create/chown `/web/cache` and
  clear stale generated assets on redeploy.
- Extended the deployer UI smoke to fetch `/cache` CSS/JS refs.

Verification:

- Deployer passes API regression and demo UI cache-asset smoke.
- Browser login reaches `http://192.168.50.222:2581/admin/dashboard`.
- Headless browser check reports visible dashboard text, `0` login inputs,
  `0` failed network requests, and `0` console errors.


### Mailcow authenticated dashboard still blank in interactive browser

Status: fixed on live AI server and bundled deployer.

Reported on 2026-05-18 after the cache asset repair. The login page renders,
but after successful login the interactive browser view is blank. Previous
headless checks saw HTML and no failed asset requests, so this needs a deeper
check of authenticated dashboard JavaScript, API/XHR calls, CSS visibility, and
browser-specific rendering state.

Investigation checklist:

- Capture an authenticated dashboard screenshot and pixel/DOM evidence.
- Inspect dashboard JS/XHR calls after login.
- Check whether body content exists but is hidden by CSS/overlay/theme state.
- Check `/api/v1/*`, `/json_api.php`, docker/status, and dashboard widgets that
  run after page load.
- Patch the shim/deployer/docs once the browser-visible blank page is fixed.

Root cause:

- The first asset-cache repair made generated CSS/JS available, but the generated
  URLs were stable (`/cache/<hash>.css` and `/cache/<hash>.js`). Browsers that
  had already loaded the broken/404 assets could keep a stale blank/unstyled
  dashboard state.

Fix:

- Appended `?v=<filemtime>` to generated Mailcow CSS/JS cache URLs in
  `header.inc.php` and `footer.inc.php`.
- Added `Cache-Control: no-store, no-cache, must-revalidate` for `/cache/*` in
  the nginx sidecar config.
- Re-ran the deployer after updating the bundled source to prove the fix
  survives sidecar redeploys.

Verification:

- Authenticated dashboard HTML now references versioned generated assets.
- `/cache/*.css?v=...` and `/cache/*.js?v=...` return HTTP `200` and no-store
  cache headers.
- Headless browser login to `/admin/dashboard` shows visible dashboard text,
  zero login inputs, zero failed network requests, and zero console errors.


### Mailcow root login flow still lands on blank user page

Status: fixed on live AI server and bundled deployer.

Reported on 2026-05-18 after the admin dashboard/cache fixes. Multiple browsers
with cleared cache still show a blank page after login. This likely affects the
root `/` user login flow rather than the `/admin/` admin login flow that was
previously validated.

Root cause:

- The bare `/` URL hit Mailcow's root user-login flow in this custom sidecar
  deployment. That path returned a tiny blank response after form submit, while
  the verified admin flow at `/admin/` worked correctly.
- Demo operators naturally open `http://192.168.50.222:2581/`, so the blank
  root flow looked like the whole Mailcow UI was still broken.
- A stale Mailcow user-session cookie (`MCSESSID`) made `/` and `/admin/`
  redirect back to `/user`; nginx logged those user-flow responses as HTTP 200
  with a 5-byte body.

Fix:

- Routed exact `/` in the nginx sidecar to the Mailcow admin login page through
  FastCGI by setting `SCRIPT_FILENAME` to `/web/admin/index.php` and
  `REQUEST_URI` to `/admin/`, with incoming cookies stripped on the login
  entrypoint.
- Routed exact `/admin/` the same way so stale user sessions cannot redirect
  the admin login page back to `/user`.
- Added exact `/user` and `/user/` handlers that clear both `PHPSESSID` and
  `MCSESSID` and redirect to `/`.
- Added the same route to `scripts/deploy_mailcow_api.py` so a shim redeploy
  preserves the behavior.
- Redeployed only the Mailcow API/UI sidecars.

Verification:

- Re-running `python3 scripts/deploy_mailcow_api.py` succeeds.
- Browser login from `http://192.168.50.222:2581/` redirects to
  `http://192.168.50.222:2581/admin/dashboard`.
- Headless browser evidence shows visible dashboard text, versioned CSS/JS
  loaded from `/cache`, zero failed requests, and zero console errors.
- The deployer now checks stale-session recovery: root with an existing
  `MCSESSID` still returns the admin login, and `/user` recovers back to the
  admin login instead of serving the blank user page.

## Found During 2026-05-18 Documentation Refresh

### Live AI server has standalone proxy owning port 4001

Status: resolved on 2026-05-19; the Compose-managed proxy now owns host
`0.0.0.0:4001`.

During the documentation refresh deploy, `docker compose up -d --build api`
attempted to create the Compose-managed `soc-dashboard-ai-proxy-1`, but host
port `4001` was already bound by the pre-existing standalone `ai-proxy`
container. The API was safely restored with `docker compose up -d --no-deps api`
after confirming no active agents or runner processes were present. Runner
health then returned `harness=hermes`, default model
`deepseek/deepseek-v4-flash`, and model API status `ok` through the existing
proxy.

Resolution:

- Stopped and removed the standalone `ai-proxy` container.
- Set the live deployment to `AI_PROXY_BIND=0.0.0.0` and
  `AI_PROXY_PORT=4001`.
- Restarted the Compose-managed `soc-dashboard-ai-proxy-1` and verified only
  `0.0.0.0:4001` was listening; host `4401` was not listening.
- Verified `/health`, `/api/route`, and runner-health through the managed
  proxy.

### Reference skill bundle has unrelated source drift

Status: known issue, not fixed in this documentation pass.

`python scripts/sync_reference_skills.py check --source-roots "C:/Users/cereal/.agents/skills"`
currently reports drift for:

- `ai-proxy`
- `login-troubleshooting`
- `platform-credentials`

The documentation refresh updated selected skill text in both the live
`.agents` skill tree and the portable `reference_skills/` bundle, but did not
run a full `stage` because that would pull unrelated skill changes into the
documentation commit. Before the next skill-release commit, review those three
skills intentionally, decide whether the live skill or bundled skill is the
source of truth, then run `sync_reference_skills.py stage` and commit the
resulting bundle/manifest together.

## Found In Hermes Harness Bring-Up

### Text hygiene still detects mojibake in two reference skills

Status: fixed on 2026-05-15 during Hermes verification.

Problem:

`python scripts/text_hygiene.py` fails on
`reference_skills/login-troubleshooting/SKILL.md` and
`reference_skills/platform-credentials/SKILL.md` due mojibake arrow and dash
markers.

Impact:

This blocks the full hygiene verification command even though the Hermes
harness files compile and focused tests pass.

Fix:

Normalized the affected reference skill text without changing its operational
meaning.

### Hermes was host-installed but not visible inside the dashboard API container

Status: fixed in source and deployed on 2026-05-15; live queue validation in
progress.

Problem:

Hermes Agent was installed on the AI server at `/home/cereal/.hermes`, and host
oneshot tests worked with both Nous Portal `deepseek/deepseek-v4-flash` and the
local LM Studio custom provider. The dashboard API container could not see the
`hermes` binary or Hermes home, so `AGENT_HARNESS=hermes` could not spawn from
the queue.

Impact:

The system could only invoke Claude Code from the dashboard queue even though
Hermes was correctly installed and authenticated on the host.

Fix:

- Added a `hermes` harness in `api/services/agent_harness.py`.
- Mounted `HERMES_HOME_DIR` into the API container at `/home/cereal/.hermes`.
- Mounted `HERMES_UV_PYTHON_DIR` into the API container because the host Hermes
  venv points at uv-managed Python under `/home/cereal/.local/share/uv`.
- Added `HERMES_BIN`, provider, toolset, and max-turn environment variables.
- Added `HERMES_RUN_AS_UID/GID=1000` so Hermes subprocesses run as the Hermes
  owner instead of API-container root.
- The runner now writes both `AGENTS.md` and `.claude/CLAUDE.md` into workdirs.
- Runner health now reports Hermes binary/config/Nous auth status.

### AI proxy only handled Anthropic Messages traffic

Status: fixed in source on 2026-05-15; live proxy update and route validation
required.

Problem:

Claude Code uses `/v1/messages`, but Hermes uses OpenAI-compatible
`/v1/chat/completions` for custom providers such as the dashboard proxy. The
live `ai-proxy` only exposed `/v1/messages`, so Hermes could not use the proxy
for both local and Nous Portal routes.

Fix:

Added `deploy/ai-proxy/ai_proxy.py` with both `/v1/messages` and
`/v1/chat/completions` support. `deepseek/deepseek-v4-flash` routes to Nous
Portal with caller/provider auth, while `qwen/*` and `lmstudio/*` route to LM
Studio.

### Hermes provider probing created noisy proxy 404s

Status: fixed in source on 2026-05-15; live proxy update in progress.

Problem:

Hermes custom-provider discovery probes model detail and Ollama-compatible
paths such as `/api/v1/models`, `/api/tags`, `/v1/props`, `/props`,
`/version`, `/api/show`, and `/v1/models/<model>`. The initial proxy worked
after falling back to `/v1/models`, but logged each unsupported probe as a 404.

Impact:

The local route worked, but the proxy logs looked noisy and harder to explain
in a demo or audit.

Fix:

Add compatibility responses for those harmless discovery paths.

### Hermes interactive setup enabled sudo support

Status: fixed by dashboard harness default on 2026-05-15.

Problem:

The host Hermes setup has sudo support enabled for interactive use. Queue
workers should not inherit broad sudo access by default because dashboard
approval gates and credential leases are the intended privilege boundary.

Fix:

The Hermes harness environment sets `SUDO_PASSWORD` to an empty value by
default and launches Hermes through `setpriv` as uid/gid `1000`. Elevated
operations must be implemented through scoped provider adapters or explicit
vault-backed deployment overrides.

## Found In Learning Catalog Cleanup Proof

### Done checkpoint did not close ticket when agent skipped explicit status call

Status: fixed, deployed, unit-tested, and live-smoke verified on 2026-05-15.

Problem:

Agent `214` completed task `211` with checkpoint
`learning_cleanup_complete`, `progress_pct=100`, and
`LEARNING_CLEANUP_COMPLETE LEARNING_CLEANUP_AGENTIC_1778857750` evidence, but
ticket `559` stayed `new` because the agent did not call
`POST /api/tickets/559/status` before exiting.

Impact:

The agent work was complete, but the ticket/provider lifecycle needed
supervisor cleanup. This weakens the end-to-end proof because a finished agent
can leave an operator-facing ticket open even when the task prompt explicitly
required resolution.

Fix:

The supervisor closed ticket `559` through the deployed status API with
`close_provider=true`. The API returned `provider_result.status=resolved`, and
a forced single-ticket sync showed both local ticket status and iTop provider
payload status as `resolved`.

The runner now also has a narrow success-path recovery:

- only ticket-resolution tasks qualify;
- the checkpoint must be `done` or `completed` at `100%`;
- the ticket must not already be terminal and must not be in an approval,
  access, user-response, or blocked wait state;
- the task prompt must explicitly require ticket closure;
- there must be no open change gates or access requests;
- there must be final agent evidence notes from the task window.

When all checks pass, the supervisor marks the ticket resolved, writes an
`agent-supervisor` evidence note, attempts provider close through the existing
provider close path, and logs `ticket_status_recovered_from_done_checkpoint`.
Generic task completion still does not silently close tickets.

Verification:

- Local `python -m unittest tests.test_agent_lifecycle_guards`: PASS, 34 tests.
- Remote `PYTHONPATH=api python3 -m unittest tests.test_agent_lifecycle_guards
  tests.test_task_tracker_provider_close tests.test_itop_outbound`: PASS,
  45 tests.
- Live deployed smoke marker `DONE_CHECKPOINT_RECOVERY_SMOKE_1778872231`:
  synthetic local-only ticket `563`, agent `217`, task `214`; recovery returned
  `status=recovered`, ticket status became `resolved`, provider result was
  skipped as `provider_local`, event
  `ticket_status_recovered_from_done_checkpoint` was recorded, and
  `/api/agents/active` remained empty.

### Agent-authored notes without attribution self-steer as dashboard notes

Status: fixed, deployed, and unit-tested on 2026-05-15.

Problem:

Agent `214` posted a completion/evidence note to ticket `559` without explicit
`author` or `source` fields. The ticket note endpoint defaulted the note to
`author=dashboard` and `source=dashboard`, so the non-interrupting steering
system treated the agent's own note as a human dashboard update and delivered a
steering event back to the same active agent.

Impact:

The audit trail misattributes agent evidence as dashboard/operator text, and an
active agent can receive a noisy self-steering inbox update. This can delay
closure or create confusing run evidence even though the note body itself is
valid.

Fix:

- Keep explicit `author`/`source` attribution as the preferred agent contract.
- Add a narrow API fallback for local runner note posts that omit attribution:
  when the request comes from the local API/runner path and exactly one active
  agent is assigned to that ticket, infer `author=agent-<id>` and
  `source=agent`.
- Preserve dashboard/provider note steering for explicit or non-local notes.
- Add route-level regression tests so omitted local agent attribution no longer
  creates dashboard self-steering risk.

Verification:

- Local `python -m unittest tests.test_ticket_status_endpoint
  tests.test_agent_note_steering`: PASS, 11 tests.
- Remote `PYTHONPATH=api python3 -m unittest tests.test_ticket_status_endpoint
  tests.test_agent_note_steering tests.test_itop_outbound
  tests.test_ticket_service_provider_sync`: PASS, 23 tests.
- Remote API rebuild completed; `/health` returned
  `{"status":"ok","version":"1.3.0"}` and `/api/agents/active` returned zero
  active agents after restart.

## Found In Access Broker Review

### Credential broker decisions were too opaque and approved workflows could not pre-mint normal leases

Status: fixed, deployed, and unit-tested on 2026-05-15.

Problem:

Per-agent vault leases existed, and Wazuh provider access was lease-gated, but
the operator-facing audit payloads were too terse to explain whether the
dashboard was brokering a provider call or only returning a vault reference.
Approved workflows also could not declare normal read/investigation leases to
mint at agent spawn, so proven workflows could still force repeated access
requests for the same least-privilege read access.

Impact:

The demo/audit story was hard to explain without reading source code, and
approved repeatable workflows had no configurable way to carry their normal
read access envelope.

Fix:

- Added modular vault provider metadata through `api/services/vault_providers.py`
  with `CREDENTIAL_VAULT_PROVIDER` and `CREDENTIAL_VAULT_RESOLVER_MODE`.
- Lease allow/deny responses now include `broker_trace.human_summary`,
  provider metadata, `secret_values_returned=false`, and `credential_value=null`.
- Wazuh broker endpoints identify themselves as `prebuilt_provider_endpoint`
  and explain that the dashboard returned provider evidence, not a secret.
- Reviewed active/approved workflows can define
  `approval_policy.preapproved_leases`; matching agent spawns mint only those
  scoped lease references and log `workflow_preapproved_lease` evidence.

Verification:

- Local `python -m unittest discover -s tests -p "test_*.py"`: PASS, 114 tests.
- Remote `PYTHONPATH=api python3 -m unittest tests.test_access_control_policy`:
  PASS, 10 tests.
- Remote `/api/access/policies` shows `credential_broker` metadata and
  `workflow_preapproved_leases`; `/api/agents/active` stayed empty after deploy.

## Found In Workflow Reuse Proof

### Workflow review activation hit HTTP 500 when demoting active siblings

Status: fixed, deployed, and remote unit-tested on 2026-05-15.

Problem:

`scripts/smoke_workflow_canonicalization.py` created a reviewed active
workflow, moved a second reviewed workflow onto the same `workflow_key`, then
called `POST /api/workflows/{id}/review`. The live API returned HTTP 500 while
demoting the active sibling.

Impact:

The intended one-active-per-key workflow policy exists in the local route and
unit tests, but the deployed asyncpg/runtime path exposed a server error before
the smoke could prove live review activation and audit evidence.

Fix:

The route used `$2::text` in the sibling-demotion note but passed the integer
workflow id directly, which asyncpg rejected as `expected str, got int`. The
route now passes `str(workflow_id)` for that text-cast parameter, and the unit
test asserts the text parameter shape.

Verification:

- Remote focused unit test passed after rebuild:
  `PYTHONPATH=api python3 -m unittest tests.test_workflow_postmortem_reuse`.
- The canonicalization smoke proceeded past the review activation path on the
  rerun and exposed the next knowledge-article reuse issue below.

### Postmortem promotion reused workflow but duplicated knowledge articles

Status: fixed, deployed, and remote unit-tested on 2026-05-15.

Problem:

`scripts/smoke_workflow_canonicalization.py` proved the second phishing
postmortem reused the same canonical `incident:phishing` workflow, but
promotion still returned a different `knowledge_article_id` for each
postmortem.

Impact:

Operators get one reusable workflow but multiple near-duplicate knowledge
articles for the same operational lesson, so the learning tab remains noisy and
agents can receive fragmented guidance.

Fix:

Promoted knowledge now reuses a canonical article keyed by
`workflow:{workflow_key}:knowledge` when a workflow is being promoted. Repeated
lessons merge into that article, and postmortem detail looks up both legacy
per-postmortem articles and the canonical workflow article.

Verification:

- Remote focused unit test passed after rebuild:
  `PYTHONPATH=api python3 -m unittest tests.test_workflow_postmortem_reuse`.
- The canonicalization smoke proceeded past knowledge-article reuse and exposed
  the ticket-context workflow selection issue below.

### Ticket context did not prefer the active canonical workflow

Status: fixed, deployed, and live-smoke verified on 2026-05-15.

Problem:

The canonicalization smoke verified there was only one `incident:phishing`
workflow in ticket context, but that selected row was not `active`.

Impact:

Agents can still be shown a tested/review-gated workflow instead of the active
reviewed workflow for the same use case. This is the exact demo risk where
`phishing-smoke-lifecycle` or another tested workflow appears to be the one in
use even though activation state says otherwise.

Fix:

Postmortem promotion now preserves or restores `active` status when updating an
already-reviewed canonical workflow that had previously been demoted by the
older promotion path. This keeps ticket context pointed at the active reviewed
workflow while still recording promotion evidence and canonical knowledge.

Verification:

- Live `scripts/smoke_workflow_canonicalization.py` passed against
  `http://127.0.0.1:25480`: workflow `86` reactivated and superseded `87`;
  phishing postmortems `92`/`93` reused workflow `4` and knowledge article
  `55`; ticket context returned workflow `4`.

### Workflow canonicalization smoke created auto-assigned agent work

Status: fixed, deployed, and live-smoke verified on 2026-05-15.

Problem:

The canonicalization smoke creates local phishing tickets for workflow reuse
evidence. Those synthetic tickets did not explicitly disable RACI
auto-assignment, so the dashboard spawned agent `209` on ticket `547`.

Impact:

Deterministic smoke tests can unexpectedly consume the local model lane and
look like unrelated work. This is especially risky in the shared lab because
test probes must not overlap real agentic runs unless intentionally testing the
model path.

Fix:

`scripts/smoke_workflow_canonicalization.py` now creates synthetic phishing
evidence tickets with `auto_assign=false`.

Verification:

- Agent `209` on ticket `547` was confirmed to be the synthetic smoke-spawned
  worker. After the API rebuild ended the process, cleanup note `1250` and
  status note `1251` closed ticket `547` as non-customer smoke work.
- Live `scripts/smoke_workflow_canonicalization.py` passed against
  `http://127.0.0.1:25480`: workflow `91` reactivated and superseded `92`;
  phishing postmortems `98`/`99` reused workflow `4` and knowledge article
  `55`; `/api/agents/active` remained empty afterward.

### Agent curl calls with unquoted query parameters can return empty evidence

Status: fixed, deployed, and remote unit-tested on 2026-05-15.

Problem:

The accidental smoke-spawned agent `209` followed the bounded-evidence prompt
but ran a Bash curl command against
`/api/postmortems/evidence/547?task_log_lines=0&max_notes=8&max_articles=1&max_audit=6`
without quoting the URL. Bash treated `&` as background separators, so the
first evidence request completed with no useful output and the agent started
debugging the endpoint instead of the ticket.

Impact:

Real agentic runs can lose their compact evidence at the first step and drift
into retry/debug behavior even though the dashboard endpoint is healthy.

Fix:

Reusable ticket, auto-assignment, and postmortem prompts now explicitly tell
agents to quote full curl URLs that contain `?` or `&`.

Verification:

- Local `python -m unittest tests.test_task_prompts_ticket_closure
  tests.test_workflow_postmortem_reuse`: PASS.
- Remote `PYTHONPATH=api python3 -m unittest tests.test_task_prompts_ticket_closure
  tests.test_workflow_postmortem_reuse`: PASS.

### Draft workflow promotion smoke expects draft workflow in ticket context

Status: fixed, deployed, and live-smoke verified on 2026-05-15.

Problem:

`scripts/smoke_postmortem_promotion.py` creates a draft workflow from a generic
postmortem and then asserts that the promoted workflow appears in ticket
context. The context endpoint now prioritizes active/tested operational
workflows and can omit draft one-off promotion artifacts.

Impact:

The smoke assertion no longer matches the safer context behavior. Agents should
not be pushed draft/unreviewed workflows as operational guidance unless they are
explicitly doing review or postmortem work.

Fix:

`scripts/smoke_postmortem_promotion.py` now verifies the draft workflow through
the postmortem promotion asset detail and workflow detail endpoints, keeps the
ticket context note check, and asserts draft workflows are not presented as
operational guidance.

Verification:

- Live `scripts/smoke_postmortem_promotion.py` passed against
  `http://127.0.0.1:25480`: ticket `552`, postmortem `97`, knowledge article
  `73`, draft workflow `90`, and skills `96`/`97`.

### Active agent can stall after approvals by chasing oversized persisted context output

Status: fixed, deployed, and real-agent tested on 2026-05-15.

Problem:

Workflow reuse proof ticket `537` / agent `200` received approval steering for
changes `159` and `160`, but its task checkpoint stayed at the initial queued
checkpoint. The task output showed the agent was trying to parse a large saved
tool-result file from `/root/.claude/projects/.../tool-results/...` instead of
returning to the compact evidence endpoint or completing the approved gates.

Impact:

The run was not blocked by approvals anymore, but the model could continue
spending time on a brittle context-file recovery path. That makes real
post-approval continuation look unreliable even though the control plane
delivered the approval steering correctly.

Mitigation:

- Do not stop the owned harness while it is still alive unless swim-lane
  evidence proves it cannot recover.
- Add a bounded steering note to the ticket telling the agent that changes
  `159` and `160` are approved, to ignore the saved tool-result parsing path,
  re-read compact evidence or current ticket context, complete the gates with
  lab-safe evidence, write final notes, and resolve the ticket.
- Harden ticket and auto-assignment prompts plus the global runner instructions:
  agents must not read saved harness `tool-results` files from current or prior
  workdirs to recover context, and must re-query bounded dashboard evidence
  endpoints with narrower filters instead.
- Tighten the compact postmortem evidence endpoint defaults so agent-facing
  responses use fewer notes/articles/audit entries, shorter text snippets, and
  the compact ticket payload. Ticket `537` / continuation agent `201` showed
  that the previous "compact" response could still be too large for a local
  continuation turn after an approval gate.

Verification:

- Agent `202` used the bounded evidence path, completed approved changes `159`
  and `160`, and wrote final ticket note `1188`.
- The run exposed a second endpoint-drift issue: agent `202` tried
  `PATCH`/`PUT`/`POST /api/tickets/537` instead of the documented
  `POST /api/tickets/537/status`.
- `api/routes/tickets.py` now accepts explicit status payloads on
  `POST`/`PUT`/`PATCH /api/tickets/{id}` as a compatibility shim that reuses
  the same access check, status validation, audit note, and `close_provider`
  opt-in behavior as the canonical `/status` endpoint.
- Agent `203` performed the final compatibility-path proof by calling
  `POST /api/tickets/537` with `close_provider=false`; the API returned
  `status=resolved`, status note `1193`, and provider close skipped as
  requested.
- Ticket `537` ended `resolved`; agent `203` / task `200` ended
  `finished` / `completed` at `100%`; `/api/agents/active` returned zero.
- Local regression tests passed:
  `python -m unittest tests.test_agent_lifecycle_guards tests.test_ticket_status_endpoint`.
- AI server focused tests passed before rebuild:
  `PYTHONPATH=api python3 -m unittest discover -s tests -p 'test_agent_lifecycle_guards.py'`
  and `PYTHONPATH=api python3 -m unittest discover -s tests -p 'test_ticket_status_endpoint.py'`.

### Completed task can leave a stale initial checkpoint file

Status: fixed, deployed, and unit-tested on 2026-05-15.

Problem:

In the same ticket `537` proof, continuation agent `203` resolved the ticket
and task `200` reached `completed` / `100%` in the database, but the workspace
`/app/agent_work/203/checkpoint.json` still contained the initial
`init` / `queued` checkpoint. The runner correctly persisted task completion,
but the file evidence did not match the task table when the model exited
without writing its own final checkpoint.

Impact:

Operators and auditors who inspect the workspace file directly can see stale
evidence even though the control plane marked the task complete. That makes
demo evidence harder to explain and weakens self-repair logic that reads the
file first.

Fix:

- `api/services/agent_runner.py` now writes a terminal `checkpoint.json` with
  `status=done`, `progress_pct=100`, and an explicit runner step when a
  harness exits successfully or completion is recovered from terminal evidence
  without a final done checkpoint.
- Added a regression test proving successful agent completion creates a
  terminal checkpoint file when the model omitted one.

## Found In Wazuh Access Request Pass

### Approved Wazuh access request did not mint a usable agent lease

Status: fixed, deployed, and real-agent tested on 2026-05-15.

Problem:

Ticket `533` / agent `197` requested Wazuh API read access. The approval gate
was approved and completed, but the completion result showed
`granted_leases: []`. The agent then retried
`POST /api/agents/197/vault/lease` for `wazuh.manager` read and still received
`missing_agent_vault_lease`.

Impact:

The agent could not retrieve full Wazuh alert details after approval, so it
classified the alert from partial ticket evidence and wrote an investigation
limitation. That is unacceptable for the real access-request workflow: approval
must create a scoped lease and the runner must have an auditable provider path
to use it.

Current diagnosis:

- The access request did not include a structured `lease_request`, so the
  access gate had no lease to mint on completion.
- The Wazuh API is reachable on the host at `https://127.0.0.1:26500`, but the
  dashboard runner container cannot resolve `host.docker.internal` or the Wazuh
  compose service name.
- The Wazuh container exposes API credentials through runtime environment, but
  the dashboard must consume only vault references and scoped leases, never
  plaintext ticket notes or hardcoded secrets.

Fix:

- Infer provider lease requests for known access resources such as
  `wazuh.manager API` when agents omit `lease_request`.
- Add explicit audit/event evidence when access requests include, infer, mint,
  or fail to mint leases.
- Provide a dashboard-controlled Wazuh alert lookup path that validates a
  scoped `agent_vault_leases` row before reaching the Wazuh API.
- Surface Wazuh semantic responses, such as "rule does not exist", as provider
  evidence instead of converting them into dashboard transport failures.
- Add unit and real agentic access-request tests proving denial before
  approval, lease minting after approval/completion, and Wazuh provider reads
  through the approved path.

Verification:

- Local compile and full unit suite: `python -m unittest discover -s tests -p
  "test_*.py"` passed, 107 tests.
- Remote focused suite passed after rebuild:
  `PYTHONPATH=api python3 -m unittest tests.test_access_lease_inference
  tests.test_change_approval_resume`.
- Real local-model proof `WAZUH_ACCESS_1778811177`: ticket `535`, initial
  agent `198`, continuation agent `199`, access request `15`, access ticket
  `536`, change `158`. Agent `198` was denied Wazuh read access and stopped at
  `awaiting_access`; approval inferred/minted Wazuh lease `127`; agent `199`
  re-requested the lease with `credential_value: null`, read Wazuh manager
  status through the gated endpoint, performed rule and indexer lookups, and
  resolved the ticket.

Residual note:

The proof corrected its ticket history with note `1164`: Wazuh manager status
was retrieved successfully, but Wazuh returned no rule metadata for id `11` and
the indexer search for rule `11` / source `192.168.50.115` returned zero
matching alerts. The access-control and provider-read path is fixed; the
original alert content still depends on the upstream SIEM ticket payload and
available Wazuh/indexer data.

## Found In Current Note-Steering Pass

### Overview agent count did not match Agents tab lifecycle count

Status: fixed, deployed, and remote-tested on 2026-05-14.

Problem:

The Overview stat card used `/api/dashboard/stats.agents.active`, which counted
only agents in `spawned`, `running`, or `working`. The Agents tab badge counted
the visible operational queue: queued, active, and waiting-on-gate agents. In
the live complex proof, Overview showed `1` while the Agents tab showed `5`
because four agents were intentionally waiting behind access gates.

Impact:

The dashboard looked internally inconsistent even though the underlying state
was correct. Demo viewers could misread waiting-on-gate agents as missing from
the control plane.

Fix:

The Overview label is now `Open Agents`. The frontend has a shared
`setAgentOpenCount(...)` state helper and both Overview and Agents write through
it, so tab navigation carries the same value instead of letting each page own
the badge independently. Overview now fetches `/api/agents` and uses the same
lifecycle categorization as the Agents tab; it only falls back to stats
distribution when the agent-list endpoint is unavailable. The stats API now
also returns explicit `active`, `queued`, `waiting`, `stalled`, `history`, and
`open` lifecycle counts for future deployments.

### Local model paused after postmortem promotion before final ticket status

Status: fixed, deployed, and remote-tested on 2026-05-14.

Problem:

In complex proof `COMPLEX_PHISH_EDR_1778789996`, continuation agent `196`
completed containment change `156`, added final containment evidence, created
postmortem `82`, reviewed it, and promoted it into knowledge article `66`,
workflow `76`, and skills `90`/`91`. After the promotion response, the model
remained in the harness before executing the last two prompt steps: explicit
ticket `resolved` status update and final `checkpoint.json`.

Impact:

The real agentic work was done, including access gates, containment approval,
postmortem review, and workflow/skill promotion, but the dashboard could still
show the ticket `in_progress` and the agent `working`. That makes demos hard to
explain and can keep the one-agent local-model lane occupied even though the
remaining work is deterministic final bookkeeping.

Fix:

`agent_runner.recover_completed_ticket_resolution(...)` now has a narrow
terminal-evidence recovery path for this exact state. If there are no open
change gates, at least one completed change, final completion notes, and a
promoted postmortem/workflow asset, the supervisor may mark the ticket
`resolved`, write an `agent-supervisor` note explaining the recovery, and then
finish the task/agent. Generic task completion still does not close tickets,
and open approval/access gates still fail closed.

Verification:

- `python -m py_compile api\services\agent_runner.py`: PASS.
- `python -m unittest tests.test_agent_lifecycle_guards`: PASS, including
  `test_recover_completed_ticket_resolution_resolves_promoted_open_ticket`.
- Remote rebuilt API source suite: `PYTHONPATH=api python3 -m unittest discover
  -s tests -p 'test_*.py'`: PASS, 96 tests.
- Live ticket `531` ultimately completed its own final status path: ticket
  `resolved`, agent `196` `finished`, task `193` `completed` at 100%, and
  `/api/agents/processes` returned zero active processes.

### Approved gate can miss resume if the agent blocks after the approval call

Status: fixed, deployed, and full complex proof verified on 2026-05-14.

Problem:

During complex proof `COMPLEX_PHISH_EDR_1778789996`, containment change `156`
was approved while agent `195` was still running. The approval path correctly
returned `resume.status=already_active`. A few minutes later the same agent
finished writing its durable `pending_approval` checkpoint and stopped. Because
the change was already `approved`, there was no second pending approval event to
resume the final leg.

Impact:

The ticket had correct evidence and an approved gate, but no active agent was
left to consume that approval and complete containment/postmortem work. This is
the exact race that can happen when a human approves a gate while the model is
still flushing its wait checkpoint.

Fix:

`POST /api/changes/{id}/approve` is now idempotent for already-approved gates:
calling it again attempts `_resume_agent_after_approval` instead of returning a
dead-end "not pending" error. The complex proof driver also waits for durable
`pending_approval` / `awaiting_access` checkpoints before approving gates.
Re-approving already-approved containment change `156` spawned continuation
agent `196` / task `193` for ticket `531` instead of leaving agent `195`
permanently behind the already-open gate.

### Approval-gate continuation handoff was not obvious in ticket history

Status: fixed locally and remediated for ticket `531` on 2026-05-14; deploy
pending active agent `196` completion.

Problem:

Ticket `531` showed agents `194`, `195`, and `196` plus changes `155` and
`156`. Agents `194` and `195` were intentionally stopped at durable gates:
`194` at `awaiting_access` for Wazuh access and `195` at `pending_approval` for
containment approval. The control plane resumed the original ticket by spawning
continuation agent `196`, but the ticket timeline only showed generic
"assigned/started/waiting" notes.

Impact:

Operators could reasonably read the three-agent chain as duplicate assignment or
as older agents stuck indefinitely, instead of a deliberate gate-stop plus
continuation pattern. This weakens demo readability and audit traceability even
when the lifecycle behavior is correct.

Fix:

`_resume_agent_after_approval` now records an `agent-lifecycle` ticket note
whenever it spawns a continuation agent. The note states the source agent, the
replacement agent/task, the change id, the approver, and that the source agent
is historical evidence for the wait state. The source agent's `error_message`
is also annotated with the continuation agent/task so agent-detail views do not
look abandoned.

Follow-up correction:

The first fix left source agents in `awaiting_access` / `pending_approval`,
which kept them in the dashboard Waiting On Gate section after the continuation
agent took ownership. Handoff now moves the source agent to `finished` and the
source task to `completed` with the handoff evidence, so the continuation agent
is the only active/waiting owner for that ticket.

### Manual process check under-reported active continuation agent

Status: investigated on 2026-05-14; no product fix required.

Problem:

During complex proof ticket `531`, continuation agent `196` / task `193`
advanced to the final containment path and wrote
`payload_change_156_complete.json`. A manual `ps` command with a narrow grep
pattern did not show the process even though the database still showed task
`193` as `running`, agent `196` as `working`, and change `156` as `approved`.

Impact:

This briefly looked like an orphaned running task and would have blocked safe
API redeploys if trusted without checking the structured process endpoint.

Resolution:

`GET /api/agents/processes` correctly reported PID `14` and
`active_processes: [193]` for agent `196`, so the continuation agent was still
alive. Use the dashboard process endpoint plus task DB state as the authoritative
status check; do not rely on ad hoc grep filters alone.

### iTop sync can downgrade local wait states after an agent blocks

Status: fixed, deployed, and remote regression verified on 2026-05-14.

Problem:

After agent `195` stopped at `pending_approval`, iTop still reported provider
status `new` for Incident `308`. A provider sync changed dashboard ticket `531`
from `pending_approval` back to `new`.

Impact:

The approval gate and task checkpoint were still visible, but the primary
ticket status no longer reflected the local wait state.

Fix:

iTop sync now preserves local wait states (`awaiting_user_response`,
`awaiting_access`, `pending_approval`, and `blocked`) while the provider is
non-terminal, the same way it already preserves local terminal states.

### Ticket notes do not steer already-running agents

Status: fixed, deployed, and live-agent verified on 2026-05-14.

Problem:

Dashboard and provider-synced ticket notes are durable ticket context, but an
already-running agent only sees them if it independently re-reads ticket context.
There is no explicit non-interrupting note-update hook that tells the active
agent "new information arrived; keep the original objective, but incorporate
this update."

Impact:

Operators can add clarifying notes in the dashboard or iTop while an agent is
working, but the agent may continue on stale context or a human may be tempted
to stop/restart it. Stopping the harness risks losing objective continuity, so
the correct behavior is to deliver a bounded steering update without replacing
the agent's task.

Fix:

- Record a durable steering event whenever a user/provider note is added to a
  ticket that has an active agent.
- Mirror pending steering events into the agent work directory as a compact
  inbox file the agent can poll while continuing its original task.
- Update agent prompts/skills so active agents check the inbox between major
  steps and treat notes as context, not as a replacement objective.
- Prove the behavior with unit tests and real active local-agent runs, including
  dashboard note and iTop/provider-note style updates.

Implemented with `agent_steering_events`, per-agent
`agent_steering_inbox.json` / `AGENT_STEERING.md`, dashboard steering APIs, and
iTop case-log note mirroring. First live proof ticket `529` / iTop
`UserRequest::306` / agent `192` delivered dashboard note `1062` and iTop note
`1066` into the same active agent without interrupting it. Clean rerun ticket
`530` / iTop `UserRequest::307` / agent `193` delivered dashboard note `1075`
and iTop note `1079`, produced `STEERING_OBSERVED_DASHBOARD`,
`STEERING_OBSERVED_ITOP`, and `STEERING_COMPLETE NOTE_STEERING_1778787230`,
completed task `190` at 100%, and left no active agent processes.

### Note-steering proof driver checked terminal task state too early

Status: fixed, deployed, and clean live-agent rerun verified on 2026-05-14.

Problem:

The live proof wrapper saw the agent's final `STEERING_COMPLETE` ticket note
before the runner had flushed terminal task state and the 100% checkpoint. The
wrapper exited with an error while the owned agent was still running, even
though the agent later completed cleanly.

Impact:

The system behavior was correct, but proof output could falsely look failed
because the driver did not wait for the final task checkpoint.

Fix:

`scripts/agentic_note_steering_demo.py` now waits for task `completed`,
`progress_pct >= 100`, and checkpoint
`note-steering-complete-<marker>` before printing pass. Clean rerun
`NOTE_STEERING_1778787230` printed `status: passed` only after agent `193` /
task `190` completed with 100% progress.

### iTop sync can overwrite a locally resolved agent ticket with stale provider state

Status: fixed, deployed, and provider-sync verified on 2026-05-14.

Problem:

After the live note-steering proof, the agent locally resolved ticket `529`
with `close_provider=false`. A later iTop sync refreshed the provider status
`new` and overwrote the local dashboard status back to `in_progress`.

Impact:

The agent completed correctly, but dashboard status could look unfinished when
provider closure is intentionally deferred.

Fix:

iTop sync now preserves local terminal states such as `resolved`, `closed`, and
`implemented` while the provider is still non-terminal. Provider terminal states
still flow back into the dashboard. After clean proof ticket `530` resolved
locally, a forced iTop sync still saw provider status `new` but preserved
dashboard status `resolved`.

### iTop HTML markup can leak into dashboard ticket descriptions

Status: fixed, deployed, and provider-sync verified on 2026-05-14.

Problem:

iTop returns descriptions with HTML markup such as `<p>...</p>`. The synced
ticket context for proof ticket `530` still showed the raw paragraph tags.

Impact:

Dashboard ticket descriptions can look broken or expose provider formatting
instead of readable text.

Fix:

iTop sync now strips simple markup from provider descriptions before writing the
canonical dashboard ticket description, using the same sanitizer as iTop
case-log note mirroring. After redeploy, forced sync on ticket `530` rewrote
the description without raw `<p>` tags.

## Found In Current Permission-Proof Pass

### Agent can write a durable access-wait checkpoint but fail to exit

Status: fixed, deployed, and live-verified on 2026-05-14.

Problem:

During first-alias permission-vault proof `AGENTIC_PERMISSION_VAULT_1778778629`,
agent `190` correctly created access request `12`, iTop child ticket `527`
/ provider ref `304`, and change gate `154`. It then wrote
`checkpoint.json` with step
`waiting-for-vault-access-AGENTIC_PERMISSION_VAULT_1778778629`, status
`waiting_for_access`, and progress `45`, but the harness process remained open.
Because the runner only mirrors the blocking checkpoint after process exit, the
dashboard continued to show task `187` as `running` and agent `190` as
`working` instead of moving them to `awaiting_access`.

Impact:

The permission boundary itself worked and the iTop-synced access request was
created, but the approval/resume path was blocked by harness lifecycle behavior
after the durable wait checkpoint had already been written.

Fix:

The runner should monitor `checkpoint.json` while the process is still running.
When a durable blocking checkpoint such as `waiting_for_access` appears, it
should persist the checkpoint, move the task and agent to the mapped wait state,
and terminate only that owned harness process so the approval/resume workflow
can continue without waiting for the one-hour no-output timeout.

Implemented as `_terminate_after_blocking_checkpoint` in
`api/services/agent_runner.py`. The API image was rebuilt after active agent
count reached `0`, `AGENT_NO_OUTPUT_STALL_SECONDS` remained `3600`, focused
lifecycle tests passed, and full remote unittest discovery passed 81/81.

### Stale API bytecode hid the active process reconciliation fix

Status: fixed, deployed, and verified on 2026-05-14.

Problem:

During first-alias permission-vault proof `AGENTIC_PERMISSION_VAULT_1778778629`,
agent `190` / task `187` was actively running with container PID `19`, and the
database task row also stored PID `19`. The source file on disk included the
DB-backed process reconciliation fix, but importing `services.agent_runner`
inside the API container showed `get_process_snapshot.__code__.co_names`
without `fetchall`, proving the interpreter was still executing stale bytecode.
As a result, `/api/agents/processes` still returned `active_processes: []`
while the raw `processes` list showed the active Claude/Qwen process.

Impact:

The active agent was not interrupted and the raw process stream still showed
what was running, but the structured `active_processes` field was unreliable
until the stale bytecode is cleared and the API imports the updated module.

Fix:

After the active first-alias permission proof completes, remove the stale
`__pycache__` entry for `agent_runner.py`, restart only the dashboard API while
no agents are active, and verify `get_process_snapshot.__code__.co_names`
includes `fetchall` plus `/api/agents/processes` reports the expected task id
during the next active run.

Completed after ticket `525` proof finished: active agents were `0`, stale
`agent_runner` bytecode was removed from host/container paths, the API image was
rebuilt from updated host source, and in-container import verification returned
`fetchall_in_get_process_snapshot=True` and `checkpoint_watcher_present=True`.

### Permission-vault demo wrapper reported pass before resumed task terminal state flushed

Status: fixed, deployed, and verified on 2026-05-14.

Problem:

The first-alias permission-vault proof completed successfully, but the wrapper
summary printed `task_status: running` and `task_progress: 40` even though the
dashboard later showed resumed agent `189` / task `186` as `completed` at 100%.
The wrapper declared success as soon as the ticket was resolved, the final note
was visible, and the access request was granted.

Impact:

The control-plane behavior was correct, but demo/test output could look
inconsistent because the wrapper did not wait for the resumed task terminal
state and final checkpoint to flush before printing the pass summary.

Fix:

Require the resumed task to reach `completed` with 100% progress and the final
`ACCESS LEASE GRANTED` checkpoint before `agentic_permission_vault_access_demo.py`
prints `status: passed`.

Implemented and covered by
`tests.test_permission_vault_demo.PermissionVaultDemoTests.test_wait_completion_requires_resumed_task_terminal_checkpoint`.
The live first-alias wrapper did not print `status: passed` until agent `191`
/ task `188` completed at 100% with final checkpoint
`vault-access-complete-AGENTIC_PERMISSION_VAULT_1778778629`.

### Agent process endpoint omits active_processes for container-spawned subject runs

Status: fixed, deployed, and live-verified on 2026-05-14.

Problem:

During first-alias permission-vault proof `AGENTIC_PERMISSION_VAULT_1778773989`,
agent `188` / task `185` was running with PID `265`. `/api/agents/processes`
listed the Claude command in `processes`, but returned `active_processes: []`.

Impact:

Operators can still see the process in the raw process list, but the structured
`active_processes` field under-reports active work for subject-spawned
container runs. This makes active process monitoring less reliable for
agentic permission tests and demos.

Fix:

Normalize PID/task matching for agents spawned from inside the API container
through subject-aware runner paths so `active_processes` includes the task id
when the stored task PID is present in the process list.

Verification:

- Rebuilt API source includes the database-backed PID reconciliation path.
- Live first-alias proof `AGENTIC_PERMISSION_VAULT_1778778629` showed task
  `188` in `/api/agents/processes.active_processes` while agent `191` was
  active, then showed zero active processes after the agent completed.

### Abandoned model-matrix wrapper started a non-primary alias after scope changed

Status: documented on 2026-05-14.

Problem:

An earlier local-model matrix wrapper continued running after the test scope was
narrowed to only `qwen/qwen3.6-27b`. It spawned agents `184`, `185`, and `186`
for `qwen/qwen3.6-27b2`, `qwen/qwen3.6-27b3`, and `qwen/qwen3.6-27b4` on
tickets `518`, `519`, and `520` with the older short matrix wait settings.

Impact:

This violated the current first-alias-only test scope and could consume agent
runner/model capacity while the permission proof is supposed to focus only on
the primary alias. It was verified by inspecting the remote process tree before
taking action. The matrix controller PID was `3634350`; stopping only child
smoke scripts allowed it to advance once per child, so the controller must be
stopped before the active child.

Expected fix:

Do not start multi-alias matrix wrappers during first-alias permission proof
runs. If a scope change happens mid-run, identify the wrapper command and stop
only the verified out-of-scope wrapper/agent lane. Keep
`AGENT_NO_OUTPUT_STALL_SECONDS=3600`; do not shorten runner no-output timeout
to accelerate model testing.

### Restoring runner timeout during active smoke killed test agent

Status: documented on 2026-05-14.

Problem:

- A previous interrupted model-alias matrix left `qwen/qwen3.6-27b` smoke agent
  `183` running on ticket `517`, task `180`.
- Restoring the live environment from `AGENT_NO_OUTPUT_STALL_SECONDS=120` back
  to `3600` required `docker compose up -d api`, which recreated the API
  container and terminated that active test-lane process.

Impact:

- Even when correcting configuration, API restarts kill active dashboard-owned
  agent subprocesses. This invalidates the active agentic test and should never
  be used as a casual way to change runner knobs during live proof runs.

Follow-up rule:

- Before any API restart/rebuild/config restore, check `/api/agents/active` and
  `/api/agents/processes`. If any agent is active, either wait for it, explicitly
  document and stop only the current test-owned lane, or defer the restart.
- 2026-05-15 recurrence: API rebuild for prompt/smoke fixes ended synthetic
  smoke agent `209` on ticket `547`. The agent was verified as the
  canonicalization-smoke-owned lane first, cleanup note `1250` and status note
  `1251` closed the synthetic ticket, and the smoke was fixed to use
  `auto_assign=false` so future runs do not spawn the model lane.

### Direct agent spawn skipped ticket row-scope checks

Status: fixed locally, deployed, and live-verified on 2026-05-14.

Problem:

- The ticket-level `/api/tickets/{id}/assign-agent` route checks whether the
  spawning subject can read the target ticket, but direct `/api/agents/spawn`
  accepted a `ticket_id` and started an agent without the same row-level ticket
  decision.
- The ticket-level assign route also did not forward a requested permission
  envelope, so over-broad requested agent permissions could not be proven as
  trimmed from that common UI path.

Impact:

- A user with `agents:spawn` but without access to a specific ticket could
  attempt to start an agent on a ticket outside their group/classification scope
  through the direct agent route.
- The per-agent permission boundary remained present, but one spawn entry point
  was missing the required parent-ticket guard.

Fix plan:

- Apply the same ticket existence and row-scope check in `/api/agents/spawn`
  before calling the runner.
- Add `requested_permissions` passthrough to
  `/api/tickets/{id}/assign-agent`.
- Verify with the new local+iTop permission provider matrix.

Verification:

- Local unit discovery passed: 77 tests.
- Live unit discovery passed: 77 tests.
- Live provider matrix marker `PERMISSION_PROVIDER_MATRIX_1778766486`
  verified direct `/api/agents/spawn` is denied for Dev Y against hidden Dev Z
  ticket scope, while scoped spawn on Dev Y still succeeds and trims excess
  requested permissions into the agent snapshot.

### Agentic permission proof harness restarted API after spawning agent

Status: fixed, deployed, and live-verified on 2026-05-14.

Problem:

- The real local-model permission-vault script spawned the scoped Dev Y agent
  while auth enforcement was enabled, then immediately restarted the dashboard
  API back to disabled/audit-only so the model could use normal lab API calls
  without synthetic auth headers.
- That API restart killed the just-spawned subprocess. Tickets `482`/`496`
  stayed `in_progress`, agents `171`/`176` failed with
  `Agent process is no longer running in the API container`, and no access
  request was created.

Impact:

- The agentic permission loop was not actually tested. The failure came from
  the test harness restarting the runner process, not from a real model
  permission decision.

Fix plan:

- Keep the API stable during the live agent run.
- Spawn the agent through the in-container runner with the Dev Y subject loaded
  from the access-control tables, so the agent receives Dev Y's bounded vault
  leases without injecting auth headers into its provider/API curls.
- Use the provider matrix for enforced header/RBAC proof and this script for
  true local-model permission-wall/resume proof.

Verification:

- Script no longer toggles/restarts the API after spawn.
- Live first-alias proof `AGENTIC_PERMISSION_VAULT_1778778629` completed without
  an API restart: parent ticket `525` resolved, access child ticket `527`
  resolved, access request `12` granted, and resumed agent `191` finished.

### One-shot agentic harness created queued task without durable worker

Status: fixed, deployed, and live-verified on 2026-05-14.

Problem:

- After removing the API restart, `agentic_permission_vault_access_demo.py`
  used `agent_runner.spawn_agent()` from a short-lived
  `docker compose exec api python -` helper.
- `spawn_agent()` enqueues work into the current Python process. Because the
  helper process exits right after returning the spawn payload, queued task
  `174` for agent `177` did not start until a manual in-container worker was
  attached.

Impact:

- The test harness can create realistic agent/vault rows, but not reliably run
  the live local-model task end to end unless it also keeps a worker process
  alive for that queued task.

Fix plan:

- Add a harness path that runs the spawned task's `_spawn_with_semaphore`
  execution in the same helper process after spawn, or call a durable API route
  that enqueues work inside the running API server.
- Verify with the active live proof: agent `177`, ticket `498`, marker
  `AGENTIC_PERMISSION_VAULT_1778767569`.

Fix:

- The helper now loads the spawned task and runs
  `agent_runner._spawn_with_semaphore(...)` before returning from the helper
  process, so it cannot strand a queued task without a worker.

Verification:

- Live first-alias proof `AGENTIC_PERMISSION_VAULT_1778778629` ran both the
  initial denied-access agent and the resumed granted-access agent through the
  in-container helper. The resumed task `188` reached `completed` with 100%
  progress and a `vault-access-complete-*` checkpoint.

### Local model stalled after tool_use stop without executable tool payload

Status: fixed, deployed, and live-verified as fail-fast on 2026-05-14.

Problem:

- Live local-model proof agent `177` on ticket `498` read its vault manifest
  and correctly exposed only dashboard ticket leases plus Dev Y GitLab read
  lease. It also showed denied requested permissions
  `changes:approve` and `access:admin`.
- The stream then reached a model message with `stop_reason: tool_use`, but the
  content contained only a thinking block and no concrete tool call payload.
  The process stayed alive, heartbeat continued, and no access request or curl
  action occurred.

Impact:

- A real local-model flow can appear active while no tool work is being
  performed. This is separate from the permission model; the agent did inherit
  the correct bounded vault manifest, but the harness needs to detect and
  recover from a malformed/no-op tool-use turn.

Fix plan:

- Add a bounded no-progress/no-tool-output watchdog signal for local-agent
  runs, using actual stream/output movement rather than UI percentage.
- For this proof lane, treat agent `177` as test-owned and recover by stopping
  or replacing only that exact agent if it remains stuck after inspection.

Fix:

- The proof harness now passes a shorter
  `AGENT_NO_OUTPUT_STALL_SECONDS` value into the in-container agent runner and
  the prompt explicitly requires simple sequential Bash/curl commands.
- The runner now detects `stop_reason=tool_use` assistant events that contain
  no executable `tool_use` payload and stops the process after the bounded
  watchdog window with an explicit stalled reason.

Verification:

- Live proof marker `AGENTIC_PERMISSION_VAULT_1778768749`, agent `180`, task
  `177` stopped cleanly after 65 seconds with:
  `Agent produced no output for 65 seconds; runner marked it stalled and stopped
  the process to prevent a silent harness/model hang.`
- `/api/agents/active` and `/api/agents/processes` were both empty afterward.

### Agentic proof driver timed out while worker was still running

Status: fixed, deployed, and live-verified on 2026-05-14.

Problem:

- The patched proof harness passed `AGENT_NO_OUTPUT_STALL_SECONDS=180`, but
  also used the same 180 seconds as the outer `subprocess.run(..., timeout=...)`
  limit for `docker compose exec api python -`.
- The driver exited with `subprocess.TimeoutExpired` while live agent `178` was
  still running on ticket `500`, leaving no orchestration process to approve the
  access request if the agent later created one.

Impact:

- The no-output watchdog should govern the inner Claude/local-model process.
  The outer proof driver must stay alive for the full proof timeout so it can
  approve the access gate, observe the resumed agent, and print proof evidence.

Fix plan:

- Make the outer helper timeout use the full proof timeout, not the
  no-output-stall setting.
- Treat agent `178` as a test-owned replacement lane if it remains stalled.

Fix:

- `agentic_permission_vault_access_demo.py` now uses the full proof timeout for
  the outer `docker compose exec` helper while passing the shorter no-output
  timeout only into the inner agent runner environment.

Verification:

- Live first-alias proof `AGENTIC_PERMISSION_VAULT_1778778629` stayed attached
  long enough to approve the access gate, resume the task, and capture terminal
  completion evidence instead of timing out at the inner watchdog boundary.

### Agentic proof driver waited for access request after agent failure

Status: fixed, deployed, and regression-tested on 2026-05-14.

Problem:

- After the runner correctly failed agent `180` for no-output stall, the outer
  `agentic_permission_vault_access_demo.py` process continued waiting for an
  access request that could never be created.

Impact:

- The agent lane is clean, but the proof driver remains as a useless polling
  process until timeout unless manually stopped.

Fix:

- Make `wait_access_request` and `wait_completion` check the latest agent task
  state and fail fast when the relevant agent task reaches `failed` or
  `stopped` before the expected ticket/access evidence appears.

Verification:

- `tests.test_permission_vault_demo.PermissionVaultDemoTests.test_wait_access_request_fails_fast_when_agent_ends`
  covers the pre-access-request failure path.
- `tests.test_permission_vault_demo.PermissionVaultDemoTests.test_wait_completion_requires_resumed_task_terminal_checkpoint`
  covers the post-grant completion path and prevents premature success.

### Access gate completion response hides lease-grant evidence

Status: fixed locally, deployed, and live-verified on 2026-05-14.

Problem:

- The local+iTop permission provider matrix created a synced iTop parent
  ticket, spawned a scoped Dev Y agent, proved denied GitLab and iTop leases,
  created a synced iTop access-request child, approved the gate, and completed
  change `146`.
- The completion API returned only `{"status":"completed","change_id":146}`
  instead of the access-request sync result and granted lease evidence.

Impact:

- The control plane may still grant the scoped lease internally, but the API
  response does not give the runner or demo UI an immediate, auditable proof
  artifact for denied lease -> approved access gate -> granted agent vault
  lease.

Fix plan:

- Confirm whether the lease row was minted for change `146`.
- Return the `_sync_access_request_status` result from the change completion
  route under `access_sync`.
- Rerun the local+iTop matrix and verify the response plus a subsequent vault
  lease request.

Verification:

- Live matrix marker `PERMISSION_PROVIDER_MATRIX_1778766486` completed access
  gate response with `access_sync.granted_leases`, then verified the newly
  granted iTop lease id `37` returned
  `<vault:itop_team_z_read_after_approval>` with `credential_value: null`.

### Access-request child ticket completion did not close iTop object

Status: fixed locally, deployed, and live-verified on 2026-05-14.

Problem:

- The local+iTop permission provider matrix passed RBAC, row-scope, vault
  allow/deny, iTop parent creation, iTop access-request child creation, and
  post-approval lease grant checks with marker
  `PERMISSION_PROVIDER_MATRIX_1778766347`.
- The dashboard access ticket `491` synced to iTop provider ref `294`
  (`R-000303`), but after local access-gate completion the provider-side iTop
  object still read as `status: new`.

Impact:

- Dashboard evidence says the access gate is granted, but the real ticketing
  provider does not reflect the completed access request. That weakens the
  demo and violates the provider-sync expectation for end-to-end workflows.

Fix plan:

- When an access-request gate completes or rejects, update the local child
  access ticket and also close the provider-side access ticket when it has an
  external provider reference.
- Rerun the matrix and verify the iTop access request is no longer `new`.

Verification:

- Live matrix marker `PERMISSION_PROVIDER_MATRIX_1778766486` created dashboard
  access ticket `495`, synced it to iTop provider ref `296` (`R-000305`), and
  verified iTop returned `status: resolved` after access-gate completion.

### Access grant completion did not mint the approved agent vault lease

Status: fixed locally, deployed, and control-plane verified on 2026-05-14.

Problem:

- The access-request workflow marks access requests as `granted` when the
  approval gate is completed, but the completion path does not yet create a new
  `agent_vault_leases` row for the approved system/resource/action.
- That means a resumed agent can prove it requested access and got approval, but
  it cannot prove the approved lease is available afterward without manual DB
  intervention.

Impact:

- The permission wall loop is auditable up to approval, but not fully closed
  from denied lease -> access request -> approval -> new scoped lease -> resumed
  work.

Fix plan:

- Allow access requests to carry a lease request payload with system,
  resource_type, resource_id, action, and optional vault reference.
- On access-gate completion, mint an active `agent_vault_leases` row for the
  original agent and the completing/resumed agent when applicable.
- Verify with a real local-model agent run.

Verification:

- Control-plane matrix marker `PERMISSION_PROVIDER_MATRIX_1778766486` verified
  denied iTop lease -> access request -> approval -> completion -> newly
  granted agent vault lease id `37`.
- Real local-model verification is still running for marker
  `AGENTIC_PERMISSION_VAULT_1778767569`.

### Codex migration audit reported reference-skill drift and a legacy server-manager fallback

Status: legacy fallback fixed on 2026-05-15; broader reference-skill drift remains documented.

Problem:

- Final local hygiene ran `python scripts/audit_codex_migration.py`.
- The audit failed because `sync_reference_skills.py` reports reference-skill
  drift in several skills.
- The reference `agent-memory` script also had a legacy Claude-only
  server-manager fallback path.

Impact:

- This does not block the deployed permission/vault proof, and no plaintext
  secret was introduced by this pass.
- It does mean the broader reference skill bundle needs a separate sync/cleanup
  pass before using the audit as an all-green release gate.

Fix:

- Removed the legacy Claude-only server-manager fallback from both the
  reference `agent-memory` script and the installed `agent-memory` skill.

Follow-up:

- Reconcile the listed reference-skill drift intentionally rather than
  bulk-overwriting unrelated skill work in this permission commit.
- Continue reconciling any remaining reference-skill drift from the allowlisted
  skill bundle.

### Operator-stopped proof agent can be overwritten as failed

Status: fixed, deployed, and live-verified on 2026-05-14.

Problem:

- During the permission-vault proof, agent `170` was intentionally stopped
  after proving the allowed and denied vault leases.
- The stop endpoint terminated the process, but the runner later observed the
  SIGTERM exit code and overwrote the stopped bookkeeping as `failed`.

Impact:

- A deliberately stopped test-lane agent can look like a model/runtime failure
  in demo evidence.

Fix:

- Make the runner re-check task/agent status after the subprocess exits. If an
  operator already set the task or agent to `stopped`/`terminated`, the runner
  records an `agent_exit_after_operator_stop` audit event and does not rewrite
  the terminal state as failed.

Verification:

- Local compile passed for `api/services/agent_runner.py`.
- Local unit discovery passed: 73 tests.
- Live unit discovery passed: 73 tests.
- Agent `170` from the permission-vault proof was corrected to `stopped` /
  task `stopped` with an audit entry explaining the pre-fix SIGTERM overwrite.
- Final live verification showed `/api/agents/active` count `0`.

### Agent vault leases are not yet enforced at use time

Status: fixed, deployed, and live-verified on 2026-05-14.

Problem:

- Route-level RBAC can deny `/api/agents/spawn` and ticket assign-agent calls
  when `DASHBOARD_AUTH_MODE` and `DASHBOARD_AUTH_ENFORCEMENT=enforce` are set,
  but the authenticated subject is not consistently passed into
  `agent_runner.spawn_agent`.
- If `record_agent_permission_context` detects requested permissions broader
  than the spawner, the current snapshot path records a denial event but the
  agent does not yet have a dedicated per-agent vault/lease manifest that
  controls which credential references it may use for each system.

Impact:

- The dashboard can demonstrate audit-only agent permission snapshots, but it
  does not yet strictly prove that spawned agents receive only their own
  credential leases, work inside allowed system/resource scope, hit a permission
  wall for forbidden systems/actions, document the denial, and request access
  instead of silently overreaching.

Fix:

- Pass the evaluated request subject from middleware into agent-spawn routes.
- Record the bounded permission snapshot for every spawned agent, trimming or
  rejecting individual requested permissions from the effective agent envelope
  without preventing the agent from spawning.
- Create a per-agent vault manifest that contains only scoped credential
  references and lease metadata. Do not inject a single dashboard auth header
  into generic curls, because different provider systems require different
  credentials and scopes.
- Add a broker/API path that evaluates vault lease requests per agent, system,
  resource, and action. Allowed requests return the scoped vault reference;
  denied requests return a real access-denied response and audit entry so the
  agent can create an account-access request.
- Add tests proving lower-privilege agents can spawn, can access allowed ticket
  scope through their vault leases, are blocked from forbidden system/resource
  leases, and can record/request access after the denial.

Verification:

- Local compile passed for access-control service, ticket/agent/change routes,
  app middleware, and the permission-vault smoke script.
- Local unit discovery passed: 73 tests.
- Live enforcement proof marker `PERMISSION_VAULT_E2E_1778761664` passed:
  Dev Y ticket `480`, Dev Z ticket `481`, test agent `170`, allowed GitLab
  lease `dev-y/*`, denied GitLab lease `dev-z/app`.
- `access_decision_log` recorded both `agent_vault_lease_match` allow and
  `missing_agent_vault_lease` deny for agent `170`.
- Live post-deploy checks passed: 73 unit tests, platform doctor 18/18, auditor
  smoke OK, and active agents count `0`.

## Current Operational Caveats

### Agent can complete ticket evidence but leave task running

Status: fixed and live-verified on 2026-05-14.

Problem:

- During the real local-model phishing smoke for ticket `452`, agent `165`
  completed change `132`, wrote final resolution note `854`, and closed the
  ticket, but the dashboard still showed the agent task `162` as `running` with
  stale checkpoints at `40%`.
- The agent heartbeat continued, so this was not a dead process by percent
  alone. It is a terminal bookkeeping gap after the substantive work succeeded.

Impact:

- Demo and audit views can look wrong even when the actual ticket, note, and
  change evidence prove the work completed.
- The capped local-model lane can remain occupied until an operator stops the
  completed-but-not-finalized test agent.

Fix:

- Terminal evidence detection now counts final notes posted with `source=agent`,
  `source LIKE 'agent%'`, or `author=agent-<id>`.
- The agent auditor now calls a narrow terminal-evidence recovery helper for
  running ticket-resolution tasks. The helper only finalizes the task when the
  ticket is closed/resolved, no change gates remain open, and final evidence
  notes plus completed change/postmortem evidence exist.

Verification:

- Agent `166` worked ticket `472` end to end, wrote triage note `882`,
  no-containment note `883`, final resolution note `884`, and closed the ticket
  with note `885`.
- The explicit auditor run returned OK and finalized agent `166` / task `163`
  from terminal evidence: agent status `finished`, task status `completed`,
  progress `100%`, and `/api/agents/active` returned `0`.

### Agent auditor smoke returns HTTP 500 after terminal recovery change

Status: fixed and live-verified on 2026-05-14.

Problem:

- After deploying terminal-evidence recovery, the deterministic
  `scripts/smoke_agent_auditor.py` check failed on
  `POST /api/agents/audits/run` with HTTP 500.

Impact:

- The standalone auditor smoke cannot prove supervision health until the route
  traceback is fixed.
- The run stopped before the remaining deterministic smokes, so the full
  acceptance pass must be rerun after the fix.

Fix:

- The traceback was in `_recent_manual_completion_skip`: asyncpg inferred the
  `$3::text` interval parameter as text, but the helper passed integer `3600`.
- A second traceback appeared in `_detect_completed_ticket_resolution` for the
  `$4::text` author match because the helper passed integer `agent_id`.
- Both helpers now pass explicit strings for text-cast parameters.

Verification:

- Local full unit sweep: `python -m unittest discover -s tests -p "test_*.py"`
  passed with 70 tests.
- Live `POST /api/agents/audits/run` returned `{"status":"ok","audited":4}`.

### Agent supervisor repeats manual-completion skip events for old gates

Status: fixed, deployed, and regression-tested on 2026-05-14.

Problem:

- The live dashboard recent activity stream repeatedly logs
  `change_auto_complete_skipped` for older manual-completion gates such as
  changes `97`, `98`, `99`, and `127`.

Impact:

- This does not indicate an active agent is running, but it makes the audit feed
  noisier and can obscure more important recent actions during demos.

Fix:

- The supervisor now rate-limits duplicate manual-completion skip events per
  change/task for one hour while preserving the first clear audit record
  explaining why manual completion is required.

Verification:

- `tests.test_agent_lifecycle_guards.AgentLifecycleGuardTests.test_manual_completion_skip_dedupe_uses_event_log_window`
  confirms the event-log dedupe query uses the one-hour window and string-cast
  parameters expected by asyncpg.

## Fixed In Current Pass

### Runtime image does not include repo-level unit tests

Status: documented on 2026-05-13.

Problem:

- During the agent timing/status deployment, `docker compose exec -T api python
  -m unittest tests...` failed with `ModuleNotFoundError: No module named
  'tests'`.
- The API container is a production runtime image and does not include the
  repository-level `tests` package.

Impact:

- Deployment verification can look failed if operators try to run repo tests
  from inside the API container.

Resolution:

- Run syntax checks inside the container for deployed API files.
- Run repo-level unit discovery from the remote project host path:
  `cd /home/cereal/SOC_TESTING/soc-dashboard && python3 -m unittest discover
  -s tests -p 'test_*.py'`.

Verification:

- Remote host targeted tests passed: 25 tests.
- Remote host full unit discovery passed: 62 tests.

### FedRAMP-grade dashboard access control was only scaffolded

Status: fixed, deployed, provider-matrix verified, and agentically verified on 2026-05-14.

Problem:

- Dashboard users and roles existed, but route enforcement, user scopes,
  classification boundaries, and per-agent permission snapshots were not ready
  for a FedRAMP-style least-privilege cutover.
- Agents did not yet have an explicit stored policy snapshot proving they could
  not receive permissions beyond the user or workflow that spawned them.

Impact:

- The lab dashboard could demonstrate audit and approvals, but it could not yet
  prove strict need-to-know separation between teams, organizations,
  classifications, or provider-specific ticket scopes.

Fix:

- Added local additive migration `013_fedramp_access_controls.sql`.
- Added `api/services/access_control.py` with route-permission mapping,
  role-capability evaluation, classification ordering, and agent permission
  subset checks.
- Added default-off middleware so deployment can start in audit-only mode and
  move to enforcement mode after identity/provider testing.
- Documented the cutover plan in `docs/FEDRAMP_ACCESS_CONTROL_PREP.md`.

Verification:

- Added local unit tests for route permission mapping and the agent
  "cannot exceed spawner" permission boundary.
- Live provider matrix `PERMISSION_PROVIDER_MATRIX_1778766486` verified
  row-scoped ticket denial, permission trimming, and iTop sync behavior.
- Live first-alias proof `AGENTIC_PERMISSION_VAULT_1778778629` verified an
  agent spawned under Dev Y could not use Dev Z credentials until an approved
  access request minted a scoped vault lease.

### Agent timing labels made gate wait look like wasted runtime

Status: fixed, deployed, and regression-tested on 2026-05-14.

Problem:

- Agent cards still showed separate `Runtime`, `Work`, and `Gated` fields.
- Stalled agents could report increasing wall-clock/runtime fields even though
  a stalled agent is not doing useful work.
- Agents blocked behind approvals, access grants, or requester replies were not
  grouped clearly, so a wait-gated run could look like an overlapping active or
  stalled category.

Impact:

- Demo viewers could misread approval/user wait as agents wasting compute.
- Operators could miss that an agent was legitimately waiting behind a gate
  instead of actively running or silently stalled.

Fix:

- The Agents tab now shows only `Total work time` on cards.
- Stalled agents return zero `idle_seconds`, `running_seconds`, and
  `task_working_seconds` from `/api/agents`.
- Queued agents and wait-gated agents are rendered in distinct sections before
  stalled/history agents.

Verification:

- Added frontend regression coverage for queue/wait sections and removal of
  `Runtime` / `Gated` labels.
- Added route regression coverage proving stalled timing fields are zeroed in
  the `/api/agents` query.
- Local and remote full unit discovery passed with 82 tests on 2026-05-14.

### Agent completion implicitly resolved tickets

Status: fixed, deployed, and regression-tested on 2026-05-14.

Problem:

- `agent_runner` and `task_tracker` treated completed ticket-resolution tasks as
  permission to set the parent ticket to `resolved` and close the iTop provider
  record.
- That made a harness lifecycle event equivalent to a business/workflow
  decision.

Impact:

- Deployments that require a human review layer after agent work could have
  tickets closed too early.
- Source-repair, postmortem, workflow-build, and partial remediation tasks could
  look complete at the ticket level even when the intended workflow required
  a human verifier or follow-up.

Fix:

- Agent/task completion now only completes agent bookkeeping and approved
  agent-linked changes.
- Ticket status changes are explicit through `POST /api/tickets/{ticket_id}/status`.
- Agents are prompted to default to calling that endpoint when they are
  confident the work is complete, all gates/evidence are done, and no
  human-review/wait-state policy says to leave the ticket open.
- External provider closure is opt-in through `close_provider: true` on the
  explicit status update.

Verification:

- Added regression coverage proving successful agent completion and checkpoint
  completion no longer issue `UPDATE tickets SET status = 'resolved'`.
- Added status endpoint tests proving canonical status updates do not close the
  provider unless `close_provider=true`.
- Added prompt regression coverage proving the default workflow contract is
  agent-initiated closure, while human review remains an explicit opt-out.
- Local and remote full unit discovery passed with 82 tests on 2026-05-14.

### Agent runtime advertised git but did not install git

Status: fixed, deployed, and regression-tested on 2026-05-14.

Problem:

- Dashboard agents were allowed to run `Bash(git *)`, and source/CI/CD workflows
  require git for diffs, patch artifacts, GitLab remediation, and audit
  evidence.
- The API/agent Docker image installed curl, procps, Node, and Claude Code but
  did not install the `git` binary.
- During ticket `442`, agent `159` successfully diagnosed and fixed the failing
  source test, but its required `git diff` evidence command failed with
  `Exit code 127` / `git: command not found`.

Impact:

- CI/CD and GitLab remediation agents could repair files but fail to produce
  normal git evidence inside the runtime.
- Source self-repair demos could look incomplete even after compile and unit
  tests passed.

Fix:

- Add `git` to the API/agent runtime image in `api/Dockerfile`.
- Add a regression test asserting the runtime image installs git.
- Add a reusable source self-repair marker utility and test so future agentic
  source-edit proofs have a tiny deterministic target.

Verification:

- Ticket `442`, agent `159`, task `156`, and change `128` proved the agentic
  source edit itself end to end: approval was requested and approved, the agent
  created `scripts/agentic_self_repair_marker.py`, compile passed, unit test
  passed, note `770` was written, and checkpoint finished at `done` / `100%`.
- The remaining git evidence gap is now covered by local regression test
  `tests/test_agentic_self_repair_marker.py`.
- Local and remote full unit discovery passed with 82 tests on 2026-05-14.

### Postmortem SLA metrics did not track postmortem completion

Status: fixed, deployed, and agentically verified on 2026-05-13.

Problem:

- `GET /api/dashboard/ops-metrics` reported ticket SLA compliance from
  ticket create-to-resolution time only.
- The dashboard did not separately measure whether resolved tickets received a
  required postmortem within the expected learning/review window.
- This made postmortem follow-through look healthy even when a ticket was
  resolved without a timely postmortem artifact.

Impact:

- Demo and operations views could overstate SLA health for agentic work because
  the learning/postmortem phase was invisible to SLA tracking.
- Agents and operators could miss delayed or missing postmortems after ticket
  resolution.

Fix:

- Add `postmortem_sla` metrics to `/api/dashboard/ops-metrics`, counting
  resolved tickets, tickets with postmortems, postmortems created within the
  configured window, missing postmortems, late postmortems, and compliance
  percentage.
- Render the postmortem SLA beside ticket SLA in the overview snapshot.
- Add regression coverage and live smoke assertions so postmortem SLA cannot
  silently disappear from the dashboard again.

Verification:

- Local compile, JS syntax, targeted unit tests, and full unit discovery passed.
- Live AI server compile, JS syntax, targeted unit tests, and
  `scripts/smoke_operational_metrics.py http://127.0.0.1:25480` passed after
  deployment.
- Real local-model self-repair proof completed through dashboard ticket `440`,
  agent `157`, task `154`, and approval gate `126`.
- Agent `157` verified `postmortem_sla` values, completed the approved gate,
  wrote evidence note `755`, updated checkpoint `done` at `100%`, and resolved
  the ticket.

### Agent prompts allowed inline JSON patterns that the shell guard rejects

Status: fixed and deployed on 2026-05-13.

Problem:

- During ticket `440`, agent `157` twice attempted POST payloads with inline
  JSON or multiline Python-in-shell commands that triggered the shell guard:
  `Contains brace with quote character` and `Newline followed by # inside a
  quoted argument`.
- The agent recovered on its own by using the Write tool to create JSON payload
  files, then `curl -d @payload.json`, but the reusable prompts did not teach
  that pattern.

Impact:

- Slow local agents could waste minutes recovering from preventable shell-guard
  errors during approval gates, ticket notes, change completion, and other
  control-plane writes.

Fix:

- Added reusable prompt guidance in `task_prompts.py` and the agent-runner
  wrapper prompt: for POST payloads, create a JSON file with the Write tool and
  call `curl -d @payload.json`; do not use Bash heredocs or inline
  `-d '{...}'` payloads.

Verification:

- Deployed only the shell-guard prompt hunk to the AI server after confirming no
  active agents.
- Remote compile, targeted unit tests, operational metrics smoke, and health
  checks passed after rebuild.

### Agents could look complete after stopping at an access or approval wait gate

Status: fixed, deployed, and agentically verified on 2026-05-14.

Problem:

- The runner treated a zero-exit harness process as completed even when
  `checkpoint.json` said `waiting_for_access`, `pending_approval`, or another
  below-100 wait state.
- That could make a permission-blocked ticket look resolved before an access
  owner approved and granted the required role.

Fix:

- Added a wait-gate checkpoint guard in `agent_runner`. Below-100
  `waiting_for_*`, `pending_approval`, `pending_access`, `blocked`,
  `access_denied`, and `needs_access` checkpoints now leave the task and agent
  in a blocked/waiting status instead of resolving the ticket.
- Added `access_requests`, `POST /api/tickets/{id}/access-request`, and
  approval-gate synchronization so a blocked agent can create a child access
  ticket, wait for approval, and resume the original ticket after approval.
- Seeded `GitLab repository access` and `SIEM analyst access` RACI rules.

Verification:

- Unit tests and control-plane permission smokes passed locally and on the AI
  server.
- Live first-alias proof `AGENTIC_PERMISSION_VAULT_1778778629` verified the
  initial agent stopped at `awaiting_access`, the access approval spawned a
  resumed agent, and the resumed task completed from the granted lease instead
  of being marked complete at the original wait gate.

### Operational metrics, workflow review state, scanner findings, and tool inventory were demo-confusing

Status: fixed and deployed on 2026-05-13.

Problem:

- The Agents tab showed negative idle/running seconds when browser and server
  clocks diverged.
- Overview lacked working-time metrics that excluded approval/user-response
  gate wait.
- Workflow rows could show `active` while still looking like they were waiting
  on approval, and operators could not see linked tickets/test runs from the
  workflow detail.
- CI/CD run detail mixed scanner findings together and treated OWASP ZAP
  baseline exit code `2` as a scanner error instead of warnings/findings.
- Learning status labels like `promote`, `ready_for_review`, and `approved`
  were ambiguous.
- Tools did not clearly show setup modules/bridges/integrations.
- RACI rules could not easily expose automatic agent assignment policy.

Fix:

- Added `GET /api/dashboard/ops-metrics` with agent working time, gate wait,
  SLA compliance, approval gate wait, workflow run counts, CI/CD counts,
  auto-assignment counts, and tool health.
- Agents now return server-derived nonnegative `idle_seconds`,
  `running_seconds`, `task_working_seconds`, and `gate_wait_seconds`.
- Workflows now expose `review_state`, run counters, linked ticket/test runs,
  and a reviewed rerun API for tested/active workflows.
- CI/CD run detail now normalizes scanner names, groups findings by scanner,
  always shows Semgrep/Trivy/OWASP ZAP/Nuclei result slots, and maps ZAP code
  `2` to `completed_with_findings`.
- Learning labels now say Draft / Ready For Review / Approved Learning /
  Assets Created with plain hints.
- Tools now render both health-checked tools and setup modules; ComfyUI remains
  hidden from the operator tools dashboard.
- RACI CRUD now exposes the `auto_assign_agent` hook and default model/prompt.

Verification:

- Local compile: `python -m py_compile api\routes\agents.py
  api\routes\dashboard.py api\routes\workflows.py api\routes\cicd.py
  api\routes\tools.py`: PASS.
- JavaScript syntax: `node --check frontend\js\dashboard.js` and companion
  frontend files: PASS.
- Unit tests: `python -m unittest discover -s tests -p "test_*.py"`:
  43 tests PASS.
- Live smoke: `python scripts\smoke_operational_metrics.py
  http://192.168.50.222:25480`: PASS, created CI/CD run `26`,
  verified `zap_status=completed_with_findings`, four scanner summary groups,
  `setup_modules=38`, and no negative agent timing fields.

### Bridge E2E tests can falsely fail when launched outside their configured context

Status: documented and rerun correctly on 2026-05-13.

Problem:

- Running `/home/cereal/SOC_TESTING/siem-ticket-bridge/tests/test_ticket_e2e.py`
  directly from an unrelated working directory did not load the bridge `.env`
  and reported `SIEM connected: False`, `Ticketing connected: False`.

Impact:

- The bridge looked broken even though the service and connectors were healthy.

Fix:

- Treat bridge tests as context-sensitive: run from the bridge directory with
  `PYTHONPATH=.` and load `.env` for live connection/E2E tests.

Verification:

- `cd /home/cereal/SOC_TESTING/siem-ticket-bridge && PYTHONPATH=. python3 -m
  unittest tests.test_bridge -v`: 41 tests PASS, 3 live tests skipped.
- `source .env && PYTHONPATH=. python3 -m siem_ticket_bridge.bridge
  --test-connection`: Wazuh and iTop connected, `error_count=0`.
- `source .env && PYTHONPATH=. python3 tests/test_ticket_e2e.py`: PASS;
  direct iTop ticket `267` created.
- SOC bridge suites: 11 + 22 + 13 tests PASS.
- IAM bridge: 23 tests PASS.
- Keycloak-Mailcow bridge: 47 PASS, 1 expected skip.
- Mailcow API shim: 10 tests PASS.
- Keycloak manager: 26 tests PASS.

### Ticket close proof v2 was local-only despite end-to-end wording

Status: fixed and verified, found from marker
`CODEX_TICKET_CLOSE_PROOF_V2_1778629496` / dashboard ticket `342`.

Problem:

- The test created ticket `342` with `provider=local`,
  `sync_provider=false`, and `provider_sync_status=local_only`.
- The title claimed "controlled agent completion with full evidence note
  retention", but the test evidence did not include an iTop object, provider
  close, forced sync, or direct iTop read.
- iTop search for the marker returned zero matching `Incident` and
  `UserRequest` objects, which is expected for that local-only ticket.

Impact:

- The proof was valid only for local dashboard closure and note retention, not
  for end-to-end dashboard-to-iTop synchronization.
- Demo notes could overstate what was proven and hide a real provider-sync
  regression if one appeared later.

Fix:

- Replace the close proof with an iTop-backed end-to-end variant that creates
  the ticket with `provider=itop` / `sync_provider=true`, requires
  `provider_sync_status=synced`, runs the agent, forces `/api/tickets/{id}/sync`,
  and directly reads the matching iTop object to assert `resolved` plus solution
  text.

Verification:

- Replacement proof marker `CODEX_ITOP_CLOSE_PROOF_1778645781` created
  dashboard ticket `368`, synced to iTop Incident `240`, spawned local-model
  agent `131`, retained evidence notes `551` and `552`, completed task `128`,
  and direct iTop read confirmed `status=resolved` with the marker in
  `solution`.
- Final clean proof marker `CODEX_ITOP_CLOSE_PROOF_1778648936` created
  dashboard ticket `373`, synced to iTop Incident `245` / `I-000254`, spawned
  local-model agent `135`, retained evidence notes `574` and `575`, completed
  task `132`, direct iTop read confirmed `status=resolved`,
  `resolution_code=assistance`, and marker-bearing solution text, and the
  ticket notes contained zero `Provider close failed` entries.
- The replacement test is `scripts/smoke_itop_agent_close_e2e.py`; it refuses
  local-only tickets by requiring `provider=itop`,
  `provider_sync_status=synced`, a numeric provider ref, evidence notes, forced
  sync, and direct iTop state verification.

### iTop-backed ticket create can persist then return HTTP 500

Status: fixed and verified, found while replacing the local-only close proof
with marker `CODEX_ITOP_CLOSE_PROOF_1778645039`.

Problem:

- `scripts/smoke_itop_agent_close_e2e.py` called `POST /api/tickets` with
  `provider=itop` and `sync_provider=true`.
- The API returned HTTP 500, but the dashboard row was still created as ticket
  `367` with `provider=itop`, `provider_ref=239`, `itop_ref=239`,
  `provider_sync_status=synced`, and status `new`.

Impact:

- A caller can think ticket creation failed even though an iTop object exists.
- E2E tests abort before assigning the agent, leaving a synced but unworked
  ticket behind.

Fix:

- Cast provider placeholders consistently as varchar in the ticket provider
  update path so asyncpg does not infer mixed `text`/`varchar` parameter types.
- Keep outbound iTop provider metadata mirrored into both provider-neutral
  columns and legacy `itop_ref` / `itop_class` columns for older dashboard
  views and close helpers.

Verification:

- Fresh proof marker `CODEX_ITOP_CLOSE_PROOF_1778647301` created ticket `371`
  and iTop Incident `243` without HTTP 500.
- Final proof marker `CODEX_ITOP_CLOSE_PROOF_1778648936` created ticket `373`
  and iTop Incident `245` without HTTP 500; API logs after the rerun contained
  no `AmbiguousParameterError` entries.

### iTop provider close used solution fields during assignment

Status: fixed and verified, found during iTop-backed close proof marker
`CODEX_ITOP_CLOSE_PROOF_1778645039` / dashboard ticket `367` / iTop Incident
`239` / agent `130`.

Problem:

- Agent `130` completed the proof steps and wrote evidence notes `542` and
  `543`, then checkpoint note `544`.
- The dashboard resolved ticket `367` locally, but provider close failed with:
  `Invalid stimulus: 'ev_resolve' on the object I-000248 in state 'new'`.
- The fallback assignment call was sending the Incident `solution` field along
  with `ev_assign`; iTop assignment stimuli require empty fields. The solution
  belongs only on the subsequent `ev_resolve`.

Impact:

- iTop-backed dashboard tickets can remain `new` in iTop while showing
  `resolved` locally if they were never assigned before provider close.

Fix:

- Change the fallback `ev_assign` call to use empty fields, wait until iTop
  reports the object has left `new`, then retry `ev_resolve` with
  `resolution_code=assistance` and `solution` populated.
- Retry the provider close wrapper once when iTop returns a transient invalid
  stimulus/state error so the dashboard does not write a false failure note
  moments before the provider state catches up.

Verification:

- Unit coverage added for provider-ref close, empty-field assignment fallback,
  assignment-state polling before resolve retry, and transient close retry
  without writing a provider failure note.
- Live ticket `368` eventually resolved in iTop, but still produced note `554`
  from the old immediate retry path. A clean rerun after redeploy must show no
  false `Provider close failed` note.
- Clean proof marker `CODEX_ITOP_CLOSE_PROOF_1778648936`: ticket `373`, agent
  `135`, task `132`, iTop Incident `245` / `I-000254`; notes `572`-`577`
  retained assignment/start/evidence/checkpoint/completion with
  `provider_close_failed_notes=0`, event log has `provider_close_complete`, and
  direct iTop read returned `status=resolved`,
  `resolution_code=assistance`, and solution marker text.

### Agent auditor can miss live agents stuck after oversized evidence fetch

Status: fixed and deployed, found while preserving unrelated live agent
`132` / ticket `369`.

Problem:

- Agent `132` was heartbeating and the dashboard auditor reported
  `agent_progress_ok`, but direct task log/checkpoint inspection showed it had
  only read `checkpoint.json`, fetched a large
  `/api/postmortems/evidence/369?task_log_lines=0` payload, and left
  `checkpoint.json` at `init`.
- The audit endpoint currently overweights process/heartbeat freshness and does
  not treat unchanged checkpoint state plus no new output as a distinct
  "needs steering" condition.

Impact:

- Slow local-model agents can appear healthy while actually stalled on oversized
  context or analysis, and the UI percent can remain misleading.

Fix:

- Add auditor logic that compares checkpoint timestamp/step, task-log growth,
  and recent ticket notes before declaring progress healthy.
- Rank and trim postmortem evidence workflows/knowledge by ticket terms so an
  EDR/Sysmon ticket is not handed mostly phishing artifacts just because all
  assets are `Incident` class.
- Keep this as a corrective watchdog, not a hard timeout: it should write a
  review finding and optionally steer/restart through explicit policy while
  exempting approval gates and user-response waits.

Verification:

- Local validation added for Sysmon evidence term extraction, relevance ranking,
  and stale-checkpoint auditor findings.
- Agent `132` was stopped through the dashboard API with explicit audit reason
  after repeated inspection showed heartbeat/output but no checkpoint progress
  or agent triage notes; no raw process kill was used.
- Rebuilt the live API with `agent_checkpoint_not_advancing` and ranked compact
  evidence enabled. Final close proof then completed with no active-agent
  leftovers.

### Agent audit history lacked terminal completion review

Status: fixed and deployed, found while auditing ticket `366` / agent `129`
after the successful workflow-reuse run.

Problem:

- `POST /api/agents/audits/run` worked and did not restart or duplicate the
  completed agent, but the visible audit history for agent `129` only showed an
  earlier `agent_progress_ok` row from when task `126` was still running.
- Because `/api/agents/audits` joins current agent status onto historical audit
  rows, the UI/API could show `agent_status=finished` beside old details like
  `task_status=running`.

Impact:

- Demo and operator review can be confusing: the agent really finished, but the
  latest audit artifact does not prove terminal completion or closure evidence.

Fix:

- Add a terminal `agent_task_completed` audit finding for recently completed
  tasks with ticket status, open/completed change counts, postmortem count, and
  final progress.

Verification:

- Local validation: `python -m py_compile api\services\agent_auditor.py` and
  `python -m unittest tests.test_agent_auditor
  tests.test_agent_lifecycle_guards tests.test_auto_assignment
  tests.test_itop_sync_status` passed.
- Rebuilt the live API after confirming `/api/agents/active` returned zero.
- Reran `/api/agents/audits/run`; it audited six recently completed tasks and
  created audit review `333` for agent `129` with
  `finding=agent_task_completed`, `task_status=completed`,
  `ticket_status=resolved`, `progress_pct=100`, `open_changes=0`,
  `completed_changes=3`, and `postmortems=1`.

### Postmortem create endpoint rejected list-shaped text fields

Status: fixed and deployed, found during workflow reuse proof ticket `366` /
agent `129` / task `126`.

Problem:

- Agent `129` completed triage, approval gates, lab-safe containment evidence,
  and final resolution on phishing ticket `366`, then attempted to persist the
  postmortem at `2026-05-13T03:39:11Z`.
- The local model sent `improvements` as a JSON list. FastAPI rejected the
  request before route code ran because `POST /api/postmortems` annotated text
  fields as strict strings.

Impact:

- A real agent can complete the operational work but fail the learning artifact
  step, which prevents the ticket from proving the full
  ticket -> workflow reuse -> postmortem loop.

Fix:

- `POST /api/postmortems` now accepts text fields as generic JSON and normalizes
  `summary`, `went_well`, `improvements`, `workflow_proposal`, and
  `documentation` to strings before inserting.
- Ticket, postmortem, and runner prompts now document the exact accepted
  postmortem body fields and require text fields to be strings while arrays stay
  arrays.

Verification:

- Agent `129` self-corrected the payload shape, created postmortem `49`, set
  task `126` to `completed` / `100%`, and closed dashboard ticket `366`.
- Rebuilt the live API after confirming `/api/agents/active` returned zero
  agents.
- Live deploy smoke posted a list/dict-shaped postmortem payload, verified it
  normalized to text, then deleted only the smoke row (`postmortem 50`).
- Local validation: `python -m py_compile api\routes\postmortems.py
  api\services\task_prompts.py api\services\agent_runner.py` and
  `python -m unittest tests.test_agent_lifecycle_guards
  tests.test_auto_assignment tests.test_itop_sync_status` passed.

### Compact postmortem evidence omits active workflows

Status: fixed, deployed, and verified through workflow reuse ticket `366`,
found during post-promotion rerun ticket `365` / agent `128`.

Problem:

- Postmortem `47` was promoted into knowledge article `44`, skills `55` and
  `56`, and active workflow `46`.
- New phishing ticket `365` correctly exposed workflow `46` through
  `GET /api/tickets/365/context`.
- Agent `128` followed the bounded-evidence instruction and first called
  `GET /api/postmortems/evidence/365?task_log_lines=0`, but that compact
  evidence response did not include active workflows or promoted knowledge.

Impact:

- The reusable workflow may be active and visible in full ticket context while
  still being absent from the compact evidence path that local agents are told
  to prefer.
- This can make "postmortem -> workflow -> future ticket uses workflow" appear
  unreliable even when workflow promotion itself worked.

Fix:

- Add relevant active/tested/approved workflows, promoted postmortems, and
  knowledge articles to the compact evidence endpoint.
- Update prompts to tell agents that bounded evidence includes reusable
  workflows and must be checked before drafting a fresh plan.

Verification:

- `GET /api/postmortems/evidence/365?task_log_lines=0` returned active workflow
  `46` and knowledge article `44`.
- Fresh ticket `366` / agent `129` used compact evidence first, saw workflow
  `46`, followed it, completed gates `106`-`108`, wrote resolution note `537`,
  created postmortem `49`, and closed the ticket.
- Forced dashboard sync and direct iTop read confirmed dashboard ticket `366`
  and iTop Incident `238` / `I-000247` were both `resolved`.

### Acceptance reruns could hit API before restart finished

Problem:

- A live provider-adapter smoke rerun immediately after `docker compose restart api`
  hit `/api/providers` before Uvicorn was fully ready and raised
  `ConnectionResetError: [Errno 104] Connection reset by peer`.

Fix:

- Acceptance scripts and manual reruns should wait on `/health` after restarting
  the API before calling route-level smoke tests.

Verified:

- Rerun command waited on `/health` and completed provider-adapter smoke after
  the API rebuild/recreate sequence.

### Python service hot uploads do not change the running API container

Problem:

- Uploading `api/services/auto_assignment.py` to the live host source tree and
  restarting the API container did not change the code running inside `/app`.
- The API image bakes Python service files at build time; only selected volumes
  such as frontend, platform, skills, and agent work are mounted.

Impact:

- A policy fix can appear deployed on the host but still run old code until the
  API image is rebuilt.

Fix:

- For Python API/service/route changes, run `docker compose up -d --build api`
  after updating the host source.
- Keep simple restarts for frontend/skill/config changes that are actually
  mounted into the container.

Verified:

- Rebuilt API with `docker compose up -d --build api`.
- Container-side `_score_rule` returned `{'class_only_score': 0}`.
- `python3 scripts/smoke_provider_adapters.py http://localhost:25480` created
  ticket `174` and `GET /api/agents/active` remained empty afterward.

### Change auto-completion smoke command used the wrong container path

Status: fixed during the 2026-05-12 full acceptance regression pass.

Problem:

- The full regression command tried to run `python smoke_change_auto_completion.py`
  inside the API container.
- The script lives under `scripts/` in the source tree and is not mounted into
  `/app` by the running API container.

Impact:

- Baseline regression stopped at the approved-change auto-completion check even
  though earlier platform doctor, provider, intake, workflow, CI/CD, and auditor
  smokes passed.

Fix:

- Document the correct pattern: copy `scripts/smoke_change_auto_completion.py`
  into the API container, then run `/app/smoke_change_auto_completion.py`.
- Updated the acceptance command script to use the same copy-and-run pattern.

Verified:

- `docker compose cp scripts/smoke_change_auto_completion.py api:/app/smoke_change_auto_completion.py`: PASS.
- `docker compose exec -T api python /app/smoke_change_auto_completion.py`: PASS
  with ticket `172`, agent `76`, task `74`, change `82`, and
  `change_status=completed`.

### `ps` missing in API container

Problem:

- Agent process diagnostics could not work in the slim Python image.

Fix:

- API image installs `procps`.
- `/api/agents/processes` now reports `ps_path=/usr/bin/ps`.

### Wake/restart were not trustworthy enough

Problem:

- UI could show running/wake/restart state without proving a harness process existed.

Fix:

- Wake now checks active tasks and either refreshes heartbeat or spawns a replacement.
- Restart stops active task, terminates old agent row, and spawns replacement.
- Process diagnostics expose actual runner process state.

### Claude Code allowed-tools command ordering

Problem:

- Putting `--allowedTools` late in the command caused it to swallow the prompt because it is variadic.

Fix:

- `agent_harness.py` puts `--allowedTools` before `-p`.

### Full bypass refused as root

Problem:

- Claude Code refuses bypass mode from the current root-run API container.

Fix:

- Managed agents use `acceptEdits` and `Read,Write,Bash(curl *)`.

### Model process kept running after useful completion

Problem:

- Agent could write done checkpoint while the Claude process kept consuming GPU.

Fix:

- `task_tracker` completes the task from the done checkpoint and terminates the harness process.

### Docker-host style model route avoided

Problem:

- Docker networking aliases are fragile in this lab.

Fix:

- `AGENT_LLM_BASE_URL` uses routable LAN proxy URL, currently `http://192.168.50.222:4001`.

### Fresh DB init missing new approval columns

Problem:

- `init_db.sql` had older `change_requests` columns while route code writes `risk_level` and `approval_policy`.

Fix:

- Fresh schema now includes both columns.
- Existing deployments still use migration 003.

### iTop hardwired in compose

Problem:

- `docker-compose.yml` pinned `ITOP_HOST` to the lab IP and required iTop credentials.

Fix:

- `ITOP_HOST`, `ITOP_USER`, and `ITOP_PASSWORD` are environment-driven.
- `ITOP_SYNC_ENABLED=false` supports local-only/non-iTop deployments.

### Dashboard-created provider tickets did not actually push outward

Problem:

- `sync_provider=true` only marked tickets `pending_create`.

Fix:

- Added provider `create_ticket` contract.
- Added local provider create/push.
- Added guarded iTop outbound create.
- Added `POST /api/tickets/{id}/push-provider`.

### Non-iTop tickets could get iTop-shaped URLs

Problem:

- URL generation assumed iTop when refs looked non-local.

Fix:

- `external_ticket_url()` now returns provider URL first and only builds iTop URLs for iTop tickets.

### ComfyUI should not be in tool dashboard

Fix:

- Default tools omit ComfyUI.
- `init_db.sql` deletes existing ComfyUI row if present.

### Demo credentials were inconsistent across platforms

Problem:

- `/home/cereal/multiplatform_user_manager.py` had hardcoded iTop/Mailcow DB passwords, shell-expanded password hashes, a Wazuh scrypt salt mismatch, and no Wazuh Dashboard internal-user sync.
- `demo_account_1` worked in some backing databases but failed real auth checks.

Fix:

- Removed hardcoded DB passwords; iTop/Mailcow credentials now resolve from container environment or explicit env vars.
- Reworked SQL execution to stream SQL over stdin, avoiding bcrypt/scrypt `$` shell expansion.
- Switched Wazuh to native API updates first, with RBAC SQLite as fallback, and added Wazuh Dashboard OpenSearch Security sync.
- Rebuilt the iTop demo account as a valid `UserLocal` object with `Administrator` and `REST Services User` profiles.
- Rotated vault key `demo_account_1` and scrubbed the old failed debug password from iTop `error.log`.

Verified:

- iTop REST login returns `code:0`.
- Wazuh API auth returns HTTP 200.
- Wazuh Dashboard backend auth recognizes `demo_account_1`.
- GitLab Rails `valid_password?` passes and the account is active/admin.
- Mailcow mailbox exists.

### Agent timeout default could kill valid local-model runs

Problem:

- Local 256k-context runs can legitimately take a long time, and a fixed harness timeout can kill useful work while the model is still generating.

Fix:

- Installer, compose defaults, and `.env.example` now default `AGENT_TIMEOUT_MINUTES=0`.
- Local-model deployments should default to `MAX_CONCURRENT_AGENTS=1` until faster models are available. This prevents queued work from saturating the model and creating false stalled-agent symptoms.
- `AGENT_NO_OUTPUT_STALL_SECONDS` is configurable and defaults to `3600` for this environment. It is a last-resort silent-harness guard, not a short task timeout; agents that are streaming output or using tools should continue.
- The agent auditor is the supervision path and defaults to `AGENT_AUDITOR_AUTO_RECOVER=false` so recovery is auditable before being made automatic.
- Existing deployments can run `python3 scripts/repair_agent_supervision_env.py --env-file .env`, then recreate the API container.

### Agent note API dropped evidence when local agents used `content`

Problem:

- A real local-agent closure proof on ticket `340` completed and resolved the
  ticket, but the agent used `content` in `POST /api/tickets/340/notes`.
- The route accepted `body`, `note`, and `title` only, so notes `420` and `421`
  stored the titles without the detailed evidence body.

Fix:

- `POST /api/tickets/{ticket_id}/notes` now accepts `content` as a compatibility
  alias and combines it with `title` the same way it already handled `body` and
  `note`.
- Added unit coverage in `tests/test_agent_lifecycle_guards.py`.

Verified:

- Direct API proof ticket `341` created note `424` with title and full `content`
  body retained.
- Real local-agent closure proof V2 created ticket `342`, agent `113`, task
  `110`, notes `427` and `428` with full evidence bodies, checkpoint note `429`,
  completion note `430`, and final ticket status `resolved`.

### SIEM bridge EDR fanout can create too many local agents

Problem:

- A successful EDR/Sysmon rerun created multiple bridge tickets for closely
  related marker alerts, then RACI auto-assignment spawned agents for each.
- That behavior proves the bridge and auto-assignment hooks work, but it can
  saturate the current one-local-model lab and obscure the single incident
  narrative in demos.

Fix:

- The SIEM bridge now stores `ticket_correlation_keys` in bridge state.
- Exact alert dedup still works as before, while cross-rule correlation collapses
  alerts with an explicit `correlation_key` or marker such as `CODEX_*` into the
  first ticket for that incident.
- Added unit coverage proving two Sysmon marker alerts with different rules but
  the same marker produce one ticket and one correlated event.
- RACI auto-assignment now also enforces
  `AUTO_ASSIGNMENT_MAX_ACTIVE_PER_RULE=1` by default so related EDR/SIEM tickets
  do not queue several same-rule local agents while one matching agent is
  already active.

Verified:

- Recovery marker `CODEX_SYSMON_E2E_RECOVERY_1778630817` produced two Wazuh
  alerts but one bridge correlation key after the next poll.
- Live cap proof tickets `351` and `352` showed the first same-rule ticket
  assigned agent `122`; the second skipped with
  `auto_assignment_capacity_reached`. The proof agent was stopped immediately
  after verification.

### Mailcow HTTP API shim missing compatibility pieces

Full blueprint and runbook: `docs/MAILCOW_API_SHIM.md`.

Problem:

- The optional Mailcow HTTP API shim could reject valid API keys or return empty bodies because nginx did not forward `X-API-Key` into FastCGI and the mounted web code expected an `identity_provider` table.
- The stock `json_api.php` path can still return HTTP 200 with empty bodies for `get/domain/all` and `get/alias/all`, or `{}` for `get/mailbox/all`, in the custom reference deployment even though direct MySQL contains real data.

Fix:

- `deploy_mailcow_api.py` now forwards `HTTP_X_API_KEY`, sets `HTTP_SEC_FETCH_DEST=empty`, preserves content type, creates the `identity_provider` compatibility table, and stops printing API keys.
- The API shim now installs `mailcow_compat_api.php` and routes read-only `GET /api/v1/get/domain/*`, `GET /api/v1/get/mailbox/*`, and `GET /api/v1/get/alias/*` calls through that compatibility endpoint when the stock API path is unreliable.
- The compatibility endpoint validates `X-API-Key` against the Mailcow `api` table, uses the Mailcow DB connection from mounted Mailcow config/environment, and intentionally omits mailbox password hashes from responses.
- Invalid keys must return HTTP 401 during verification.
- Existing deployments that have shim containers but no restricted key file can run `bash scripts/repair_mailcow_api_keyfile.sh`.
- Fresh or repaired deployments should run `python3 scripts/deploy_mailcow_api.py`, then `python3 scripts/test_mailcow_api_shim.py --mysql-parity`.

Current note:

- Direct MySQL remains the canonical Mailcow bridge fallback for the reference deployment. The HTTP API shim is now usable for read-only compatibility checks and future provider-style tooling.
- The deployer no longer requires host-side `MYSQL_ROOT_PASSWORD`; it runs SQL inside the `mysql-mailcow` container using the container-held environment and writes the API key only to the restricted `api-nginx/.api_key` file.

Verified:

- Invalid API key returns HTTP `401`.
- Valid API key returns HTTP `200` with `2` domains, `11` mailboxes, and `6` aliases.
- Direct MySQL smoke confirms the same underlying counts.
- 2026-05-12 regression: `test_mailcow_api_shim.py --mysql-parity` passed `13/13`; platform doctor passed `18/18`; Keycloak-Mailcow bridge E2E passed `47/48` with `1` expected skip for the undeclared Keycloak custom attribute.

### Sysmon EDR test required manual secret injection

Problem:

- The EDR/Sysmon E2E test defaulted secret fields to empty strings and used POST for read-only Wazuh Indexer endpoints.

Fix:

- The test now reads deployed container/env-file values when explicit environment variables are absent, does not print secrets, uses GET for read-only indexer checks, and fixes the iTop REST URL encoding path.

### Sysmon EDR was green but not ingesting fresh endpoint telemetry

Problem:

- The old EDR/Sysmon test proved Wazuh, rules, iTop, and bridge primitives, but
  it did not prove current Sysmon events were reaching Wazuh alerts.
- SysmonForLinux was writing syslog-prefixed XML to
  `/var/log/sysmon/sysmon.log`.
- Wazuh was configured with `<log_format>json</log_format>` for that file.
- After changing the parser, the 15GB historical hot log filled the Wazuh
  logcollector queue and delayed fresh alerts.
- A later deployment pass exposed additional reality: the reference Linux
  Sysmon config used wrapper-style elements that SysmonForLinux v1.5.1/schema
  4.90 rejects, the generated systemd unit started the binary without the
  service install arguments, and the exact marker rule was standalone instead
  of a child of the level-0 Sysmon catch-all.

Fix:

- Wazuh Sysmon localfile now uses `<log_format>syslog</log_format>`.
- The oversized hot log was moved to a timestamped archive and a fresh hot log
  was created.
- `deploy-sysmon-linux.sh` now targets `/var/log/sysmon/sysmon.log` and installs
  a logrotate policy.
- `deploy-sysmon-linux.sh` now installs `rsyslog`, writes an early
  `/etc/rsyslog.d/10-sysmon-forward.conf`, validates/reinstalls SysmonForLinux
  through the Microsoft binary's own `-i <config>` flow, and avoids hand-written
  bad service units.
- `sysmon_config_linux.xml` now uses SysmonForLinux 4.90-compatible filters.
- `sysmon_decoder.xml` was reduced to a valid minimal decoder; the invalid
  `<location>` decoder was removed from the live manager.
- Rule `100230` is now the exact-marker child of base Sysmon rule `100200` for
  real Sysmon XML events, and rule `100231` is a raw-marker fallback for manager
  diagnostics. This preserves the real file-create E2E path while still making
  direct marker injection easy to test.
- `deploy-edr.sh` now detects when the live manager already has the broader
  Sysmon rule set in `local_rules.xml` and installs only
  `sysmon_marker_rules.xml` in that case, avoiding duplicate rule warnings.
- The E2E test now generates a unique `/tmp/CODEX_SYSMON_*.txt` file and
  verifies that exact marker in Wazuh Indexer.

Verified:

- Dashboard changes `37` and `38` were approved and completed.
- Wazuh EDR/Sysmon E2E passes `16/16`.
- 2026-05-12 regression passed with exact marker
  `CODEX_SYSMON_E2E_1778567257`, two alerts in Wazuh Indexer, `271` Sysmon
  rules searchable, Wazuh Indexer green, iTop API authenticated, live decoder
  shape verified for Wazuh 4.14, and bridge state valid.
- Logtest confirmed the XML Sysmon file-create marker fires rule `100230`.
- Logtest no longer emits duplicate Sysmon rule warnings after the marker-only
  live-manager install path.

### Legacy live test scripts drifted from current providers

Problem:

- `report_phish/test_reporter.py` imported old backend factory names that are
  no longer exported after the internal Mailcow SMTP backend became canonical.
- `itop-deployment/scripts/test_itop.py` and `test_approval_chain.py` assumed
  outdated iTop classes/fields (`Request`, `Problem`, `risk`, missing `org_id`,
  and missing `fallback` for `ev_plan`).
- `wazuh_deploy/test_wazuh.py` required pytest and embedded credentials.
- `log_forwarder/test_logtest.py` called `/var/ossec/bin/wazuh-logtest` on the
  host even though Wazuh runs in the manager container.
- `report_phish/backends/internal_email.py` defaulted Wazuh credentials to
  placeholder strings, causing an avoidable Wazuh auth failure during a
  successful internal Mailcow report.

Fix:

- Replaced `test_reporter.py` with a compatibility test around
  `PhishReporter` + `InternalEmailBackend`.
- Replaced the iTop tests with current-schema tests for Organization, Team,
  Person, Incident, UserRequest, NormalChange approval, and Incident pending.
- Replaced `test_wazuh.py` with a stdlib-only test that reads Wazuh credentials
  from the running container environment and does not print or store secrets.
- Updated `log_forwarder/test_logtest.py` to execute
  `/var/ossec/bin/wazuh-logtest` through `docker exec -i
  wazuh_deploy-wazuh.manager-1`.
- Updated the report-phish internal backend so Wazuh forwarding is enabled only
  when `WAZUH_API_PASSWORD` is supplied, with user/password read from
  environment variables instead of placeholders.

Verified:

- `report_phish/test_reporter.py`: passed.
- `itop-deployment/scripts/test_itop.py`: passed.
- `itop-deployment/scripts/test_approval_chain.py`: passed, including
  `ev_plan`, `ev_approve`, `ev_implement`, and incident `ev_pending`.
- `wazuh_deploy/test_wazuh.py`: passed.
- `log_forwarder/test_logtest.py`: passed.
- `report_phish/test_report.py`: passed with Wazuh forwarding explicitly
  disabled when no Wazuh credential env is present.

### Full CI/CD demo found scanner wrapper edge cases

Problem:

- The full local-model remediation run originally ended with a `needs_review`
  gate even after the agent fixed the intended source vulnerabilities.
- The Trivy Docker call passed `trivy fs ...` into an image whose entrypoint is
  already `trivy`.
- OWASP ZAP baseline returned exit code `2`, which means warnings were present,
  but the wrapper treated it as a scanner execution failure.

Fix:

- Docker Trivy invocations now pass `fs ...`.
- ZAP exit code `2` is treated as completed-with-findings.
- The gate status is decided by finding severity, with high/critical findings
  blocking production deployment and low/medium warnings recorded as evidence.

Verified:

- Ticket `82`, final scanner run `10` passed after local-model remediation.
- Semgrep, Trivy, OWASP ZAP, and Nuclei all completed.
- Change `36` was approved and completed; superseded change `35` was rejected.

### GitLab Runner CI/CD demo needed runner networking fixes

Problem:

- The first GitLab-backed demo project created a pipeline that stayed pending
  because the project runner was not attached to the new project.
- Docker job containers could not resolve the GitLab service name, so artifact
  upload/download failed even when scanner jobs completed.
- OWASP ZAP could not write JSON output until `/zap/wrk` existed as a mounted
  writable directory.
- GitLab job containers cannot use `localhost` for dashboard callbacks because
  `localhost` points to the job container, not the host/dashboard.

Fix:

- `agentic_gitlab_cicd_demo.py` now attaches the first available runner to the
  generated project when required.
- The reference runner config uses `network_mode = "gitlab-net"` so job
  containers can resolve and reach the GitLab container.
- The reference runner config mounts `/tmp/zap-wrk:/zap/wrk`.
- The demo script supports a separate runner-facing dashboard URL and defaults
  `SOC_DASHBOARD_URL` to `http://192.168.50.222:25480` for the lab.
- ZAP writes to `/zap/wrk/zap.json` and then copies that artifact into the
  project workspace.

Verified:

- Ticket `83` created from the GitLab security gate.
- GitLab pipeline `9` ran unit tests, Semgrep, Trivy, ZAP, and Nuclei, then
  failed the dashboard gate as intended.
- Dashboard CI/CD run `11` recorded seven findings.
- Local model remediation agent `50` requested change `39` before edits.
- After approval, the agent fixed the app, committed to branch
  `agent/remediate-security-gate`, and opened MR `!1`.
- GitLab pipeline `10` passed.
- Dashboard CI/CD run `12` passed with zero findings.
- Deployment change `40` was approved and completed.

### Agent postmortem context can be too large for slow local models

Problem:

- The postmortem task for the full CI/CD demo fetched the entire ticket context,
  including large prior agent logs and attachments.
- The model remained alive but slow after receiving a large payload.
- The first postmortem agent process exited successfully but did not create the
  required `postmortems` row, so process exit alone was not enough to prove task
  completion.

Resolution:

- Added `GET /api/postmortems/evidence/{ticket_id}` so postmortem agents receive
  bounded, scoped evidence instead of raw ticket context, full scanner JSON, or
  full agent logs.
- The endpoint now returns compact ticket context, notes, attachment metadata,
  change requests, task summaries, CI/CD severity counts and sampled findings,
  prior postmortems, and a short audit/event slice.
- The runner now treats postmortem tasks as failed if they exit without creating
  a postmortem artifact for the ticket/task.
- Added supervisor fallback `POST /api/postmortems/synthesize/{ticket_id}`.
  If local-model postmortem agents stall or fail, the platform creates a
  `ready_for_review` postmortem from bounded evidence and logs the synthesis.
- Postmortem agents no longer reopen the resolved ticket or replace the
  ticket's primary resolver agent.

### GitLab demo postmortem failure mode is now guarded

Problem:

- The GitLab demo postmortem agent first tried non-existent per-ticket notes and
  attachment endpoints.
- It then tried to read scanner artifacts outside its assigned work directory.
- The runner correctly failed the task when the agent exited without creating a
  postmortem row.
- Later retries showed a second local-model failure mode: even compact raw JSON
  can lead the model to chase persisted tool-output files instead of persisting
  the postmortem.

Resolution:

- Added `GET /api/postmortems/evidence/{ticket_id}` and reduced the default
  payload to an agent-safe summary.
- Added `POST /api/postmortems/synthesize/{ticket_id}` as the deterministic
  supervisor fallback for stalled/failed model postmortems.
- Postmortem `21` was created with status `ready_for_review` for ticket `83`.
- Postmortem `22` was created with status `ready_for_review` for ticket `88`
  after the real CI/CD flow completed and local-model postmortem attempts
  stalled.
- Ticket `83` evidence endpoint was verified with `6` notes, `2` attachments,
  `2` changes, `2` agent tasks, `2` CI/CD runs, `1` postmortem, and `28` audit
  entries.
- Ticket `88` completed the real CI/CD flow with final run `14` passed,
  changes `43` and `44` completed, ticket status `resolved`, postmortem `22`
  ready for review, and zero active agent processes.

### Fresh one-line installs exposed agent workdir ownership drift

Problem:

- The API container creates `agent_work/<agent_id>` on a bind mount.
- On a fresh side-by-side install, those workdirs can be owned by root on the
  host.
- `agentic_cicd_full_demo.py` then failed before it could seed the demo app for
  the local-model agent: `PermissionError: [Errno 13] Permission denied:
  '.../agent_work/<id>/demo-app'`.
- The previous repair code used a fixed container name, which does not work for
  one-line installs that use custom Compose project names.

Resolution:

- `agentic_cicd_full_demo.py` now repairs workdir ownership with
  `docker compose exec -T api` from the installed root rather than using a fixed
  container name.
- The runner writes a probe file before continuing, and fails clearly if the
  workdir is still not host-writable.
- Verified on fresh install
  `/home/cereal/SOC_TESTING/soc-dashboard-install-e2e-20260512` with real
  local-model ticket `13`; remediation agent `7` completed and produced the MR
  patch artifact.

### Postmortem fallback must stop stale model processes after synthesis

Problem:

- The compact postmortem evidence API is bounded, but slower local models can
  still stall or fail while producing the structured POST body.
- The supervisor can synthesize a `ready_for_review` postmortem, but the model
  process may still be alive if synthesis happens due to timeout rather than
  process exit.

Resolution:

- The full CI/CD demo runner now stops the postmortem agent after supervisor
  synthesis.
- The agent runner itself now attempts deterministic postmortem synthesis when
  a postmortem task exits without creating the required artifact.
- Verified on fresh install ticket `13`: postmortem `4` was
  `ready_for_review`, the stale postmortem process was stopped, and
  `/api/agents/processes` returned no active processes.

### One-line installer script mode can be lost during transfer

Problem:

- `./install.sh` failed with `Permission denied` in a fresh installer E2E run
  because the executable bit was not preserved.

Resolution:

- The repository index now marks `install.sh` executable.
- If a copied working tree still loses the bit, repair the source tree with:

```bash
chmod +x /home/cereal/SOC_TESTING/soc-dashboard/install.sh
```

### Ticket sorting/filtering failed when status filters were used

Problem:

- The ticket list API built `WHERE status = ...` and `WHERE priority = ...`
  clauses without table aliases.
- Once the tickets query joined `agents`, PostgreSQL treated `status` as
  ambiguous, causing HTTP 500 for filtered ticket lists.
- Restarting the API container alone did not load host-side route edits because
  the API code is baked into the image.

Fix:

- Ticket filters now qualify columns as `t.status`, `t.priority`,
  `t.assignee`, and `t.agent_id`.
- The count query now aliases `tickets t` to match the shared filter clause.
- Rebuild the API container with `docker compose up -d --build api` after API
  Python changes.

Verified:

- `GET /api/tickets?status=in_progress&sort_by=title&sort_dir=asc&limit=3`
  returns HTTP `200`.
- `platform_doctor.py` validates ascending and descending ticket sort order.

### SOC bridge daemon fails when launched from its package directory

Status: fixed during the 2026-05-12 real agentic bridge acceptance pass.

Problem:

- The documented SOC bridge health check was run from
  `/home/cereal/SOC_TESTING/soc_bridge` with:

```bash
python3 daemon.py --config production_config.json --check
```

- It failed before checking iTop/Mailcow with:

```text
ModuleNotFoundError: No module named 'soc_bridge'
```

Impact:

- This blocks reliable verification of the iTop-Mailcow notification bridge
  from the documented quick-operation command.
- It does not currently block the SIEM-ticket bridge; Wazuh-to-iTop bridge
  status and connection checks passed with `siem_connected=true` and
  `ticketing_connected=true`.

Next action:

- Completed.

Fix:

- Updated `/home/cereal/SOC_TESTING/soc_bridge/daemon.py` and `cli.py` so direct
  script execution adds the package parent directory to `sys.path` before
  importing `soc_bridge.*`.
- Kept module-style execution working; the change only applies when
  `__package__` is empty.

Verified:

- `python3 -m py_compile daemon.py cli.py`: PASS
- `python3 daemon.py --config production_config.json --check`: PASS,
  iTop and Mailcow both connected.
- `python3 cli.py --config production_config.json status`: PASS, iTop and
  Mailcow both connected.
- `python3 daemon.py --config production_config.json --poll-once`: PASS,
  completed a poll and delivered notifications.

### SOC bridge poll-once can catch up old tickets as new notifications

Status: fixed during the 2026-05-12 real agentic bridge acceptance pass.

Problem:

- After the direct-invocation import fix, the first successful
  `python3 daemon.py --config production_config.json --poll-once` loaded only
  one tracked ticket from state and then sent `created` notifications for 28
  existing iTop tickets.

Impact:

- This proves the Mailcow notification path works, but it also shows that a
  repaired/restarted bridge with stale or empty state can notify old tickets as
  if they were newly created.
- For customer demos and first production use, this can look noisy or
  unprofessional if baseline state is not initialized deliberately.

Next action:

- Completed.

Fix:

- Added `TicketNotificationEngine.baseline_state()` to record current watched
  tickets without sending notifications.
- Added daemon flag:

```bash
python3 daemon.py --config production_config.json --baseline-state
```

- Added CLI flag:

```bash
python3 cli.py --config production_config.json poll --baseline
```

Verified:

- With an empty temporary state file,
  `python3 daemon.py --config production_config.json --state-file "$TMP_STATE" --baseline-state`
  tracked 28 tickets and sent 0 notifications.
- A subsequent
  `python3 daemon.py --config production_config.json --state-file "$TMP_STATE" --poll-once`
  fetched 28 tickets, found 0 changes, and sent 0 notifications.
- `python3 cli.py --config production_config.json poll --baseline` completed
  successfully and sent 0 notifications.

### Incoming tickets can now auto-assign agents by RACI policy

Status: fixed during the 2026-05-12 real agentic bridge acceptance pass.

Problem:

- Bridge-created or provider-synced tickets currently require manual agent
  assignment from the dashboard or an explicit `/assign-agent` API call.
- A production control plane needs configurable assignment policy: some RACI
  groups, intents, severities, providers, or ticket classes should immediately
  spawn an agent, while other tickets should stay in a manual queue.

Impact:

- Real bridge flows can create and sync tickets but do not yet prove the
  intended hands-free path from incoming event to agent work.
- This weakens the customer pitch because the system appears to need an
  operator click at the exact point where automation should begin.

Fix:

- Added RACI rule fields `auto_assign_agent`, `auto_agent_model`, and
  `auto_agent_prompt`.
- Seeded the phishing RACI rule so Security Operations phishing incidents
  auto-spawn a ticket agent.
- Wired policy evaluation into direct ticket creation, service-desk intake after
  classification notes/approval gates are written, and iTop sync for newly
  discovered provider tickets.
- Kept manual routing as the default for rules where `auto_assign_agent=false`.

Verified:

- `python -m py_compile api/services/auto_assignment.py api/services/ticket_service.py api/services/itop_sync.py api/routes/intake.py api/routes/tickets.py`: PASS.
- `python -m unittest tests.test_auto_assignment tests.test_provider_registry tests.test_itop_outbound`: PASS.
- `python scripts/smoke_auto_assignment_policy.py`: PASS.

## Current Limitations

### Change completion can silently drop agent evidence

Status: fixed and deployed live on 2026-05-12.

Problem:

- During ticket `312`, agent `85` completed changes `83`, `84`, and `85` with
  request bodies containing `evidence`.
- The live `/api/changes/{id}/complete` route only reads `result`, so it marked
  each gate `completed` while storing a blank `change_requests.result`.
- The route also attributed those completions to `dashboard` because it ignored
  the submitted `agent_id`.

Impact:

- Change gates can look completed in the UI/API while losing the evidence needed
  for audit, demo explanation, and postmortem learning.

Fix:

- Accept `result`, `evidence`, or `output` as completion evidence and store the
  selected value in `change_requests.result`.
- Reject blank completion evidence instead of recording an empty result.
- Attribute completion to `completed_by`, `actor`, or `agent_<agent_id>` before
  falling back to `dashboard`.

Verification:

- Added unittest coverage for `evidence` alias handling and blank evidence
  rejection in `tests/test_change_approval_resume.py`.
- Live API rejected blank evidence for change completion.
- Live ticket `312` result rows for changes `83`, `84`, and `85` were repaired
  through the hardened API route using the evidence agent `85` already posted.

### iTop incident resolution requires lifecycle transition before resolve

Status: fixed and deployed live on 2026-05-12.

Problem:

- Ticket `312` was resolved by agent `85` in the dashboard, but iTop Incident
  `199` / `I-000208` remained in state `new`.
- A direct iTop `ev_resolve` stimulus failed with
  `Invalid stimulus: 'ev_resolve' on the object I-000208 in state 'new'`.
- The next iTop sync then pulled the provider's `new` status back into the
  dashboard, hiding the completed agent work from the ticket list.

Impact:

- Agent-completed work can be locally complete but provider-visible tickets
  stay open, which breaks demos and weakens the provider-sync audit trail.

Fix:

- Provider close now retries iTop resolution through the normal lifecycle:
  `ev_assign` first when direct `ev_resolve` is invalid, then `ev_resolve`.

Verification:

- Live repair succeeded for ticket `312`: iTop accepted `ev_assign`, then
  accepted `ev_resolve`, and the subsequent sync returned the dashboard ticket
  to `resolved`.
- API image was rebuilt with the iTop lifecycle fallback and passed health,
  compile, and focused remote unittest checks.

### Approval resume can fan out duplicate agents for one ticket

Status: fixed and deployed live on 2026-05-12.

Problem:

- Approving three pending lab-no-op changes for ticket `312` caused the
  approval resume handler to spawn continuation agents `86`, `87`, and queued
  `88` while agent `85` was already actively working the same ticket.
- The agent auditor correctly wrote `ticket_already_has_active_agent` audit
  events, but it only audited and did not prevent or consolidate the duplicate
  runners.
- Root cause: `_resume_agent_after_approval` checked active tasks only for the
  original change agent, not for active agents on the ticket as a whole.

Impact:

- Approval gates can create overlapping agents for the same ticket, causing
  duplicated notes, duplicated remediation actions, noisy demo evidence, and
  possible cross-agent confusion.

Fix:

- Make approval resume ticket-scoped: if any spawned/running/working agent or
  queued/running task exists for the ticket, return that active agent instead
  of spawning another continuation.
- Keep the auditor signal, but make the approval path prevent duplicates before
  the auditor has to notice them.

Verification:

- Added `tests/test_change_approval_resume.py` coverage proving
  `_resume_agent_after_approval` returns `already_active_ticket` when another
  agent/task is active on the same ticket.
- Live regression created approval change `86` on ticket `317`; approving it
  returned `resume.status=already_active_ticket` and did not create another
  agent.
- `/api/agents/active` was clean after removing the regression fixtures.

### Stopped queued agent can still start when semaphore opens

Status: fixed and deployed live on 2026-05-12.

Problem:

- Agent `88` was stopped while its task was still queued.
- When a semaphore slot opened, task `86` still started a Claude runner process
  after the stop request had already set the agent status/error.

Impact:

- Dashboard stop is not definitive for queued tasks. A queued duplicate or
  cancelled task can still become a real process later, which undermines agent
  supervision and demo reliability.

Fix:

- Before `_spawn_with_semaphore` launches a process, reload task and agent state
  and exit without spawning if either is `stopped`, `terminated`, `failed`, or
  otherwise no longer queued/runnable.
- Ensure `stop_agent_task` marks queued tasks as stopped in a way the semaphore
  worker honors before process launch.

Verification:

- Added `tests/test_agent_lifecycle_guards.py` coverage proving stopped queued
  tasks are skipped before `_run_agent` is called.
- Live process diagnostics after deployment showed no active Claude runner
  processes.

### Stopping a duplicate agent can leave ticket assigned to the stopped agent

Status: fixed and deployed live on 2026-05-12.

Problem:

- Duplicate agent `88` was stopped, but `tickets.agent_id` still pointed to
  `88` while the only real active worker was agent `85`.
- iTop/dashboard sync context then reported the wrong canonical agent for the
  ticket, which can confuse agents, operators, and audit demos.

Impact:

- The dashboard can show or pass stale ownership after duplicate cleanup,
  especially when a later duplicate spawn overwrites `tickets.agent_id`.

Fix:

- When stopping an agent, if that agent is the ticket's current `agent_id`,
  reassign the ticket to another active agent for the same ticket, or clear the
  assignment if none exists.
- Record the reassignment/clear in audit/event history.

Verification:

- Added `tests/test_agent_lifecycle_guards.py` coverage for ticket reassignment
  after stopping a duplicate agent.
- Live regression stopped duplicate queued agent `92` on ticket `318`; the
  ticket owner was restored to active agent `91`, then both regression fixtures
  were cleaned up.

### SOC Bridge phishing ticket creation is failing before dashboard sync

Status: fixed during the 2026-05-12 real bridge phishing agent flow.

Problem:

- `/tmp/bridge_phish_agent_flow.py` failed in `run_bridge_report`.
- SOC Bridge returned `ticket_creation.success=false` with
  `No ticket key in API response`.
- Root cause identified: phishing reports with `message_id` were mapped to
  iTop `Incident.externalid`, but the live iTop schema has no `externalid`
  attribute on `Incident`. iTop returned `code=100` with
  `Unknown attribute externalid from class Incident`; the bridge did not surface
  that response message.

Impact:

- The full Report Phish -> SOC Bridge -> iTop -> dashboard -> agent flow cannot
  start because the iTop ticket is not created.

Fix:

- Inspect SOC Bridge production config and iTop create response handling.
- Verify the configured security team/org/caller fields still match the live
  iTop instance.
- Fix the bridge connector or config, rerun the bridge phishing harness, then
  continue to agent/approval/postmortem validation.

Verification:

- Acceptance log `bridge-phish-agent-20260512-125257.log` shows SOC Bridge
  successfully created iTop Incident `198`.
- Acceptance log `bridge-phish-agent-20260512-130312.log` shows SOC Bridge
  successfully created iTop Incident `199` and sent the Mailcow notification.

### Dashboard iTop sync is not discovering the bridge-created phishing ticket

Status: fixed during the 2026-05-12 real bridge phishing agent flow.

Problem:

- SOC Bridge successfully created iTop Incident `198` titled
  `Phishing Report: Bridge Agentic Phish 1778611977`.
- The real bridge harness remained in the dashboard sync/find loop; dashboard
  `/api/tickets` did not show the new bridge ticket after `/api/tickets/sync-all`.

Impact:

- The Report Phish -> SOC Bridge -> iTop leg now works, but the full iTop ->
  dashboard -> agent auto-work leg is still blocked.

Fix:

- Inspect `/api/tickets/sync-all` behavior, iTop sync logs, and sync-state key
  tracking for newly created Incident keys above the current dashboard range.

Verification:

- Sparse iTop key listing now uses `SELECT <Class>` instead of assuming
  contiguous numeric IDs.
- Full sync imports historical rows passively while live discovery can still
  auto-assign genuinely new tickets.
- Ticket `312` synced from iTop Incident `199` and now has
  `provider_sync_status=synced`.

### Bulk iTop catch-up sync can auto-assign historical phishing tickets

Status: fixed and deployed live on 2026-05-12.

Problem:

- After switching discovery away from contiguous ID scanning, a full catch-up
  sync imported historical iTop phishing tickets and auto-started agents for
  old SOC Bridge smoke tickets (`agent_id` 78 and 79).

Impact:

- This is not the same broad matcher bug; the tickets are genuine phishing
  tickets, but they are historical catch-up rows and should not spawn live
  agents during repair, bootstrap, or bulk import.

Fix:

- Split sync behavior so live discovery and explicit single-ticket sync can
  auto-assign, while `full_sync`/bootstrap catch-up imports remain passive.

Verification:

- Added `tests/test_itop_outbound.py` coverage proving `full_sync()` calls
  `sync_ticket(..., auto_assign=False)` for historical/provider catch-up rows.
- Remote unittest suite passed after deployment.

### Auto-assigned bridge phishing agent stalls on broad default ticket prompt

Status: fixed and deployed live on 2026-05-12 for future auto-assigned
phishing tickets.

Problem:

- Live bridge run created iTop Incident `199`, dashboard ticket `312`, and
  auto-assigned agent `81`.
- Agent `81` remained alive with heartbeats for 10+ minutes at `45%` progress
  after reading full ticket context/workflow evidence, but it had not created
  triage notes or remediation approval gates.
- The active prompt is the broad default ticket-resolution prompt plus a short
  phishing instruction, not the tighter bridge phishing acceptance workflow.

Impact:

- The bridge, iTop sync, and auto-assignment chain works, but the intended
  hands-free agentic phishing flow is not yet completing reliably with the
  default auto-assignment prompt.

Fix:

- Tighten the phishing RACI `auto_agent_prompt`/prompt builder so auto-assigned
  phishing agents use bounded postmortem/ticket evidence and concrete required
  actions instead of broad context exploration.

Verification:

- Added `AUTO_ASSIGNMENT_PROMPT`, and `maybe_auto_assign()` now uses
  `build_auto_assignment_prompt()` instead of the broad default ticket prompt.
- Added migration `010_tighten_phishing_auto_agent_prompt.sql` and updated
  `init_db.sql` so fresh installs and existing deployments get the compact
  phishing instruction.
- Live database check confirmed the phishing RACI prompt begins with
  `Auto-work Security Operations phishing tickets end to end using compact evidence first`.

### Agent task can fail after useful work with output chunk separator error

Status: mitigated and deployed live on 2026-05-12.

Problem:

- Agent `81` wrote a meaningful phishing triage note for ticket `312`.
- The task then failed with
  `Separator is found, but chunk is longer than limit`.

Impact:

- The model can perform useful ticket work, but the runner/task-output handling
  can mark the task failed before approval gates and final notes are complete.
- This makes real-flow validation brittle even when the agent is taking correct
  actions.

Mitigation:

- Inspect agent runner stream/chunk handling for long tool output or persisted
  tool-result references, then bound or summarize oversized chunks before task
  persistence.

Verification:

- Ticket API and postmortem evidence responses now call
  `compact_ticket_payload()` so agents see provider payload summaries instead of
  the full iTop payload by default.
- The auto-assignment prompt instructs agents to use
  `/api/postmortems/evidence/{ticket_id}?task_log_lines=0` first and avoid full
  ticket context unless a specific fact is missing.
- The original ticket `312` was completed by the follow-up bounded flow; changes
  `83`, `84`, and `85` all have persisted completion evidence.

### RACI auto-assignment matched generic Incident tickets too broadly

Status: fixed during the 2026-05-12 full acceptance baseline.

Problem:

- A provider-adapter smoke ticket titled `Provider adapter smoke` received an
  active agent even though it did not contain phishing keywords and was not
  routed to Security Operations.
- Root cause: the auto-assignment scorer gave enough points for matching
  `ticket_class=Incident` alone, so the phishing RACI rule could match generic
  Incident tickets.

Impact:

- Agents can be assigned to tickets that should remain in a manual or unrelated
  queue.
- This matches the observed concern that agents may spill into tickets that
  already have a different purpose.

Fix:

- Auto-assignment now requires a strong signal such as assignment group or
  keyword match before an
  auto-assignment rule can fire.
- Ticket class is now a ranking boost only after a real intent/group signal is
  present.
- Added a unit/smoke case proving generic Incident tickets stay manual while
  phishing/Security Operations incidents auto-assign.

Verified:

- Local `python -m unittest tests.test_auto_assignment`: PASS.
- Local `python scripts/smoke_auto_assignment_policy.py`: PASS.
- Live rebuilt API `_score_rule` returned `{'class_only_score': 0}` for
  `Provider adapter smoke`.
- Live provider-adapter smoke created ticket `174` with no active agent spawned.

### Tool health inventory still has unprobeable deployed/reference modules

Status: active, found during the 2026-05-12 full acceptance baseline.

Problem:

- `POST /api/tools/check-all` reports `unknown` for Suricata IDS, SOC Bridge,
  SIEM-Ticket Bridge, and TheHive.
- The returned error is `No port configured for health check`.

Impact:

- The Tools page is not yet a clean demo surface for every deployed or reference
  integration.
- Operators can see Wazuh Dashboard, iTop, Mailcow, GitLab, SearXNG, Agent
  Memory, and other HTTP/port-backed tools as healthy, but bridge/daemon-style
  modules do not yet expose a dashboard health contract.

Next action:

- Add provider-aware health checks for daemon/file/container-backed tools, or
  mark optional/reference modules inactive when they are not part of the current
  setup profile.
- Reconcile the Tools page from the setup manifest so unused modules are hidden
  or explicitly labeled optional/not configured.

### Fresh Sysmon exact-marker alert intermittently misses Wazuh Indexer

Status: fixed in the reference lab profile during the 2026-05-12 EDR/Sysmon live rerun.

Problem:

- The EDR/Sysmon E2E test passed 15/16 after the neutral iTop harness fix.
- The remaining failure is `Fresh Sysmon exact-marker alert flow`: the test
  generated a harmless `CODEX_SYSMON_*` marker but did not find a matching
  Wazuh Indexer alert within the 90-second wait window.
- This is the same symptom as the earlier queue/logcollector delay, so the next
  diagnostic step is to trace the marker through Sysmon hot log, Wazuh
  logcollector, manager alerts, and Indexer ingestion before changing rules.

Impact:

- The provider health-check ticket no longer causes accidental RACI
  auto-assignment, but the real endpoint telemetry proof is not yet reliable
  enough for a clean demo.

Diagnostic path used:

- Capture the exact marker from the rerun, confirm whether it reached
  `/var/log/sysmon/sysmon.log`, inspect Wazuh manager/logcollector warnings, and
  rerun after correcting the ingestion path.

Update:

- Rerun marker `CODEX_SYSMON_E2E_1778632057` was present in
  `/var/log/sysmon/sysmon.log` as both the logger line and Sysmon file-create
  XML.
- No matching Wazuh archive/alert hits were found.
- `wazuh-manager` reported inactive and localhost Indexer connection refused
  during the trace, so the immediate blocker is Wazuh service availability, not
  Sysmon marker generation.
- Container inspection corrected the service read: Wazuh is Dockerized and the
  manager container is running. The manager sees `/var/log/sysmon/sysmon.log`,
  but `wazuh-analysisd` logged `Input queue is full`, and no marker was found in
  manager archives/alerts. The active blocker is noisy Sysmon ingestion
  overwhelming Wazuh analysis, so the reference Sysmon config needs to be
  tightened for the E2E marker path before rerun.

Fix:

- Removed broad `/bin/bash -c`, `/bin/sh -c`, `.sh`, and `.py` selectors from
  the lab Sysmon profile.
- Added an explicit match-nothing `ProcessTerminate` include rule because
  SysmonForLinux was otherwise emitting EventID 5 process-termination noise and
  filling the Wazuh analysis queue.
- Rotated the hot Sysmon log and restarted Sysmon plus Wazuh manager internals.

Verified:

- Hot Sysmon log stayed quiet after restart.
- EDR/Sysmon E2E rerun passed `16/16`.
- Exact marker `CODEX_SYSMON_E2E_1778632686` produced 2 Wazuh alerts.
- SIEM bridge remained healthy with `error_count=0` and processed the marker
  during the next poll.

### Agent Bash path validation rejects multiline inline Python

Status: active, found during real agent work on ticket `354` / agent `123`.

Problem:

- The agent correctly moved from compact evidence to deeper Wazuh context, but
  generated a multiline `python3 -c` shell snippet containing a `#` comment
  inside a quoted argument.
- The harness rejected it with `Newline followed by # inside a quoted argument
  can hide arguments from path validation`.

Impact:

- This is a good safety rejection, but local agents may waste cycles or stall if
  their prompts do not steer them toward simpler command shapes.

Fix:

- Add a harness instruction telling agents to avoid multiline inline
  `python -c`/shell comments and to use simple `curl` calls or write temporary
  scripts/files when parsing JSON is required.

Verified:

- Local `python -m py_compile api/services/task_prompts.py` passed.
- Current agent recovered from the rejected command by trying a simpler approach.
- Live API rebuild is deferred until active agent `123` completes, to avoid
  disrupting the running EDR/SIEM proof.

### Provider sync can overwrite local in-progress agent state

Status: fixed in source, live API rebuild deferred until agent `123` completes.

Problem:

- The compact evidence showed ticket `354` as `in_progress` immediately after
  auto-assignment.
- Later dashboard ticket detail showed `status: new` while agent `123` was still
  working because iTop sync mirrored the provider-side status back over the
  dashboard's local working state.

Impact:

- Operators may see an actively worked ticket as `new`, which makes the demo and
  audit story confusing.
- This can also make agent completion/closure verification harder because local
  and provider states are not clearly separated.

Fix:

- Preserve or derive an active local workflow state while an agent is assigned,
  and push/pull provider status transitions explicitly rather than letting
  provider sync hide active dashboard work.
- Existing iTop sync now derives an effective local status: active-agent tickets
  keep `in_progress`, `awaiting_user_response`, or `pending_approval` unless the
  provider reports a terminal status such as `resolved` or `closed`.

Verified:

- Local `python -m unittest tests.test_itop_sync_status tests.test_auto_assignment tests.test_itop_outbound`: PASS.
- Source synced to the remote tree; container rebuild waits for the active EDR
  proof agent to finish.

### Agent-created notes can default to dashboard author

Status: fixed in source, live API rebuild deferred until agent `123` completes.

Problem:

- Agent `123` posted triage note `456`, but the note defaulted to
  `author=dashboard` and `source=dashboard` because the request did not include
  explicit note attribution.

Impact:

- The note body is useful, but audit readability suffers because an agent action
  can look like a human dashboard note.

Fix:

- Tighten ticket-agent prompts so agent note requests include
  `author=agent-{agent_instance_id}` and `source=agent` or
  `agent-control-plane` whenever the agent writes progress, triage, or
  resolution evidence.

Verified:

- Local `python -m py_compile api/services/task_prompts.py api/services/itop_sync.py`: PASS.
- Source synced to the remote tree; container rebuild waits for the active EDR
  proof agent to finish.

### Agent completion must close provider tickets

Status: fixed and deployed.

Problem:

- Real EDR/SIEM agent `123` completed task `120` and resolved dashboard ticket
  `354`, but the runner's success path only updated the canonical dashboard
  status directly.
- For iTop-backed tickets, provider closure should also be attempted through the
  iTop lifecycle so the external ticket does not remain open after local agent
  completion.

Fix:

- Added best-effort provider close on successful `ticket_resolution` completion.
- For iTop-backed tickets, the runner now calls `iTopProvider.close_ticket`,
  which already handles `ev_assign` before `ev_resolve` when iTop rejects direct
  resolution from `new`.
- Provider close success/failure is logged. Failures add a ticket note instead
  of hiding the local resolution.

Verified:

- Local `python -m unittest tests.test_itop_sync_status tests.test_auto_assignment tests.test_itop_outbound tests.test_agent_lifecycle_guards`: PASS.
- Local `python -m py_compile api/services/agent_runner.py api/services/itop_sync.py api/services/task_prompts.py`: PASS.
- Live API rebuilt after active agents reached zero.
- Manual provider close for ticket `354` returned `{'status': 'resolved'}` and
  post-close evidence showed dashboard status `resolved` and provider status
  `resolved`.

### Single-ticket sync endpoint returned 500 after provider close

Status: fixed and deployed.

Problem:

- `POST /api/tickets/354/sync` returned `Internal Server Error` immediately
  after iTop provider close.
- A subsequent evidence fetch still showed ticket `354` and provider payload
  status as `resolved`, so the sync operation may be completing but the route is
  erroring while formatting or returning the response.

Impact:

- Operators cannot trust the manual single-ticket sync button/API even when the
  underlying provider state is correct.

Fix:

- Inspect the API traceback, fix the route or sync return contract, and rerun
  `POST /api/tickets/354/sync` until it returns a clean JSON response.
- The status-guard refactor had two stale references to the removed `exists`
  variable in `iTopProvider.sync_ticket`. Replaced them with `existing_ticket`
  / `not bool(existing_ticket)`.
- Added a regression check to `tests/test_itop_sync_status.py`.

Verified:

- Live API rebuilt with zero active agents.
- `POST /api/tickets/354/sync` returned HTTP 200 with
  `{"status":"synced","itop_ref":"226","itop_class":"Incident","is_new":false,"ticket_id":354,"auto_assignment":null}`.
- Ticket `354` evidence remained dashboard `resolved` with provider payload
  status `resolved`.

### Phishing agent resolved after triage only

Status: fixed and verified, found during report-phish live flow on ticket `361` / agent `124`.

Problem:

- The report-phish bridge flow worked mechanically: SOC bridge created iTop
  Incident `233`, Mailcow notification was sent, dashboard synced the ticket,
  agent `124` auto-assigned, wrote attributed triage note `462`, completed task
  `121`, and iTop provider status synced as `resolved`.
- The agent did not create approval-gated containment actions such as URL block,
  mailbox/message quarantine simulation, user notification, or credential reset
  review. It resolved after triage only.

Impact:

- This is not yet a strong end-to-end phishing-response proof. It proves intake,
  sync, attribution, and closure, but not full remediation workflow behavior.

Fix:

- Tighten the phishing RACI/workflow instruction so phishing agents must either
  create approval-gated containment/recovery changes or explicitly document why
  no containment is required.
- The seeded phishing/Security Operations RACI prompt now requires URL block,
  mailbox search/quarantine, password/session review, or an explicit
  no-containment justification before resolution.
- Ticket-resolution prompts now give the exact change request schema and final
  closure rules.

Verified:

- Live report-phish rerun marker `CODEX_PHISH_E2E_1778637511` created iTop
  Incident `236` / `I-000245`, dashboard ticket `364`, agent `127`, and task
  `124`.
- Agent `127` wrote triage note `491`, created approval gates `100`, `101`, and
  `102`, resumed after approval, completed all three changes with lab-safe
  containment evidence, wrote resolution note `502`, created postmortem `47`,
  and finished at `100%`.
- Dashboard ticket `364` and direct iTop Incident `236` both ended `resolved`.

### Progress supervisors use checkpoint-only stale detection

Status: fixed and verified, found while auditing report-phish rerun ticket `362` / agent
`125`.

Problem:

- Agent `125` is alive and heartbeating while working through the stricter
  phishing flow, and it wrote attributed triage note `468`.
- The task tracker and agent auditor still evaluate "no progress" primarily
  from the latest `checkpoint.json` timestamp.
- Local models can spend a long time generating or using tools without updating
  the checkpoint file, especially when queued behind slow local inference.

Impact:

- A valid local-model run can be marked failed or recommended for replacement
  even though the harness is heartbeating, output is being appended, or ticket
  notes/change gates are moving.

Fix:

- Update task tracker and agent auditor activity calculations to use the newest
  evidence across checkpoint timestamp, agent heartbeat, output log mtime, and
  ticket note/change activity.
- Keep `STUCK_TIMEOUT_MINUTES` and `AGENT_AUDIT_NO_PROGRESS_MINUTES`
  configurable, but do not treat checkpoint silence alone as failure while the
  agent is otherwise demonstrably alive.
- `task_tracker` and `agent_auditor` now compute latest activity across
  checkpoint timestamp, agent heartbeat, output log mtime, checkpoint file mtime,
  ticket notes, and change request activity.
- The auditor records `progress_sources` in no-progress findings so operators can
  understand what evidence was evaluated.

Verified:

- During ticket `364`, the auditor recorded `agent_waiting_on_approval` while
  gates were pending and did not mark the heartbeating local model as failed
  while notes, approvals, and output log activity were moving.
- The same run completed cleanly with task `124` at `100%`.

### Agent change requests failed due missing request schema

Status: fixed and verified, found during report-phish rerun ticket `362` / agent `125`.

Problem:

- Agent `125` correctly attempted to create three approval-gated phishing
  containment changes: URL block, mailbox search/quarantine, and password
  reset/session revocation.
- It posted fields such as `title` and `description` to
  `POST /api/changes/request`, but that endpoint requires `action`, `target`,
  and `reason`.
- The API returned validation errors for all three attempts, so no
  `change_requests` rows were created on the first try.

Impact:

- The RACI prompt is directionally correct, but the harness prompt is still too
  implicit for slow local agents. Agents can attempt the right workflow and
  still fail because they guessed the endpoint contract.

Fix:

- Add the exact change request JSON shape to ticket-resolution prompts:
  `agent_id`, `ticket_id`, `action`, `target`, `reason`, optional
  `risk_level`, optional `approval_policy`.
- Standard and auto-assignment ticket prompts now include the exact
  `POST /api/changes/request` body and warn agents not to use `title` /
  `description` for change request creation.
- Agent workspaces also include the same schema in `CLAUDE.md`.

Verified:

- Agent `127` created change requests `100`, `101`, and `102` on ticket `364`
  without schema validation errors.

### Approved phishing gates lack bounded lab action contract

Status: fixed and verified for lab/demo execution, found during report-phish rerun ticket `362` / agent `125`.

Problem:

- Agent `125` successfully self-corrected and created three approval gates
  after the initial schema error:
  - change `94`: `url_block` on `phish-example.test`
  - change `95`: `mailbox_quarantine` on `demo.user@mailcow.local`
  - change `96`: `password_reset` on `demo.user@mailcow.local`
- All three were approved by `codex-e2e-lab-approver`.
- After approval, the agent began broad tool discovery (`/api/tools`, workspace
  listing) instead of using a bounded lab-safe execution contract.

Impact:

- The approval boundary works, but approved action execution is still too vague
  for local agents. The system needs either concrete provider action adapters
  or explicit lab-action semantics for demos.

Fix:

- Update prompts so agents do not discover broad tool inventory after approval.
- For approved lab/demo actions without a concrete provider adapter, agents
  should complete the gate with explicit simulated control evidence, add a
  ticket note, and state exactly which production adapter would perform the real
  operation.
- Longer term: add provider action adapters for URL blocking, Mailcow search /
  quarantine, and IAM password reset/session revocation.
- Per-agent curl guards block broad dashboard schema/tool inventory endpoints
  such as `/api/tools`, `/openapi.json`, `/docs`, and `/redoc`.
- Prompts now tell agents to complete approved lab/demo containment gates with
  explicit control evidence and name the production adapter when no concrete
  provider action adapter exists yet.

Verified:

- Agent `127` completed gate `100` with URL-block evidence and DNS/proxy
  production-adapter guidance.
- Agent `127` completed gate `101` with mailbox search/quarantine evidence and
  Mailcow/Rspamd production-adapter guidance.
- Agent `127` completed gate `102` with password reset/session revocation
  evidence and Keycloak production-adapter guidance.

### Intermediate checkpoint marked ticket resolved before changes completed

Status: fixed and verified, found during post-fix report-phish rerun ticket `363` / agent
`126`.

Problem:

- Agent `126` correctly wrote triage note `479` and created approval gates
  `97`, `98`, and `99` using the fixed `action` / `target` / `reason` schema.
- The gates were manually approved by `codex-e2e-lab-approver`.
- Before executing or completing those approved gates, the agent wrote
  `checkpoint.json` with `status: "done"` but only `progress_pct: 30`.
- The task tracker treated any `done` checkpoint as final completion, marked
  task `123` completed, set ticket `363` to `resolved`, and left changes
  `97`-`99` in `approved` state with no result.

Impact:

- A ticket can close while approved containment actions remain unfinished. This
  fails the E2E phishing workflow requirement and makes dashboard state
  misleading.

Fix:

- Update task tracker so `done` / `completed` checkpoint states only finalize a
  task when `progress_pct >= 100`.
- Update agent prompts so intermediate steps use `running` and only final
  completion uses `done` with progress `100` after open changes are completed,
  final notes are written, and provider closure is ready.
- `task_tracker` now ignores `done` / `completed` checkpoints below `100%`,
  records `checkpoint_done_ignored_before_100`, and keeps the task running.
- Prompts now require intermediate checkpoints to use `running`; final
  completion must be `done` at `100%` after approval gates, notes, and provider
  closure are complete.

Verified:

- Agent `127` wrote an intermediate `running` checkpoint at `35%` while changes
  `100`-`102` were pending/approved, and ticket `364` stayed `in_progress`.
- Only after changes `100`-`102`, resolution note `502`, and postmortem `47`
  existed did agent `127` write final checkpoint `resolution_complete` with
  `status=done` and `progress_pct=100`; task `124` then completed and ticket
  `364` resolved.

### iTop outbound creation needs environment-specific defaults

Incident/UserRequest creation requires iTop org/caller defaults. This is intentional. Configure:

- `ITOP_DEFAULT_ORG_ID`
- `ITOP_DEFAULT_CALLER_ID`

Until configured, outbound iTop create records `create_failed`.

### Notes are canonical-first

Agents write notes to dashboard canonical notes. Provider-side comment sync is not fully implemented yet. This is the next important provider-adapter expansion.

### Binary attachments are metadata-only

`ticket_attachments` stores filename/content-type/hash/storage reference/metadata. Actual binary upload/storage is not implemented yet.

### Access control is not production-ready

The dashboard does not yet enforce Keycloak/OIDC login or role-based approval. Current approval fields are ready for authenticated identities, but auth middleware is still future work.

### Workflow activation is manual/review-state only

Workflows can be drafted, tested, reviewed, and run records can be created. Automatic trigger routing from incoming tickets to approved workflows is not complete yet.

### ServiceNow/Jira providers are not implemented yet

The adapter boundary exists; concrete adapters still need to be written and tested.

### iTop sync scans by numeric key

The current iTop discovery strategy scans numeric keys. It works for the lab but a production provider should prefer provider-native updated-since queries where available.

### No database rollback system

Migrations are additive/idempotent. There is no first-class rollback tool yet.

### Duplicate active workflows per use case

Status: fixed locally and ready for live smoke on 2026-05-15.

Problem:

- Postmortem promotion names workflows with the postmortem id, so repeated
  phishing or SIEM/EDR postmortems can create many separate workflows for the
  same use case.
- The live dashboard had multiple phishing-like workflows in `approved` or
  `active` state while `phishing-smoke-lifecycle` remained `tested` /
  `tested_needs_approval` despite being the workflow with the most completed
  run evidence.
- False-positive refinements were promoted into a separate phishing-related
  workflow instead of becoming notes/refinements on the canonical phishing or
  SIEM false-positive workflow lineage.

Impact:

- Agents and operators can see conflicting workflows for the same ticket type.
- A workflow that is only `tested` can look like the one being used, while older
  approved workflows remain active.
- Postmortem learning becomes fragmented across duplicate articles/workflows.

Fix:

- Add a canonical `workflow_key` and enforce only one active/approved workflow
  per key.
- Make postmortem promotion find and update the canonical workflow for the use
  case instead of minting a new active workflow for every postmortem.
- Demote duplicate active workflows during review/promotion and reconcile the
  live phishing workflow set so `phishing-smoke-lifecycle` is the canonical
  active workflow.
- Workflow create/update requests for `active` or `approved` are now held at
  `ready_for_review`; `POST /api/workflows/{id}/review` is the only activation
  path.
- Review activation now demotes any active/approved sibling with the same
  `workflow_key` before setting the reviewed workflow active and records
  `workflow_siblings_superseded` audit evidence.
- Changing the `workflow_key` on an already-active workflow without an explicit
  review status re-gates that workflow to `ready_for_review`.
- Restored `scripts/smoke_workflow_canonicalization.py` as a deployable smoke
  that proves review gating, one-active enforcement, postmortem workflow reuse,
  ticket-context workflow selection, and audit search evidence.

Verification:

- Local full unit discovery passed on 2026-05-15: 111 tests.
- Focused workflow/postmortem reuse suite passed on 2026-05-15: 6 tests.
- `scripts/text_hygiene.py` was restored and tightened so default checks catch
  true mojibake without forcing historical box-drawing/Unicode docs to be
  rewritten; default hygiene check passes after fixing two recovered skill docs.

### Wazuh/Sysmon bridge queue and log retention gaps

Status: fixed and verified on 2026-05-13.

Problem:

- Wazuh manager logged `wazuh-analysisd: WARNING: Input queue is full` after
  Sysmon ingestion, so high-volume endpoint telemetry can starve fresh alert
  processing.
- The reference Sysmon host still had a 16 GB historical
  `/var/log/sysmon/sysmon.log.archive.*` file in the hot Sysmon directory.
  Wazuh only watches `sysmon.log`, but keeping huge old files in the active log
  path makes diagnostics and future collector changes risky.
- The SIEM ticket bridge had Python file rotation, but no installed system
  logrotate policy for `/var/log/siem-ticket-bridge/*.log`; the systemd stderr
  sidecar log could grow without a platform-level retention guard.
- The bridge state stores dedupe keys as an unordered set, so count pruning is
  not time-aware enough for sustained alert volume.

Impact:

- A noisy Sysmon rule or replayed historical log can clog Wazuh analysis queues.
- Bridge and endpoint logs can consume disk over long-running demo or customer
  deployments.
- Operators have weak health signals for alert backlog, dedupe pressure, and
  log growth.

Fix:

- Add bridge logrotate deployment assets plus configurable rotating file
  handler limits.
- Add time-aware processed-alert retention, per-poll ticket creation caps, and
  bridge status metrics for backlog/log pressure.
- Move historical Sysmon archives out of the hot collection path and tighten
  Sysmon logrotate/test guidance.
- Add false-positive classification and suppression-proposal workflow tests so
  agents can recommend precise rule tuning behind approval gates instead of
  blanket suppressions.

Verification:

- Bridge unit suite passed locally and on AI server: 44 tests, 3 live skipped.
- Dashboard agent lifecycle suite passed locally and on AI server, including
  priority queue ordering tests.
- `deploy/check_bridge_health.py` returned `status: ok`, `error_count: 0`, and
  `backpressure_count: 0`.
- Wazuh/Sysmon E2E passed 16/16 with a fresh marker; bridge created iTop
  Incident `275`, dashboard imported ticket `431`, auto-assigned agent `151`,
  and both dashboard/iTop were resolved after false-positive classification.

### Model-backed smoke runner queued overlapping local agents

Status: fixed in test harness, found during the 2026-05-13 full dashboard smoke
rerun.

Problem:

- The previous ad hoc full-smoke runner continued through model-backed tests
  while auto-assigned agent `136` was still actively working ticket `381`.
- It spawned additional queued smoke agents (`139`, `140`) behind the
  one-agent local model lane.
- `smoke_local_model_agent.py` and `smoke_setup_agent.py` used fixed 720-second
  wait windows and attempted to stop agents when the wrapper expired, which is
  wrong for slow local models and queued lab environments.

Fix:

- Stop only the superseded smoke runner processes in this test lane.
- Stop queued smoke agents through `POST /api/agents/{id}/stop` with an audit
  reason; do not kill the active working agent.
- `smoke_local_model_agent.py`, `smoke_setup_agent.py`, and
  `smoke_itop_agent_close_e2e.py` now wait for `/api/agents/active` to become
  empty before spawning model-backed work.
- Model-backed smoke wait windows default to `AGENT_SMOKE_WAIT_SECONDS=3600`
  and `AGENT_SMOKE_IDLE_WAIT_SECONDS=3600`.
- Smoke wrappers no longer stop a still-running agent on wait-window expiry
  unless `AGENT_SMOKE_STOP_ON_TIMEOUT=true` is explicitly set. They run the
  auditor and print evidence instead.
- `smoke_change_auto_completion.py` self-dispatches into the API container when
  launched from the host, so it uses the installed `asyncpg`/raw PostgreSQL
  runtime without requiring host packages.

Verification:

- Queued smoke agents `139` and `140` were stopped via dashboard API and
  `/api/agents/active` returned only the active worker, then zero after worker
  completion.
- Agent `136` completed ticket `381` end to end: triage note `597`, completed
  approval gate/change `109`, final resolution note `604`, and terminal
  `checkpoint.json` with `status=done`, `progress_pct=100`.
- Fresh serialized smoke run `serial_20260512_234803` started with the patched
  runner and waits for active agents between model-backed phases.

### Setup ticket ignored spawn_agent=false through RACI auto-assignment

Status: fixed, deployed, and verified on 2026-05-13.

Problem:

- `POST /api/setup/ticket` accepted `spawn_agent=false`, but created the setup
  ticket through the generic ticket facade with default `auto_assign=true`.
- The setup plan text contains provider names such as SIEM/EDR, so the EDR/SIEM
  RACI rule matched the setup NormalChange and spawned agent `145` even though
  the setup smoke intentionally requested no automatic agent.
- The spawned agent belonged to this test lane, but it received the wrong
  auto-assignment prompt for a platform setup ticket.

Impact:

- Setup and installer smoke tests can leak into the live local-model queue.
- Operators lose the ability to create review-only setup tickets without
  consuming agent capacity.

Fix:

- `api/routes/setup.py` now calls `ticket_service.create_ticket(...,
  auto_assign=False)` for setup tickets. Setup agent creation is controlled only
  by the explicit `spawn_agent` flag in the setup endpoint.
- `scripts/smoke_setup_platform.py` now asserts setup tickets do not receive an
  auto-assigned agent when `spawn_agent=false`.

Verification:

- API container rebuilt with the patched setup route.
- `python3 scripts/smoke_setup_platform.py http://localhost:25480`: PASS,
  created setup ticket `407`, and `/api/agents/active` remained `0`.
- `python3 scripts/smoke_setup_agent.py http://localhost:25480`: PASS, created
  ticket `408`, explicitly assigned agent `146`, completed task `143` at
  `100%`, wrote the setup context proof note, and left no active process.
- `python3 scripts/smoke_itop_agent_close_e2e.py http://localhost:25480
  --marker CODEX_ITOP_CLOSE_RERUN_20260513_065044`: PASS, created dashboard
  ticket `409` synced to iTop Incident `262` / `I-000271`, agent `147`
  completed task `144`, dashboard and iTop both ended `resolved`, and the iTop
  solution contained the marker.

### Dashboard-created proof tickets bypassed provider sync

Status: fixed in source on 2026-05-15; live cleanup in progress.

Problem:

- Some ad hoc/demo routes and smoke scripts forced `provider: local` or
  `sync_provider: false`.
- CI/CD and workflow proof scripts created local ticket classes that are not
  valid provider classes, including generic `Change`, `BrokerLeaseProof`, and
  `WorkflowReuseSmoke...`.
- This made recent proof tickets look complete in the dashboard while not being
  true provider-synced end-to-end evidence.

Fix:

- `ticket_service.create_ticket()` now normalizes classes before insert and
  provider create.
- Ad hoc agent tickets, setup tickets, CI/CD security tickets, and workflow
  canonicalization smoke tickets no longer opt out of provider sync by default.
- Explicit local-only creation remains available only when the caller selects
  `provider: local` for provider-adapter/RBAC negative controls.

Verification:

- See `docs/PROVIDER_SYNC_CLEANUP_2026-05-15.md`.

### iTop backfill can overwrite local proof titles with generic provider titles

Status: investigated on 2026-05-15; sampled database/API rows retained their
canonical titles after push.

Problem:

- During provider-sync backfill of previously local-only proof tickets, several
  pushed rows were read back from the dashboard API with title `Ticket 1`.
- This suggests the provider sync path can trust a generic provider-side title
  over a more specific dashboard title during or immediately after outbound
  creation.

Impact:

- Demo/proof tickets lose human-readable context even though provider refs are
  created successfully.
- Audit and ticket lists become harder to explain.

Next fix:

- Preserve the canonical dashboard title during outbound create/backfill unless
  the provider title is explicitly newer and non-generic.

### iTop close path used resolution fields for change classes

Status: fixed, deployed, and unit-tested on 2026-05-15.

Problem:

- Provider-close backfill for resolved `RoutineChange` rows failed with
  `Unknown attribute resolution_code from class RoutineChange`.
- The iTop close adapter used Incident/UserRequest resolution fields for all
  ticket classes.

Fix:

- `iTopProvider.close_ticket()` now sends `resolution_code`/`solution` only for
  `Incident` and `UserRequest` classes, and retries without fields if iTop
  reports an unknown close-field attribute.

Verification:

- Local `python -m unittest tests.test_itop_outbound
  tests.test_task_tracker_provider_close`: PASS.
- Remote focused test pass and API rebuild completed on 2026-05-15; live
  ticket `559` closed as iTop `UserRequest` `314` with provider status
  `resolved`.

### Hermes queue invocation passed unsupported top-level `--source` flag

Status: fixed, superseded by chat-mode runner, and verified on 2026-05-18.

Problem:

- Hermes Agent v0.13.0 does not expose a top-level `--source` CLI option.
- The dashboard harness passed `--source soc-dashboard`, causing Hermes to
  interpret `soc-dashboard` as a command/subcommand during real queue execution.
- Direct one-shot Hermes tests still passed because they did not include the
  dashboard runner's full command line.

Fix:

- The dashboard runner now uses `hermes chat -Q --query`, where `--source` is
  supported, instead of the top-level one-shot command path.
- `tests/test_agent_harness.py` asserts Hermes commands use the chat-mode
  source flag, not top-level `-z`.

Verification:

- Real dashboard Hermes smoke completed on ticket `606`, agent `243`, task
  `240`, using model `deepseek/deepseek-v4-flash` with enforced dashboard
  auth.

### Hermes queue invocation passed unsupported top-level `--max-turns` flag

Status: fixed, superseded by chat-mode runner, and verified on 2026-05-18.

Problem:

- Hermes Agent v0.13.0 does not expose a top-level `--max-turns` CLI option.
- The dashboard harness passed `--max-turns 90`, causing Hermes to interpret
  `90` as a command/subcommand during real queue execution.

Fix:

- The dashboard runner now uses `hermes chat -Q --query`, where `--max-turns`
  is supported, while keeping dashboard-level timeout, no-output stall
  detection, approval gates, and task supervision.
- `tests/test_agent_harness.py` asserts Hermes commands use chat-mode
  `--max-turns`, not top-level `-z`.

Verification:

- Real dashboard Hermes smoke completed on ticket `606`, agent `243`, task
  `240`, using model `deepseek/deepseek-v4-flash` with enforced dashboard
  auth.

### Hermes least-privilege queue process inherited `/root` home

Status: fixed, deployed, and verified on 2026-05-15.

Problem:

- Direct `setpriv` Hermes tests passed when `HOME=/home/cereal` was supplied.
- Real dashboard queue runs inherited `HOME=/root` from the API container
  because the harness used `setdefault()` and did not override the existing
  container value.
- After privilege drop to uid/gid `1000`, Hermes dependency checks attempted
  to stat `/root/.modal.toml` and failed with `PermissionError`.

Fix:

- `HermesHarness.build_env()` now explicitly sets `HOME`, `USER`, and
  `LOGNAME` from `HERMES_RUN_HOME`/`HERMES_RUN_USER`, defaulting to the mounted
  Hermes user home `/home/cereal`.

Verification:

- Direct least-privilege container Hermes call returned
  `HERMES_SETPRIV_OK`.
- Real dashboard Hermes smoke completed on ticket `568`, agent `222`, task
  `219`, using model `deepseek/deepseek-v4-flash`.

### Hermes least-privilege worker could not write root-owned checkpoints

Status: fixed, deployed, and verified on 2026-05-15.

Problem:

- The dashboard runner provisions agent workspaces as the API container user.
- Hermes then runs through `setpriv` as uid/gid `1000`.
- Real queue smoke ticket `567` wrote the expected proof ticket note but failed
  to update `/app/agent_work/221/checkpoint.json` because the workspace was
  still owned by root, leaving the supervisor without a final done checkpoint.

Fix:

- `api/services/agent_runner.py` now recursively chowns Hermes workspaces to
  `HERMES_RUN_AS_UID`/`HERMES_RUN_AS_GID` after all context, guard, vault, and
  steering files are provisioned.

Verification:

- Real dashboard Hermes smoke completed on ticket `568`, agent `222`, task
  `219`.
- The workspace `/app/agent_work/222` and final `checkpoint.json` were owned by
  uid/gid `1000`.
- Final checkpoint: `local-model-agent-smoke` / `done` at `100%`.

### Completed Hermes task left stale `active_processes` diagnostic entry

Status: fixed, deployed, and verified on 2026-05-15.

Problem:

- Hermes smoke ticket `568` completed successfully, wrote the proof note, and
  persisted a done checkpoint, but `/api/agents/processes` still listed task
  `219` in the in-memory `active_processes` diagnostic set.
- No OS process existed and `/api/agents/active` was empty, so this was a stale
  runner diagnostic rather than live work.

Fix:

- `get_process_snapshot()` now prunes in-memory process handles whose
  `returncode` is set before returning diagnostic task ids.

Verification:

- After API rebuild, `/api/agents/active` returned `count: 0` and
  `/api/agents/processes` returned `active_processes: []`.

### CI/CD Semgrep report links required provider credentials

Status: fixed, deployed, and verified on 2026-05-19.

Problem:

- CI/CD run details preserved Semgrep/GitLab artifact URLs, but the dashboard
  rendered those external links as the main way to read the report.
- Private GitLab artifacts can require a separate browser session or provider
  token, so operators could see that Semgrep had findings but could not read the
  evidence directly from the dashboard.

Fix:

- Added dashboard-authenticated scanner report endpoints at
  `/api/cicd/runs/{run_id}/reports/{tool}` for `semgrep`, `trivy`,
  `owasp_zap`, and `nuclei`.
- CI/CD run detail now includes internal dashboard report links first and marks
  external provider artifacts as `requires_external_auth`.
- The CI/CD modal now opens full scanner reports from the stored canonical run
  record, including severity, rule id, path, line, message, raw scanner result,
  and optional provider artifact references.

Verification:

- Local suite passed: `163 passed`.
- Live smoke passed on `http://127.0.0.1:25480` with service-token auth:
  CI/CD run `41`, ticket `711`, change `187`, Semgrep dashboard report with one
  stored finding.
- Operational metrics smoke passed with CI/CD run `42` and verified Semgrep
  dashboard report access plus provider-authenticated external artifact labels.
