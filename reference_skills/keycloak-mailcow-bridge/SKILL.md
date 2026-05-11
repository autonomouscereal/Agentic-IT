---
name: keycloak-mailcow-bridge
description: >-
  Complete Keycloak <-> Mailcow integration bridge. Configures Keycloak as OIDC Identity Provider
  for Mailcow, auto-provisions users with template mapping, creates distribution groups and shared
  mailboxes, and validates the report-phish workflow. Uses direct MySQL for Mailcow communication
  (HTTP API unavailable in custom deployments). Includes deployment orchestrator, Keycloak setup,
  Mailcow IDP config, bidirectional sync engine, and E2E test suite (48 tests).
when_to_use: >-
  Integrating Keycloak with Mailcow, setting up SSO for email, configuring OIDC for mailcow,
  auto-provisioning mailboxes from Keycloak, distribution groups, shared mailboxes,
  report phish workflow testing, or when the user asks about email authentication via Keycloak.
allowed-tools:
  - Read
  - Bash(python *)
  - Bash(python3 *)
  - Bash(python ssh_client.py *)
  - Bash(find *)
argument-hint: "--deploy --test --status --sync --setup-keycloak --setup-mailcow"
---

# Keycloak-Mailcow Bridge

Complete integration between Keycloak 26.x (Identity Provider) and Mailcow (Email Server) via OIDC on Linux servers.

**CRITICAL ARCHITECTURE NOTE:** The reference deployment uses direct MySQL communication for canonical Mailcow operations via `docker exec mysql-mailcow`. The optional HTTP API shim can be deployed on a nonstandard port for environments that need API-compatible tooling, but direct MySQL remains the supported fallback because custom Mailcow deployments may not expose the stock nginx REST surface.

## Architecture

| Component | File | Purpose |
|---|---|---|
| Deployment Orchestrator | `scripts/deploy.py` | Full deployment: prerequisite checks, Keycloak setup, Mailcow IDP config, sync |
| Keycloak Setup | `scripts/keycloak_setup.py` | Realm, OIDC client, groups, roles, mappers, users |
| Mailcow IDP Config | `scripts/mailcow_idp_config.py` | Domain, distribution groups, shared mailboxes via direct MySQL |
| Sync Engine | `scripts/sync_engine.py` | Bidirectional sync: Keycloak users <-> Mailcow mailboxes via MySQL |
| E2E Test Suite | `scripts/test_integration.py` | 48 tests across 10 categories |
| Optional HTTP API Shim | `scripts/deploy_mailcow_api.py` | Nonstandard-port nginx/php-fpm API shim; direct MySQL remains canonical |
| Environment Template | `.env.example` | Secret template - copy to `.env` before deploying |

## System Diagram

```
+----------------+  OIDC Config              +----------------+
|   Keycloak     | <----------------------   |   Mailcow DB   |
|  (Identity)    |  realm, client, users     |  (MySQL)       |
|  Port 8080     |                           |  docker exec   |
+-------+--------+                           +-------+-------+
        |                                          |
        |  IMAP/SMTP auth                          |  Dovecot/Postfix
        |  via app passwords                       |  ports 143/25
        +---------->|^<----------------------------+
                    | Bidirectional
                    | user/mailbox sync
                    v
               .sync_state.json
```

## Mailcow MySQL Communication

All Mailcow operations use direct MySQL via Docker exec:

```python
# Example: query mailboxes (password from MYSQL_PASSWORD env var / .env file)
docker exec mysql-mailcow mysql -uroot -p"$MYSQL_PASSWORD" \
  -B -e "SELECT username, domain, quota, active FROM mailbox WHERE active = 1" mailcow

# Example: create mailbox
docker exec mysql-mailcow mysql -uroot -p"$MYSQL_PASSWORD" \
  -e "INSERT INTO mailbox (username, domain, password, quota, active) VALUES (...)" mailcow
```

**Database:** `mailcow` (not `mailcow_dockerized`)
**MySQL credentials:** Stored in `.env` file (never hardcoded)

## Optional HTTP API Shim

Use `scripts/deploy_mailcow_api.py` only when a deployment specifically needs Mailcow HTTP API compatibility. The shim must:

- listen on a nonstandard port, normally `8081`
- forward `X-API-Key` to FastCGI as `HTTP_X_API_KEY`
- set `HTTP_SEC_FETCH_DEST=empty`
- create the Mailcow `identity_provider` compatibility table if missing
- reject invalid API keys with HTTP 401
- never print API keys in logs

If the shim returns empty bodies or degraded responses, keep the direct MySQL bridge as canonical and treat the shim as optional until the site-specific Mailcow web code is fixed.

## Dovecot Auth Configuration

Dovecot uses SQL passdb with SSHA512 password scheme:

```
password_query = SELECT CONCAT(username, "@", domain) AS user, password AS password
  FROM mailbox WHERE username = "%n" AND domain = "%d" AND (active = "1" OR active = "2")
```

**Key detail:** Dovecot splits `user@domain.com` into `%n=user` and `%d=domain.com`. The `username` column must store only the local part (before @), NOT the full email address. Mailboxes with full email as username will fail IMAP auth.

## Prerequisites

- **Keycloak 26.x** running and accessible (default: `http://localhost:8080`)
- **Mailcow** running with MySQL accessible via `docker exec`
- **Python 3.8+** available on the host
- **Docker** access to `mysql-mailcow` and `dovecot-mailcow` containers
- **Ports 8080, 25, 143** must be available

## Group/Template Mapping

| Keycloak Group | Keycloak Role | Mailcow Template | Quota |
|---|---|---|---|
| `mailcow-user` | `mail-user` | Default | 5GB |
| `mailcow-premium` | `mail-premium` | Premium | 25GB |
| `mailcow-admin` | `mail-admin` | Admin | 50GB |

## Deployment

### Step 1: Configure Credentials

Copy `.env.example` to `.env` and fill in all required values:

```bash
cp .env.example .env
# Edit .env with your Keycloak and MySQL credentials
```

Required variables: `KEYCLOAK_ADMIN_PASSWORD`, `MYSQL_PASSWORD`.

### Step 2: Run Full Deployment

```bash
python3 scripts/deploy.py
```

This executes:
1. **Prerequisite checks** - Keycloak connectivity, Mailcow MySQL access, Docker containers, credentials
2. **Keycloak setup** - Creates `mailcow` realm, OIDC client, groups, roles, OIDC mappers, test users
3. **Mailcow IDP config** - Domain verification, distribution groups, shared mailboxes via MySQL
4. **Initial sync** - Runs one bidirectional sync cycle

All operations are **idempotent** - safe to run multiple times.

### Step 3: Verify with E2E Tests

```bash
python3 scripts/test_integration.py --all
```

Expected: **47 pass, 0 fail, 1 skip** (48 total) across 10 categories:
- Connectivity (5) - Keycloak HTTP, Mailcow MySQL, SMTP, IMAP
- Keycloak Setup (8) - Realm, client, users, attributes
- OIDC Flow (4) - Discovery, token endpoints
- Mailcow IDP (5) - Domain, mailboxes, aliases, services
- User Provisioning (6) - Mailboxes, quotas, IMAP auth
- Distribution Groups (4) - Aliases, goto targets
- Shared Mailboxes (5) - Shared mailboxes, security, SOC
- Sync Engine (5) - State, sync cycle, template mapping
- Report Phish (2) - SMTP delivery, distribution groups
- Graceful Degradation (4) - Service independence

### Step 4: Run Sync Daemon (Optional)

```bash
python3 scripts/sync_engine.py --daemon --interval 300
```

## CLI Reference

### deploy.py - Deployment Orchestrator

```bash
python3 scripts/deploy.py                  # Full deployment
python3 scripts/deploy.py --prereq-only    # Only check prerequisites
```

### keycloak_setup.py - Keycloak Configuration

```bash
python3 scripts/keycloak_setup.py          # Run Keycloak setup (idempotent)
```

Creates: `mailcow` realm, OIDC client, groups, roles, OIDC mappers, test users.

### mailcow_idp_config.py - Mailcow Configuration

```bash
python3 scripts/mailcow_idp_config.py      # Configure Mailcow IDP + distribution groups + shared mailboxes
```

### sync_engine.py - Bidirectional Sync

```bash
python3 scripts/sync_engine.py --sync      # Single sync cycle
python3 scripts/sync_engine.py --daemon --interval 300  # Continuous daemon
python3 scripts/sync_engine.py --status    # Show sync status
```

### test_integration.py - E2E Test Suite

```bash
python3 scripts/test_integration.py        # Run all tests
python3 scripts/test_integration.py --category connectivity  # Run specific category
```

## Configuration

### .env Variables

| Variable | Description | Default |
|---|---|---|
| `KEYCLOAK_URL` | Keycloak base URL | `http://localhost:8080` |
| `KEYCLOAK_ADMIN_USER` | Keycloak admin username | `admin` |
| `KEYCLOAK_ADMIN_PASSWORD` | Keycloak admin password | (required) |
| `MYSQL_CONTAINER` | Mailcow MySQL Docker container | `mysql-mailcow` |
| `MYSQL_USER` | MySQL user | `root` |
| `MYSQL_PASSWORD` | MySQL root password | (required) |
| `MYSQL_DATABASE` | Mailcow database name | `mailcow` |
| `MAILCOW_DOMAIN` | Email domain for mailboxes | `mailcow.local` |
| `BRIDGE_REALM` | Keycloak realm name | `mailcow` |
| `BRIDGE_CLIENT_ID` | OIDC client ID | `mailcow-oidc` |
| `SYNC_INTERVAL` | Daemon sync interval (seconds) | `300` |
| `TEST_USER_PASSWORD` | Test user password | `<from vault: mailcow-test-user-password>` |

## Known Issues & Workarounds

### Keycloak 26.x User Profile Custom Attributes

Keycloak 26.x silently drops custom attributes (`mailcow_template`) that are not declared in the realm's user profile configuration. The sync engine works around this by tracking state in `.sync_state.json` instead of relying on Keycloak user attributes.

### Mailbox Username Format

Dovecot splits login emails into `%n` (local part) and `%d` (domain). The `username` column in the mailbox table must contain only the local part. Mailboxes created with full email addresses as usernames will fail IMAP authentication. Fix by updating the username column to the local part only.

### Mail Home Directories

New mailboxes require mail home directories at `/var/vmail/{domain}/{username}/` owned by `vmail:vmail`. These must be created inside the `dovecot-mailcow` container. Missing directories cause IMAP authentication failures even with correct passwords.

### Password Hashing

Dovecot expects `{SSHA512}` prefixed passwords. Plain text passwords in the mailbox table will cause IMAP auth failures. Always use the `_hash_password()` helper which generates proper SSHA512 hashes.

## Graceful Degradation

| Scenario | Behavior |
|---|---|
| Keycloak down | Mailcow continues with local auth for existing users. Sync skipped. |
| Mailcow down | Keycloak continues normally. Sync skipped. |
| Both down | Log error, wait for next cycle |
| MySQL unreachable | Sync engine logs warning, continues to next cycle |

## Security

- All credentials stored in `.env` files with 600 permissions
- No hardcoded passwords in any script
- SSL verification disabled for internal services (configure for production)
- `.env` files must never be committed to version control

## File Structure

```
keycloak-mailcow-bridge/
├── SKILL.md               # This file (main skill documentation)
├── reference.md           # API reference (Keycloak + Mailcow + OIDC)
├── troubleshooting.md     # Common issues and solutions
├── .env.example           # Environment template
├── .env                   # Actual credentials (git-ignored)
└── scripts/
    ├── deploy.py           # Deployment orchestrator
    ├── keycloak_setup.py   # Keycloak realm, clients, groups, roles, mappers, users
    ├── mailcow_idp_config.py  # Mailcow IDP config via MySQL
    ├── sync_engine.py      # Bidirectional sync engine (CLI + daemon)
    ├── test_integration.py # E2E test suite (48 tests)
    ├── find_mailcow_creds.py  # Credential discovery helper
    └── setup_bridge_env.py   # Environment setup helper
```

## Additional Resources

- For complete API details (Keycloak Admin API, OIDC protocol), see [reference.md](reference.md)
- For troubleshooting, debugging, and common issues, see [troubleshooting.md](troubleshooting.md)
