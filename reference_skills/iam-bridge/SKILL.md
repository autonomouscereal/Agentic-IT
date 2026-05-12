---
name: iam-bridge
description: >-
  Bidirectional IAM integration between Keycloak (identity provider) and iTop (ITSM platform).
  Handles OIDC/SAML authentication, group-to-profile mapping, user sync, and ticket assignment.
  Includes deployment orchestrator, bidirectional sync engine (CLI + daemon), and E2E test suite (23 tests).
when_to_use: >-
  Integrating Keycloak with iTop, setting up SSO for iTop, configuring OIDC/SAML for ITSM,
  syncing users between Keycloak and iTop, mapping Keycloak groups to iTop profiles,
  or when the user asks about iTop authentication, identity bridging, or IAM integration.
allowed-tools:
  - Read
  - Bash(python *)
  - Bash(python3 *)
  - Bash(find *)
argument-hint: "--deploy --test --status --sync --daemon"
---

# IAM Bridge - Keycloak <-> iTop Integration

Complete bidirectional IAM integration between Keycloak 26.x and iTop 3.2.x via Docker on Linux servers. OIDC (primary) and SAML (fallback) authentication with bidirectional user/group sync.

## Architecture

| Component | File | Purpose |
|---|---|---|
| Deployment Orchestrator | `scripts/bridge_deploy.py` | Full deployment: prerequisite checks, Keycloak setup, iTop setup, sync |
| Keycloak Setup | `scripts/keycloak_setup.py` | Realm, OIDC/SAML clients, groups, roles, protocol mappers |
| iTop Setup | `scripts/itop_setup.py` | Test teams, test users, extension verification, OIDC config generation |
| Sync Engine | `scripts/sync_bridge.py` | Bidirectional sync: Keycloak -> iTop (users), iTop -> Keycloak (teams) |
| E2E Test Suite | `scripts/test_bridge.py` | 23 tests across 9 categories (connectivity, setup, OIDC, SAML, sync, tickets, degradation) |
| Environment Template | `.env.example` | Secret template - copy to `.env` before deploying |
| API Reference | `reference.md` | Keycloak Admin API, iTop REST API, sync protocol details |
| Troubleshooting | `troubleshooting.md` | Common issues, debugging steps, service independence verification |

## System Diagram

```
+----------------+  OIDC/SAML  +----------------+
|   Keycloak     | <----------> |     iTop       |
|  (Identity)    |  combodo-    |    (ITSM)      |
|  Port 8080     |  hybridauth  |  Port 25432    |
+-------+--------+             +--------+-------+
        |                           |
        |      sync_bridge.py       |
        +------->|^<---------------+
                 | Bidirectional
                 | user/group sync
                 v
            .sync_state.json
```

## Prerequisites

- **Keycloak 26.x** running and accessible (default: `http://localhost:8080`)
- **iTop 3.2.x** running and accessible (default: `http://localhost:25432`)
- **Python 3.8+** available on the host
- **Ports 8080, 9000, 25432** must be available
- **`combodo-hybridauth`** and **`combodo-saml`** extensions installed in iTop (manual step via iTop UI)

## Profile Mapping

| Keycloak Group | iTop Profile |
|---|---|
| `itop-administrator` | Administrator |
| `itop-configuration-manager` | Configuration Manager |
| `itop-portal-power-user` | Portal power user |
| `itop-portal-user` | Portal user |
| `itop-support-team` | Support team (ticket assignment) |

## Deployment Blueprint

### Step 1: Configure Credentials

Copy `.env.example` to `.env` and fill in all required values:

```bash
cp .env.example .env
# Edit .env with your Keycloak and iTop passwords
```

Required variables: `KEYCLOAK_ADMIN_PASSWORD`, `ITOP_PASSWORD`. All other variables have sensible defaults.

### Step 2: Run Full Deployment

```bash
python3 scripts/bridge_deploy.py --full --sync
```

This executes the following steps in order:

1. **Prerequisite checks** - Verifies Keycloak health (port 9000), iTop reachability (port 25432), and credential configuration
2. **Keycloak setup** - Creates `itop` realm, OIDC client (`itop-oidc-client`), SAML client (`itop-saml-client`), 5 profile-mapped groups, 3 access roles, 4 OIDC mappers, 2 SAML mappers
3. **iTop setup** - Creates test teams, test users, verifies extension installation, generates OIDC config snippet
4. **Initial sync** - Runs one bidirectional sync cycle

All operations are **idempotent** - safe to run multiple times.

### Step 3: Verify with E2E Tests

```bash
python3 scripts/test_bridge.py
```

Expected: **23/23 tests passing** across 9 categories:
- Connectivity (4) - Keycloak health, Keycloak auth, iTop reachable, iTop auth
- Keycloak Setup (5) - Realm, OIDC client, SAML client, groups, roles
- OIDC Flow (2) - Token request, discovery endpoint
- SAML (1) - Metadata validation
- User Sync (3) - Create user in Keycloak, sync to iTop, create team
- Ticket Assignment (2) - Create incident, assign to team
- Graceful Degradation (2) - Keycloak down -> iTop works, iTop down -> Keycloak works
- Sync Bridge (2) - CLI mode, status
- Cleanup (2) - Remove test artifacts

### Step 4: Install iTop Extensions (Manual)

The `combodo-hybridauth` and `combodo-saml` extensions must be installed in iTop via the UI:

1. Log into iTop as admin
2. Navigate to Admin > Extensions > Install
3. Install `combodo-hybridauth` (OIDC - primary)
4. Install `combodo-saml` (SAML - fallback)
5. Add the OIDC config snippet to `config-itop.php` (saved at `.oidc_config.json` after setup)
6. Set `allowed_login_types` to: `'hybridauth-Keycloak|saml|form|basic'`

## CLI Reference

### bridge_deploy.py - Deployment Orchestrator

```bash
# Show deployment status (services, config, sync state)
python3 scripts/bridge_deploy.py --status

# Generate .env with cryptographically secure random passwords
python3 scripts/bridge_deploy.py --init-env

# Setup Keycloak side only (realm, clients, groups, roles, mappers)
python3 scripts/bridge_deploy.py --setup-keycloak

# Setup iTop side only (teams, users, extension checks)
python3 scripts/bridge_deploy.py --setup-itop

# Full deployment with initial sync
python3 scripts/bridge_deploy.py --full --sync
```

### keycloak_setup.py - Keycloak Configuration

```bash
# Run Keycloak setup (idempotent - safe to re-run)
python3 scripts/keycloak_setup.py
```

Creates: `itop` realm, OIDC client, SAML client, 4 OIDC mappers, 2 SAML mappers, 5 groups, 3 roles.

### itop_setup.py - iTop Configuration

```bash
# Run iTop setup (idempotent - safe to re-run)
python3 scripts/itop_setup.py
```

Creates: test teams, test users, verifies extensions, generates OIDC config.

### sync_bridge.py - Bidirectional Sync Engine

```bash
# Run a single sync cycle (Keycloak <-> iTop)
python3 scripts/sync_bridge.py --sync

# Run as continuous daemon (default: 300s interval)
python3 scripts/sync_bridge.py --daemon --interval 300

# Show sync status (last sync time, synced users/groups)
python3 scripts/sync_bridge.py --status
```

**Sync Directions:**
- **Keycloak -> iTop**: New user -> create `ExternalUser`, group change -> update profile, delete -> disable
- **iTop -> Keycloak**: New team -> create Keycloak group, sync state tracked in `.sync_state.json`

### test_bridge.py - E2E Test Suite

```bash
# Run all 23 tests
python3 scripts/test_bridge.py
```

## Configuration

### .env Variables

| Variable | Description | Default |
|---|---|---|
| `KEYCLOAK_URL` | Keycloak base URL | `http://localhost:8080` |
| `KEYCLOAK_ADMIN_USER` | Keycloak admin username | `admin` |
| `KEYCLOAK_ADMIN_PASSWORD` | Keycloak admin password | (required) |
| `ITOP_URL` | iTop base URL | `http://localhost:25432` |
| `ITOP_USERNAME` | iTop admin username | `admin` |
| `ITOP_PASSWORD` | iTop admin password | (required) |
| `BRIDGE_REALM` | Keycloak realm name | `itop` |
| `BRIDGE_CLIENT_ID` | OIDC client ID | `itop-oidc-client` |
| `BRIDGE_CLIENT_SECRET` | OIDC client secret | (auto-generated) |
| `SYNC_INTERVAL` | Daemon sync interval (seconds) | `300` |
| `SYNC_STATE_FILE` | Path to sync state file | `.sync_state.json` |

## Graceful Degradation

| Scenario | Behavior |
|---|---|
| Keycloak down | Skip Keycloak-side sync, iTop continues normally with local auth |
| iTop down | Skip iTop-side sync, Keycloak continues normally |
| Both down | Log error, wait for next cycle |
| Auth failure | Skip that service, continue with the other |

## Security

- All credentials stored in `.env` files with 600 permissions
- OIDC client secrets generated via `secrets.token_urlsafe(48)`
- No hardcoded passwords in any script
- SSL verification disabled for internal services (configure for production)
- `.env` files must never be committed to version control

## File Structure

```
iam-bridge/
├── SKILL.md               # This file (main skill documentation)
├── reference.md           # API reference (Keycloak + iTop + Bridge) - loaded on demand
├── troubleshooting.md     # Common issues and solutions - loaded on demand
├── .env.example           # Environment template with ALL secrets
├── .env                   # Actual credentials (git-ignored, 600 permissions)
└── scripts/
    ├── bridge_deploy.py   # Deployment orchestrator
    ├── keycloak_setup.py  # Keycloak realm, clients, groups, roles, mappers
    ├── itop_setup.py      # iTop teams, users, extension checks
    ├── sync_bridge.py     # Bidirectional sync engine (CLI + daemon)
    └── test_bridge.py     # E2E test suite (23 tests)
```

## Additional Resources

- For complete API details (Keycloak Admin API, iTop REST API, sync protocol), see [reference.md](reference.md)
- For troubleshooting, debugging, and common issues, see [troubleshooting.md](troubleshooting.md)
