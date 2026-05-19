# FedRAMP-Style Security Hardening

Last updated: 2026-05-18.

The Agentic Operations dashboard now supports an enforced, deny-by-default
deployment posture suitable for regulated demos and production planning.

## Live Demo Posture

The live AI Server dashboard is configured with:

- `DASHBOARD_AUTH_MODE=header`
- `DASHBOARD_AUTH_ENFORCEMENT=enforce`
- `DASHBOARD_PROTECT_UI=true`
- `DASHBOARD_PUBLIC_HEALTH=false`
- `DASHBOARD_CORS_ORIGINS=` with no wildcard cross-origin access
- trusted-proxy secret stored in vault key `dashboard_trusted_auth_secret`
- service-to-service token stored in vault key `dashboard_service_token`
- signed session-cookie secret stored in vault key `dashboard_session_secret`
- first-party dashboard demo account password stored in vault key
  `demo_account_1`

Unauthenticated API/static/health requests return `403`. Browser HTML requests
to `/` redirect to `/login?next=/`, where the operator can sign in with a
vault-backed dashboard account. Failed UI login attempts redirect back to
`/login?error=1`; successful login creates a signed, HttpOnly
`dashboard_session` cookie. API clients that present bad or missing credentials
receive JSON denial instead of an HTML page.

The trusted proxy/header flow remains the production identity-provider shape.
The first-party login page is the lab/demo fallback for environments where the
operator has not yet placed Keycloak, Entra, Okta, or another IdP proxy in
front of the app. WebSockets authenticate with the same signed cookie, so the
frontend never receives or stores the proxy secret, service token, or password.

## App-Wide Controls

- App middleware evaluates every HTTP request before routing.
- All API route families are mapped to explicit permissions.
- Unknown `/api/*` routes require `platform:unknown`, so non-admin users fail
  closed.
- UI/static/OpenAPI/docs paths require `ui:read` when `DASHBOARD_PROTECT_UI`
  is enabled.
- `/health` requires `health:read` when `DASHBOARD_PUBLIC_HEALTH=false`.
- Denied requests are audited and return no internal stack traces.
- Responses include defensive headers:
  `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`,
  `Permissions-Policy`, and optional HSTS.
- CORS is no longer wildcard by default; set `DASHBOARD_CORS_ORIGINS` only for
  approved origins.

## Identity Modes

### Trusted Proxy Header Mode

Production deployments should put the app behind Keycloak, Entra, Okta, or
another IdP/reverse proxy that authenticates users and injects:

```text
X-Auth-Request-User: <username>
X-Auth-Request-Email: <email>
X-Auth-Provider: <provider>
X-Dashboard-Auth-Secret: <vault-backed shared secret>
```

The application rejects identity headers unless the shared secret matches. This
prevents a direct client from spoofing `X-Auth-Request-User`.

### Service Token Mode

Internal agents, bridges, CI/CD jobs, and setup automation use:

```text
X-Dashboard-Service-Token: <vault-backed service token>
X-Dashboard-Service-User: <service name>
```

This is for platform-owned service traffic only. Human users should use the
trusted proxy flow so role and scope checks use their identity.

### Local Dashboard Login Mode

`POST /api/auth/login` accepts form or JSON credentials for users stored in
`dashboard_users.password_hash`. Passwords are hashed with PBKDF2-SHA256 and
per-password random salts; no plaintext password is stored or logged. Use:

```powershell
$env:DASHBOARD_LOGIN_PASSWORD = python "C:\Users\cereal\.agents\skills\server-manager\credman.py" get demo_account_1
python scripts\set_dashboard_password.py demo_account_1 --display-name "Demo Account 1"
Remove-Item Env:DASHBOARD_LOGIN_PASSWORD
```

For live/container deployments where the script is not inside the API image,
copy a temporary password file into the container, run equivalent raw-SQL
upsert logic with `services.access_control.hash_password`, and delete the file
immediately. Do not echo the password during the handoff.

### Spawned Agent Sessions

Long-running Hermes and Claude Code workers do not receive the global service
token or trusted proxy secret. At spawn time the runner creates a signed,
short-lived `dashboard_session` cookie that embeds the agent's bounded subject:

- roles/capabilities are inherited from the spawning user or service account
  and trimmed by the requested permission envelope
- a ticket-specific scope is added for the assigned ticket
- the session is stored in `dashboard_auth.json` inside the isolated agent
  workspace
- per-agent and container-level curl guards attach it only for dashboard API
  calls from that workspace
- no provider credential values or auth secrets are returned to the agent

This lets endpoint-wide auth stay enforced while allowing agents to read their
assigned ticket, add notes, request approval/access gates, and complete approved
work without bypassing the RBAC layer.

## Database Exposure

The reference compose now binds databases to localhost:

- dashboard PostgreSQL: `127.0.0.1:${SOC_DB_PORT:-5433}`
- agent memory PostgreSQL: `127.0.0.1:${AGENT_MEMORY_DB_PORT:-25490}`
- AI proxy: `127.0.0.1:${AI_PROXY_PORT:-4001}`

The live deployment verified LAN access to those ports is refused. Database
passwords remain required through `SOC_DB_PASSWORD` and
`AGENT_MEMORY_DB_PASSWORD`; source-controlled files contain only vault
references.

## Verification

Run:

```powershell
$env:DASHBOARD_TRUSTED_AUTH_SECRET = python "C:\Users\cereal\.agents\skills\server-manager\credman.py" get dashboard_trusted_auth_secret
$env:DASHBOARD_SERVICE_TOKEN = python "C:\Users\cereal\.agents\skills\server-manager\credman.py" get dashboard_service_token
python scripts\smoke_dashboard_auth_enforcement.py http://192.168.50.222:25480
```

Also verify the first-party browser login:

```powershell
$tmp = New-TemporaryFile
python "C:\Users\cereal\.agents\skills\server-manager\credman.py" get demo_account_1 | Set-Content $tmp
python scripts\smoke_dashboard_login.py http://192.168.50.222:25480 --username demo_account_1 --password-file $tmp
Remove-Item $tmp
```

Expected:

- unauthenticated UI/API/health requests denied
- authenticated admin can load UI, tickets, health, stats, and runner health
- auditor can read access state but cannot mutate tickets
- analyst cannot read access-management users
- service token can call internal runner health
- no secret values are returned

## Live Evidence

Latest live proof on 2026-05-18:

- unauthenticated `/`, `/static/js/dashboard.js`, `/health`,
  `/api/tickets`, and `/api/access/policies`: `403`
- authenticated `demo_account_1` policy/ticket/runner reads: `200`
- `codex-auditor` access read: `200`
- `codex-dev-y` access-user read: `403`
- service-token runner health: `200`
- Playwright authenticated UI pass: Demo Proofs rendered 14 rows, Access page
  showed `demo_account_1 / header / platform-admin`, WebSocket status `Live`,
  and no console errors.
- First-party dashboard login pass: unauthenticated HTML root redirected to
  `/login?next=/`, bad credentials redirected to `/login?error=1&next=/`,
  good credentials created `dashboard_session`, the sidebar showed
  `demo_account_1`, sign-out returned to `/login?logged_out=1`, and the
  post-login page had zero console errors, failed requests, or 4xx responses.
- DB/memory/proxy LAN checks: `5433`, `25491`, and `4401` refused external
  TCP connections; dashboard `25480` remained reachable.
- Broad authenticated API smoke passed: ticket `589`, local mirror ticket
  `590`, change `171`, postmortem `104`, workflow `4`, skill `134`.
- Hermes setup-agent E2E passed after auth hardening: ticket `606`,
  agent `243`, task `240`, expected protected-API note written through the
  scoped agent session.
- Permission/provider matrix passed with marker
  `PERMISSION_PROVIDER_MATRIX_1779148832`: Dev Y/Dev Z row separation,
  auditor mutation denial, denied GitLab/iTop lease checks, approved
  access-request grant, iTop synced tickets `391` and `392`, final granted
  lease `297`, and no active agents left behind.
