---
name: gitlab-keycloak-integration
description: >-
  Integrate GitLab CE 17.11.3 with Keycloak 26.6.0 via OIDC SSO on the same server.
  Includes nginx TLS termination proxy, OIDC realm/client setup, GitLab OmniAuth config,
  authorization workflows (groups, protected branches, MR approvals), E2E test suite (27 tests),
  full diagnostics (13 checks), and day-to-day management CLI.
  Fail-safe design: both services remain independent if the other goes down.
allowed-tools:
  - Read
  - Bash(python *)
  - Bash(python ssh_client.py *)
  - Bash(docker *)
  - Bash(curl *)
  - Bash(bash *)
type: skill
---

# GitLab + Keycloak OIDC Integration

Complete OIDC SSO integration between GitLab CE 17.11.3 and Keycloak 26.6.0 on the same Linux server (127.0.0.1), with an nginx TLS termination proxy, authorization workflows, and comprehensive testing.

## Architecture

```
Browser <--HTTP(80)--> GitLab CE 17.11.3
                          |
                     OIDC callback (HTTP)
                          |
Browser <--HTTPS(8443)--> nginx proxy <----HTTP(8080)----> Keycloak 26.6.0
                                                                        |
                                                                     PostgreSQL 16
```

**Why nginx proxy?** GitLab 17.x requires HTTPS issuer URLs for OIDC. Keycloak runs on HTTP (port 8080). The nginx proxy provides TLS termination so the OIDC issuer is `https://keycloak.internal:8443/realms/gitlab` while Keycloak itself remains unaware of HTTPS.

### Fail-Safety Design

- **Local auth remains enabled** in GitLab (no `auto_sign_in_with_provider`) - at least one local admin account maintained
- **Nginx proxy is a separate container** - if it goes down, GitLab still works with local auth and Keycloak is still directly reachable on 8080
- **Keycloak on `network_mode: host`**, GitLab on `gitlab-net` - no shared network dependency
- **No `auto_sign_in_with_provider`** - users can fall back to local GitLab login

### Network Layout

| Container | Network | Ports | Description |
|-----------|---------|-------|-------------|
| `gitlab` | `gitlab-net` (bridge) | 80 (HTTP), 2222 (SSH) | GitLab CE platform |
| `gitlab-runner` | `gitlab-net` (bridge) | None (internal) | CI/CD job executor |
| `keycloak` | `host` | 8080 (HTTP), 5432 (PG) | Keycloak identity provider |
| `keycloak-nginx` | `host` | 8443 (HTTPS) | TLS termination proxy |

## File Structure

```
/opt/agentic-it/gitlab-keycloak-integration/    # Server deployment directory
|-- docker-compose.yml          # Nginx proxy service definition
|-- nginx/
|   `-- nginx.conf              # Nginx config: HTTPS 8443 -> HTTP 8080
|-- certs/
|   |-- generate-certs.sh       # Self-signed cert generator with SAN
|   |-- ca-cert.pem             # CA certificate (generated)
|   |-- ca-key.pem              # CA private key (generated)
|   |-- server-cert.pem         # Server certificate with SAN (generated)
|   `-- server-key.pem          # Server private key (generated)
`-- scripts/
    |-- diagnose.sh             # Full diagnostic tool (13 checks)
    |-- test_integration.sh     # E2E test suite (27 tests)
    |-- manage_integration.sh   # Day-to-day management CLI
    |-- setup-gitlab-auth.py    # GitLab groups, projects, protected branches via API
    |-- fix-gitlab-oidc.py      # Python helper to write correct gitlab.rb OIDC config
    |-- setup_oidc.py           # Keycloak realm, client, mappers, groups, roles, users
    `-- backup_restore.sh       # GitLab backup/restore utility

C:/Users/me/.Codex/skills/gitlab-keycloak-integration/  # Local skill directory
|-- SKILL.md                      # This file
|-- docker-compose.yml            # Template (identical to server copy)
|-- nginx/                        # Nginx config
|-- certs/                        # Cert generation script
`-- scripts/                      # All scripts above
```

## Prerequisites

- **GitLab CE 17.11.3** running via Docker (managed by `gitlab-manager` skill)
- **Keycloak 26.6.0** running via Docker (managed by `keycloak-manager` skill)
- Both services already deployed and healthy on 127.0.0.1
- **server-manager** skill configured with SSH access to the server

## Integration Steps

### Phase 1: TLS Certificates + Nginx Proxy

```bash
# 1. Generate self-signed TLS certificates with SAN
cd /opt/agentic-it/gitlab-keycloak-integration
bash certs/generate-certs.sh

# Certificates valid for: keycloak.internal, localhost, 127.0.0.1, 127.0.0.1
# SAN includes both DNS names and IP addresses for flexibility

# 2. Deploy nginx proxy container
cd /opt/agentic-it/gitlab-keycloak-integration
docker compose up -d

# 3. Verify proxy health
curl -sk https://localhost:8443/nginx-health    # Should return "ok"
curl -sk https://localhost:8443/realms/gitlab   # Should return 200
```

**Nginx config highlights:**
- Listens on port 8443 with TLS (TLSv1.2 + TLSv1.3 only)
- Proxies all requests to `http://localhost:8080` (Keycloak)
- Sets `X-Forwarded-Proto: https` so Keycloak generates HTTPS URLs
- Includes HSTS, X-Frame-Options, X-Content-Type-Options headers
- Dedicated `/nginx-health` endpoint for container healthchecks

### Phase 2: Keycloak OIDC Configuration

```bash
# Run the OIDC setup script (creates realm, client, mappers, groups, roles, users)
cd /opt/agentic-it/gitlab-keycloak-integration
python3 scripts/setup_oidc.py
```

This configures:

**Realm:** `gitlab`
- OIDC discovery at `https://keycloak.internal:8443/realms/gitlab/.well-known/openid-configuration`

**Client:** `gitlab` (confidential, standard flow + client credentials)
- Redirect URI: `http://127.0.0.1/users/auth/openid_connect/callback`
- Client secret stored securely

**Protocol Mappers:**
| Mapper | Claim | Source |
|--------|-------|--------|
| `username` | `preferred_username` | User username |
| `email` | `email` | User email |
| `groups` | `groups` | Keycloak groups |
| `realm_roles` | `realm_roles` | Realm roles |

**Groups:** `gitlab-admins`, `gitlab-developers`, `gitlab-viewers`, `gitlab-auditors`

**Roles:** `gitlab-admin`, `gitlab-developer`, `gitlab-viewer`

**Test Users:** `test-admin` (in gitlab-admins), `test-dev` (in gitlab-developers), `test-viewer` (in gitlab-viewers)

### Phase 3: GitLab OmniAuth Configuration

```bash
# Fix the gitlab.rb OIDC configuration using the Python helper
# (Avoids shell quoting issues with Ruby config)
docker exec -it gitlab python3 /tmp/fix-gitlab-oidc.py

# Reconfigure GitLab
docker exec gitlab gitlab-ctl reconfigure

# Verify Keycloak button appears on login page
curl -s http://localhost/users/sign_in | grep -q "Keycloak" && echo "OK"
```

**Critical gitlab.rb config:**

```ruby
gitlab_rails["omniauth_providers"] = [
  {
    "name" => "openid_connect",
    "label" => "Keycloak",
    "issuer" => "https://keycloak.internal:8443/realms/gitlab",
    "client_options" => {
      "identifier" => "gitlab",
      "secret" => "<client-secret-from-keycloak>",
      "redirect_uri" => "http://127.0.0.1/users/auth/openid_connect/callback"
    }
  }
]
gitlab_rails["omniauth_enabled"] = true
gitlab_rails["omniauth_block_auto_created_users"] = true
# NOTE: auto_sign_in_with_provider is intentionally NOT set - keeps local auth as fallback
```

**Why the Python helper?** Shell quoting strips double quotes from Ruby config. The `fix-gitlab-oidc.py` script writes proper Ruby quoting using `chr(34)` for quote characters.

### Phase 4: Authorization Workflows

```bash
# Set up GitLab groups, projects, protected branches, and CI/CD pipelines
cd /opt/agentic-it/gitlab-keycloak-integration
python3 scripts/setup-gitlab-auth.py
```

Creates:
- **GitLab groups** mirroring Keycloak groups (gitlab-admins, gitlab-developers, gitlab-viewers)
- **Test project** with protected `main` and `develop` branches (maintainers-only push/merge)
- **MR approval rules** requiring 1+ approval before merge
- **CI/CD pipeline** with test, build, and deploy stages
- **Develop branch** for testing workflows

### Phase 5: Verify Everything

```bash
# Run diagnostics (13 checks)
bash /opt/agentic-it/gitlab-keycloak-integration/scripts/diagnose.sh

# Run E2E test suite (27 tests)
bash /opt/agentic-it/gitlab-keycloak-integration/scripts/test_integration.sh
```

Expected: **13/13 diagnostics pass** and **27/27 tests pass**.

## Management CLI

```bash
# Show status of all components
bash scripts/manage_integration.sh status

# Restart all services gracefully
bash scripts/manage_integration.sh restart

# Restart individual services
bash scripts/manage_integration.sh restart-nginx
bash scripts/manage_integration.sh restart-keycloak
bash scripts/manage_integration.sh restart-gitlab

# View logs (last 50 lines)
bash scripts/manage_integration.sh logs keycloak
bash scripts/manage_integration.sh logs nginx
bash scripts/manage_integration.sh logs gitlab
bash scripts/manage_integration.sh logs runner

# Run diagnostics
bash scripts/manage_integration.sh diagnose

# Run tests
bash scripts/manage_integration.sh test

# Show OIDC configuration
bash scripts/manage_integration.sh oidc-status

# Check certificate expiry
bash scripts/manage_integration.sh certs-expiry
```

## E2E Test Suite

`scripts/test_integration.sh` runs 27 tests across 9 groups:

| Group | Tests | Validates |
|-------|-------|-----------|
| Keycloak Health | 6 | Container, discovery endpoint, HTTPS issuer, auth/token/userinfo endpoints |
| Nginx Proxy | 3 | Container, health endpoint, proxy pass-through |
| GitLab Services | 3 | Container, gitlab-ctl status, login page |
| OIDC Integration | 6 | Keycloak button, form action, gitlab.rb config, correct issuer, omniauth enabled, auto-create blocked |
| Groups & Projects | 3 | All three GitLab groups exist |
| Protected Branches | 2 | main and develop branches protected |
| CI/CD Pipeline | 1 | .gitlab-ci.yml with stages |
| Fail-Safety | 2 | GitLab works independently, Keycloak accessible on 8080 |
| GitLab Runner | 1 | Runner container running |

## Diagnostic Tool

`scripts/diagnose.sh` performs 13 checks:

| Check | What it validates |
|-------|-------------------|
| Container Status (x4) | keycloak, keycloak-nginx, gitlab, gitlab-runner all running |
| OIDC Discovery | Issuer URL returns HTTPS |
| Realm Access | gitlab realm reachable via proxy |
| Nginx Proxy | Health endpoint responds |
| GitLab Services | gitlab-ctl shows all services running |
| OmniAuth Config | OIDC provider entries in gitlab.rb |
| Login Page | Keycloak button rendered |
| Groups (x3) | gitlab-admins, gitlab-developers, gitlab-viewers exist |

## Key URLs

| Interface | URL |
|-----------|-----|
| GitLab Web UI | `http://127.0.0.1` |
| GitLab API | `http://127.0.0.1/api/v4/...` |
| Keycloak Admin (direct) | `http://127.0.0.1:8080/admin` |
| Keycloak via Proxy | `https://127.0.0.1:8443` |
| OIDC Discovery | `https://keycloak.internal:8443/realms/gitlab/.well-known/openid-configuration` |
| Nginx Health | `https://localhost:8443/nginx-health` |

## Troubleshooting

### OIDC issuer must be HTTPS

GitLab 17.x rejects HTTP issuers. If you see "Issuer URL not HTTPS" in diagnostics:
```bash
# Verify the proxy is serving HTTPS
curl -sk https://localhost:8443/realms/gitlab/.well-known/openid-configuration | python3 -m json.tool | head -5

# Check that Keycloak is generating HTTPS URLs (X-Forwarded-Proto must be set)
docker logs keycloak-nginx --tail 20
```

### Shell quoting breaks gitlab.rb

Bash strips double quotes from Ruby config. **Always use the `fix-gitlab-oidc.py` script** to write OIDC config:
```bash
# Upload the script
scp scripts/fix-gitlab-oidc.py gitlab:/tmp/fix-gitlab-oidc.py
# Run inside container
docker exec gitlab python3 /tmp/fix-gitlab-oidc.py
```

### `((PASS++))` crashes with `set -e`

Bash arithmetic `((VAR++))` returns exit code 1 when VAR is 0 (because the old value 0 is falsy). All scripts use the safe pattern `VAR=$((VAR + 1))` instead.

### `pipefail` breaks piped commands

With `set -euo pipefail`, piped commands like `docker exec gitlab gitlab-ctl status | grep "run:"` fail if the left side returns non-zero. Scripts work around this by capturing output first:
```bash
gl_status=$(docker exec gitlab gitlab-ctl status 2>/dev/null || true)
echo "$gl_status" | grep -q "run:"
```

### Keycloak 26.x breaking changes

- OIDC discovery endpoint path changed from `/.well-known/openid-configuration` to `/realms/{realm}/.well-known/openid-configuration`
- `KC_PROXY_HEADERS` values changed - verify proxy headers match Keycloak 26.x expectations
- Health endpoint moved to management port 9000

### GitLab 17.x breaking changes

- OAuth password grant deprecated - cannot create PATs via `POST /api/v4/session`
- Session API removed - all API calls require PAT headers
- Project PUT endpoint requires all fields - partial updates fail with 400
- Use `gitlab-rails runner` for PAT creation inside the container

### Reconfigure GitLab after config changes

Any change to gitlab.rb requires reconfiguration:
```bash
docker exec gitlab gitlab-ctl reconfigure
```

### Certificate issues

```bash
# Check cert expiry
openssl x509 -in /opt/agentic-it/gitlab-keycloak-integration/certs/server-cert.pem -noout -dates

# Regenerate certs (10-year validity)
bash /opt/agentic-it/gitlab-keycloak-integration/certs/generate-certs.sh
docker restart keycloak-nginx
```

## Security Model

1. **Self-signed TLS** - Appropriate for internal LAN; replace with Let's Encrypt for external exposure
2. **No hardcoded secrets** - Client secrets generated by Keycloak, stored in gitlab.rb inside container
3. **Local auth fallback** - GitLab admin account remains accessible if Keycloak is down
4. **`omniauth_block_auto_created_users: true`** - Only pre-approved users can sign up via OIDC
5. **Protected branches** - main and develop require maintainer-level access to push/merge
6. **MR approvals** - At least 1 approval required before merge
7. **Cert/key permissions** - Private keys set to `chmod 600`

## When to Use

Use this skill when you need to:
- Integrate GitLab with Keycloak for OIDC SSO
- Set up authorization workflows (groups, roles, protected branches, MR approvals)
- Diagnose OIDC integration issues
- Test the complete integration end-to-end
- Manage the integration day-to-day (restarts, logs, status)
- Re-deploy the integration on a new server

## Re-deployment Checklist

To deploy this integration on a new server:

1. [ ] Deploy GitLab CE 17.x via `gitlab-manager` skill
2. [ ] Deploy Keycloak 26.x via `keycloak-manager` skill
3. [ ] Copy `gitlab-keycloak-integration/` to server at `/opt/agentic-it/gitlab-keycloak-integration/`
4. [ ] Generate TLS certs: `bash certs/generate-certs.sh`
5. [ ] Start nginx proxy: `docker compose up -d`
6. [ ] Run Keycloak OIDC setup: `python3 scripts/setup_oidc.py`
7. [ ] Fix GitLab OIDC config: upload and run `fix-gitlab-oidc.py` inside container
8. [ ] Reconfigure GitLab: `docker exec gitlab gitlab-ctl reconfigure`
9. [ ] Set up authorization: `python3 scripts/setup-gitlab-auth.py`
10. [ ] Run diagnostics: `bash scripts/diagnose.sh` (expect 13/13 pass)
11. [ ] Run E2E tests: `bash scripts/test_integration.sh` (expect 27/27 pass)

## Model

**Agent model:** `qwen/qwen3.6-27b`
