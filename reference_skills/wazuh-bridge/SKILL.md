---
name: wazuh-bridge
description: >-
  Unidirectional IAM integration between Keycloak (identity provider) and Wazuh (SIEM platform).
  Handles user provisioning, group-to-role mapping, and RBAC synchronization via Wazuh REST API.
  Includes deployment orchestrator, sync engine (CLI + daemon), and E2E test suite (24 tests).
allowed-tools:
  - Read
  - Bash(python *)
  - Bash(python3 *)
  - Bash(find *)
argument-hint: "--deploy --test --status --sync --daemon"
---

# Wazuh Bridge - Keycloak -> Wazuh IAM Integration

Complete IAM integration between Keycloak 26.x and Wazuh 4.14.x via Docker on Linux servers. Keycloak as identity provider with API-based user provisioning and RBAC role mapping.

## Architecture

| Component | File | Purpose |
|---|---|---|
| Deployment Orchestrator | `scripts/bridge_deploy.py` | Full deployment: prerequisite checks, Keycloak setup, Wazuh setup, sync |
| Keycloak Setup | `scripts/keycloak_setup.py` | Realm, OIDC client, RBAC groups, roles, protocol mappers |
| Wazuh Setup | `scripts/wazuh_setup.py` | API verification, JWT auth, test users, role validation |
| Sync Engine | `scripts/sync_bridge.py` | Unidirectional sync: Keycloak -> Wazuh (user provisioning) |
| E2E Test Suite | `scripts/test_bridge.py` | 24 tests across 8 categories |
| Environment Template | `.env.example` | Secret template - copy to `.env` before deploying |
| API Reference | `reference.md` | Keycloak Admin API, Wazuh Security API, sync protocol |
| Troubleshooting | `troubleshooting.md` | Common issues, debugging steps, service independence |

## System Diagram

```
+----------------+  API sync      +----------------+
|   Keycloak     | -------------> |     Wazuh      |
|  (Identity)    |  user provision |    (SIEM)      |
|  Port 8080     |                |  Port 26500    |
+-------+--------+                +-------+--------+
        |                         |
        |    sync_bridge.py       |
        +----->|v<----------------+
               | Unidirectional
               | user/group sync
               v
          .sync_state.json
```

## Prerequisites

- **Keycloak 26.x** running and accessible (default: `http://localhost:8080`)
- **Wazuh 4.14.x** running and accessible (default: `https://127.0.0.1:26500`)
- **Python 3.8+** available on the host
- **Ports 8080, 9000, 26500** must be available
- Wazuh does NOT natively support OIDC/SAML - integration is API-based user sync

## Role Mapping

| Keycloak Group | Wazuh Role | Description |
|---|---|---|
| `wazuh-administrator` | `administrator` | Full API access |
| `wazuh-security-analyst` | `readonly` | Read-only monitoring |
| `wazuh-agent-admin` | `agents_admin` | Agent management |
| `wazuh-cluster-admin` | `cluster_admin` | Cluster/manager mgmt |
| `wazuh-user-admin` | `users_admin` | User management |

## Deployment Blueprint

### Step 1: Configure Credentials

Copy `.env.example` to `.env` and fill in all required values:

```bash
cp .env.example .env
# Edit .env with your Keycloak and Wazuh passwords
```

Required variables: `KEYCLOAK_ADMIN_PASSWORD`, `WAZUH_PASSWORD`. All other variables have sensible defaults.

### Step 2: Run Full Deployment

```bash
python3 scripts/bridge_deploy.py --full --sync
```

This executes:
1. **Prerequisite checks** - Keycloak health (port 9000), Wazuh API (port 26500), credentials
2. **Keycloak setup** - Creates `wazuh` realm, OIDC client, 5 RBAC groups, 3 access roles, 3 OIDC mappers
3. **Wazuh setup** - Verifies API access, JWT auth, creates test users
4. **Initial sync** - Runs one unidirectional sync cycle

All operations are **idempotent** - safe to run multiple times.

### Step 3: Verify with E2E Tests

```bash
python3 scripts/test_bridge.py
```

Expected: **24/24 tests passing** across 8 categories:
- Connectivity (4) - Keycloak health, Keycloak auth, Wazuh reachable, Wazuh auth
- Keycloak Setup (4) - Realm, OIDC client, groups, roles
- Wazuh Setup (4) - API users listable, roles listable, manager status, test users
- User Sync (3) - Create user in Keycloak, sync to Wazuh, delete propagation
- Role Mapping (2) - Role mappings accessible, default roles present
- Graceful Degradation (2) - Keycloak down -> Wazuh works, Wazuh down -> Keycloak works
- Sync Bridge (3) - CLI sync, status data, sync timestamp
- Cleanup (2) - Remove test artifacts

## CLI Reference

### bridge_deploy.py - Deployment Orchestrator

```bash
python3 scripts/bridge_deploy.py --status
python3 scripts/bridge_deploy.py --init-env
python3 scripts/bridge_deploy.py --setup-keycloak
python3 scripts/bridge_deploy.py --setup-wazuh
python3 scripts/bridge_deploy.py --full --sync
```

### keycloak_setup.py - Keycloak Configuration

```bash
python3 scripts/keycloak_setup.py
```

Creates: `wazuh` realm, OIDC client, 3 OIDC mappers, 5 RBAC groups, 3 access roles.

### wazuh_setup.py - Wazuh Configuration

```bash
python3 scripts/wazuh_setup.py
```

Verifies: API connectivity, JWT auth, manager status, creates test users.

### sync_bridge.py - Sync Engine

```bash
python3 scripts/sync_bridge.py --sync
python3 scripts/sync_bridge.py --daemon --interval 300
python3 scripts/sync_bridge.py --status
```

**Sync Direction:** Keycloak -> Wazuh (user provisioning)
- New Keycloak user -> create Wazuh API user
- Keycloak group change -> update role mapping
- Keycloak user deleted -> disable in Wazuh
- Sync state tracked in `.sync_state.json`

## Configuration

### .env Variables

| Variable | Description | Default |
|---|---|---|
| `KEYCLOAK_URL` | Keycloak base URL | `http://localhost:8080` |
| `KEYCLOAK_ADMIN_USER` | Keycloak admin username | `admin` |
| `KEYCLOAK_ADMIN_PASSWORD` | Keycloak admin password | (required) |
| `WAZUH_URL` | Wazuh API URL | `https://127.0.0.1:26500` |
| `WAZUH_USERNAME` | Wazuh API username | `wazuh-wui` |
| `WAZUH_PASSWORD` | Wazuh API password | (required) |
| `BRIDGE_REALM` | Keycloak realm name | `wazuh` |
| `SYNC_INTERVAL` | Daemon sync interval (seconds) | `300` |
| `SYNC_STATE_FILE` | Path to sync state file | `.sync_state.json` |

## Graceful Degradation

| Scenario | Behavior |
|---|---|
| Keycloak down | Skip Keycloak-side sync, Wazuh continues normally |
| Wazuh down | Skip Wazuh-side sync, Keycloak continues normally |
| Both down | Log error, wait for next cycle |
| Auth failure | Skip that service, continue with the other |

## Security

- All credentials stored in `.env` files with 600 permissions
- Client secrets generated via `secrets.token_urlsafe(48)`
- No hardcoded passwords in any script
- SSL verification disabled for internal services (configure for production)
- `.env` files must never be committed to version control

## File Structure

```
wazuh-bridge/
|-- SKILL.md               # This file (main skill documentation)
|-- reference.md           # API reference (Keycloak + Wazuh + Bridge)
|-- troubleshooting.md     # Common issues and solutions
|-- .env.example           # Environment template
|-- .env                   # Actual credentials (git-ignored)
`-- scripts/
    |-- bridge_deploy.py   # Deployment orchestrator
    |-- keycloak_setup.py  # Keycloak realm, clients, groups, roles, mappers
    |-- wazuh_setup.py     # Wazuh API verification, test users
    |-- sync_bridge.py     # Unidirectional sync engine (CLI + daemon)
    `-- test_bridge.py     # E2E test suite (24 tests)
```

## Additional Resources

- For complete API details, see [reference.md](reference.md)
- For troubleshooting and debugging, see [troubleshooting.md](troubleshooting.md)
