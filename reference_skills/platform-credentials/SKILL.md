---
name: platform-credentials
description: >
  Multi-platform credential management for all AI Server services (Agentic Operations, iTop, Wazuh, GitLab, Keycloak, Mailcow).
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
| Agentic Operations | http://192.168.50.222:25480 | 25480 | Direct (FastAPI) | Operational |
| iTop | http://192.168.50.222:25432 | 25432 | Local DB (bcrypt) | Demo REST login verified |
| Wazuh Dashboard | https://192.168.50.222:26443 | 26443 | OpenSearch Security | Demo UI/backend auth verified |
| Wazuh API | https://127.0.0.1:26500 | 26500 | Native Wazuh API auth | Demo native API token issuance verified |
| GitLab | http://192.168.50.222:80 | 80 | Local Rails password + Keycloak OIDC | Demo local login and full Keycloak SSO verified |
| Keycloak | Internal only | N/A | Master realm admin | Operational |
| Mailcow | http://192.168.50.222:2581 | 2581 | Local + Keycloak bridge | Demo admin UI, webmail, IMAP/SMTP, and report-phish quarantine verified |

## demo_account_1 Unified Credentials

**Username:** `demo_account_1`
**Password:** Stored in credential vault - retrieve via `credman.py`

### Current Status Per Platform

| Platform | User Exists | Password Set | Login Works | Notes |
|----------|:-----------:|:------------:|:-----------:|-------|
| Keycloak (all realms) | YES | YES | N/A | Central IDP, passwords set in wazuh/gitlab/itop realms |
| iTop | YES | YES (bcrypt, 60 chars) | YES | Valid `UserLocal`, profiles `Administrator` + `REST Services User` |
| Wazuh API | YES | YES | YES | Native API auth issues a token for the demo user |
| Wazuh OpenSearch Security | YES | YES | YES | Synced to `internal_users.yml`, security config reloaded |
| GitLab | YES | YES (Rails verified) | YES | Local login works; Keycloak SSO lands in GitLab as SOC Demo Account |
| Mailcow | YES | YES (Mailcow `{BLF-CRYPT}` hash) | YES | Admin UI redirects to `/admin/dashboard`; `/webmail` is Roundcube using `demo_account_1@mailcow.local`; Report Phish proof is ticket `580`, iTop Incident `372`, agent `229`, access request `581`, quarantine id `21a705b151642568d375c748a9ea1a6b` |

## Multi-Platform User Manager

### Location
- **Script:** `/home/cereal/multiplatform_user_manager.py` (on AI Server)
- **Status:** patched 2026-05-11; live auth verified for `demo_account_1`

### Capabilities
Unified CLI for managing users across all 5 platforms:
- `create` - Create user on all platforms
- `delete` - Remove user from all platforms
- `update` - Modify user attributes
- `list` - List users across platforms
- `set-password` - Set password across platforms

### Platform Backends
- **KeycloakBackend** - Admin REST API via `keycloak_admin.py`
- **iTopBackend** - Direct MariaDB SQL (bcrypt password hashing)
- **WazuhBackend** - Direct RBAC SQLite (scrypt password hashing)
- **GitLabBackend** - Rails runner (Ruby code templates)
- **MailcowBackend** - API or direct MySQL

### Fixed Bugs in User Manager
1. **Hardcoded DB passwords removed**: iTop and Mailcow DB credentials are resolved from container environment or explicit environment variables.
2. **Shell expansion fixed**: SQL is streamed to database clients over stdin, so bcrypt/scrypt `$` characters are not expanded by shell.
3. **Wazuh auth fixed**: the manager syncs both Wazuh Dashboard OpenSearch Security and native Wazuh API/RBAC credentials so browser login and API token issuance work.
4. **iTop fixed**: the demo user was rebuilt as a valid `UserLocal` object with initialized local-auth fields and required profiles.
5. **GitLab fixed**: GitLab user updates use the GitLab 17-compatible `User.new` / `save(validate: false)` flow, local Rails password checks pass, missing personal namespaces are repaired, and the GitLab container maps `keycloak.internal` to the Docker host gateway for OIDC.

## Credential Storage Locations

### Where Each Platform Stores Credentials

| Platform | Storage | Format | Container/Path |
|----------|---------|--------|----------------|
| Keycloak | PostgreSQL DB | Encrypted | `keycloak-db-1` |
| iTop | MariaDB `priv_user_local.password_hash` | bcrypt `$2y$12$` | `itop-deployment-db-1` |
| Wazuh API | Wazuh REST API preferred; SQLite fallback | native API / scrypt:N:R:P$salt$hash | `wazuh_deploy-wazuh.manager-1` |
| Wazuh Dashboard | OpenSearch Security | bcrypt `$2y$12$` | `wazuh_deploy-wazuh.indexer-1` -> `/usr/share/wazuh-indexer/config/opensearch-security/internal_users.yml` |
| GitLab | PostgreSQL | Rails encrypted | `gitlab` |
| Mailcow | MySQL | Mailcow `{BLF-CRYPT}` hash for demo UI/IMAP | `mysql-mailcow` |

## Important Notes

- **Wazuh has TWO authentication layers**: OpenSearch Security (dashboard UI login) AND RBAC DB/API access. Verify both before demos because they can drift independently.
- **GitLab supports both local login and Keycloak OIDC**: Keep `keycloak.internal:host-gateway` in the GitLab compose service and install the Keycloak proxy CA into `/etc/gitlab/trusted-certs/` before `gitlab-ctl reconfigure`. If Keycloak mappers change, rerun the GitLab Keycloak setup script so existing mappers are updated in place.
- **Keycloak is internal-only**: No external port mapping. Services reach it via Docker network hostname resolution.
- **iTop uses local auth**: Form login against MariaDB bcrypt hashes. No SSO configured.
- **Mailcow demo UI**: Use `http://192.168.50.222:2581` and login as `demo_account_1` with the vault password for admin UI. Use `/webmail` for the Roundcube mailbox client with identity `demo_account_1@mailcow.local`; the `Report Phish` toolbar button creates Mailcow quarantine evidence and syncs an Agentic Operations ticket/iTop incident.

## Detailed Troubleshooting

For detailed login issue diagnosis and fix steps, see the [login-troubleshooting](../login-troubleshooting/SKILL.md) skill.
