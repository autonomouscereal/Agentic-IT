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

Unauthenticated requests to `/`, `/static/*`, `/health`, and every `/api/*`
route return `403`. The UI is reachable only when a trusted auth proxy or test
harness supplies the authenticated identity plus `X-Dashboard-Auth-Secret`.

The browser flow mints a signed, HttpOnly `dashboard_session` cookie after a
trusted proxy authenticates the first page request. WebSockets then authenticate
with that cookie, so the frontend never receives or stores the proxy secret.

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
