---
name: platform-credentials
description: >
  Multi-platform credential management for all AI Server services (iTop, Wazuh, GitLab, Keycloak, Mailcow, SOC Dashboard).
  Covers credential storage via encrypted vault, user management across platforms,
  the demo_account_1 unified credentials, and the multi-platform user manager script.
  Use when creating/deleting users, checking credentials, managing passwords, or troubleshooting login issues.
allowed-tools:
  - Read
  - Bash(python *)
  - Bash(docker *)
---

# Platform Credentials Management

All AI Server platform credentials are managed through the **Server Manager v2 encrypted credential vault**.
**NO PASSWORDS ARE HARDCODED.** All secrets are encrypted in `.cred_vault.json`.

## Credential Vault

### Location
- Vault script: `C:/Users/cereal/.agents/skills/server-manager/credman.py`
- Encrypted store: `C:/Users/cereal/.agents/skills/server-manager/.cred_vault.json`
- Server config: `C:/Users/cereal/.agents/skills/server-manager/servers.json`

### Usage
```bash
# Store a password
python "C:/Users/cereal/.agents/skills/server-manager/credman.py" set <server-name> "<password>"

# List servers
python "C:/Users/cereal/.agents/skills/server-manager/ssh_client.py" --list-servers
```

## Platform Services & Ports

| Platform | URL | Port | Auth Method | Status |
|----------|-----|------|-------------|--------|
| SOC Dashboard | http://192.168.50.222:25480 | 25480 | Direct (FastAPI) | Operational |
| iTop | http://192.168.50.222:25432 | 25432 | Local DB (bcrypt) | Demo REST login verified |
| Wazuh Dashboard | https://192.168.50.222:26443 | 26443 | OpenSearch Security | Demo backend auth verified |
| Wazuh API | https://127.0.0.1:26500 | 26500 | Native Wazuh API auth | Demo API auth verified |
| GitLab | http://192.168.50.222:80 | 80 | Local Rails password + Keycloak OIDC | Rails password verified; OIDC routing depends on deployment |
| Keycloak | Internal only | N/A | Master realm admin | Operational |
| Mailcow | Internal only | N/A | Local + Keycloak bridge | Mailbox exists |

## demo_account_1 Unified Credentials

**Username:** `demo_account_1`
**Password:** Stored in credential vault â€” retrieve via `credman.py`

### Current Status Per Platform

| Platform | User Exists | Password Set | Login Works | Notes |
|----------|:-----------:|:------------:|:-----------:|-------|
| Keycloak (all realms) | YES | YES | N/A | Central IDP, passwords set in wazuh/gitlab/itop realms |
| iTop | YES | YES (bcrypt, 60 chars) | YES | Valid `UserLocal`, profiles `Administrator` + `REST Services User` |
| Wazuh API | YES | YES | YES | Updated via native Wazuh API; direct SQLite is fallback only |
| Wazuh OpenSearch Security | YES | YES | YES | Synced to `internal_users.yml`, security config reloaded |
| GitLab | YES | YES (Rails verified) | YES | Local Rails password validation passes; browser SSO depends on routing |
| Mailcow | YES | Delegated to Keycloak bridge | YES | Mailbox exists and active |

## Multi-Platform User Manager

### Location
- **Script:** `/home/cereal/multiplatform_user_manager.py` (on AI Server)
- **Status:** patched 2026-05-11; live auth verified for `demo_account_1`

### Capabilities
Unified CLI for managing users across all 5 platforms:
- `create` â€” Create user on all platforms
- `delete` â€” Remove user from all platforms
- `update` â€” Modify user attributes
- `list` â€” List users across platforms
- `set-password` â€” Set password across platforms

### Platform Backends
- **KeycloakBackend** â€” Admin REST API via `keycloak_admin.py`
- **iTopBackend** â€” Direct MariaDB SQL (bcrypt password hashing)
- **WazuhBackend** â€” Direct RBAC SQLite (scrypt password hashing)
- **GitLabBackend** â€” Rails runner (Ruby code templates)
- **MailcowBackend** â€” API or direct MySQL

### Fixed Bugs in User Manager
1. **Hardcoded DB passwords removed**: iTop and Mailcow DB credentials are resolved from container environment or explicit environment variables.
2. **Shell expansion fixed**: SQL is streamed to database clients over stdin, so bcrypt/scrypt `$` characters are not expanded by shell.
3. **Wazuh fixed**: the manager now uses the native Wazuh API for user/password/role/run_as updates and syncs Wazuh Dashboard OpenSearch Security.
4. **iTop fixed**: the demo user was rebuilt as a valid `UserLocal` object with initialized local-auth fields and required profiles.
5. **GitLab fixed**: GitLab user updates use the GitLab 17-compatible `User.new` / `save(validate: false)` flow and local Rails password checks pass.

## Credential Storage Locations

### Where Each Platform Stores Credentials

| Platform | Storage | Format | Container/Path |
|----------|---------|--------|----------------|
| Keycloak | PostgreSQL DB | Encrypted | `keycloak-db-1` |
| iTop | MariaDB `priv_user_local.password_hash` | bcrypt `$2y$12$` | `itop-deployment-db-1` |
| Wazuh API | Wazuh REST API preferred; SQLite fallback | native API / scrypt:N:R:P$salt$hash | `wazuh_deploy-wazuh.manager-1` |
| Wazuh Dashboard | OpenSearch Security | bcrypt `$2y$12$` | `wazuh_deploy-wazuh.indexer-1` â†’ `/usr/share/wazuh-indexer/config/opensearch-security/internal_users.yml` |
| GitLab | PostgreSQL | Rails encrypted | `gitlab` |
| Mailcow | MySQL | Mailcow hash | `mysql-mailcow` |

## Important Notes

- **Wazuh has TWO authentication layers**: OpenSearch Security (dashboard UI login) AND RBAC DB (API access). Both need the user created.
- **GitLab uses Keycloak OIDC SSO**: Web login goes through Keycloak, not GitLab's own DB. The `keycloak.internal:8443` hostname is currently unreachable.
- **Keycloak is internal-only**: No external port mapping. Services reach it via Docker network hostname resolution.
- **iTop uses local auth**: Form login against MariaDB bcrypt hashes. No SSO configured.

## Detailed Troubleshooting

For detailed login issue diagnosis and fix steps, see the [login-troubleshooting](../login-troubleshooting/SKILL.md) skill.

