---
name: platform-credentials
description: >
  Multi-platform credential management for IT and SOC services such as iTop, Wazuh, GitLab, Keycloak,
  Mailcow, and SOC Dashboard. Covers encrypted credential-vault usage, user management across
  platforms, credential rotation, and troubleshooting login issues without hardcoded passwords,
  personal account names, fixed private IPs, or machine-specific paths.
allowed-tools:
  - Read
  - Bash(python *)
  - Bash(docker *)
---

# Platform Credentials Management

Use the `credential-vault` skill for all secrets. This skill describes how platform accounts consume those secrets; it does not own vault implementation details.

## Credential Vault

Use the vault CLI from the dedicated skill:

```bash
python "<credential-vault>/scripts/credman.py" setup
python "<credential-vault>/scripts/credman.py" set <key> "<secret>"
python "<credential-vault>/scripts/credman.py" get <key>
python "<credential-vault>/scripts/credman.py" list
```

Runtime scripts should resolve credentials in this order:

1. Explicit environment variable.
2. Secret file path supplied by environment.
3. Credential-vault key.

## Service Coordinates

Do not commit lab-specific private IPs or personal home paths. Use these environment variables in examples and scripts:

| Variable | Purpose |
|----------|---------|
| `SOC_HOST` | Main platform host or load balancer |
| `SOC_DASHBOARD_URL` | Dashboard API/UI base URL |
| `ITOP_URL` | iTop base URL |
| `WAZUH_URL` | Wazuh API base URL |
| `GITLAB_URL` | GitLab base URL |
| `KEYCLOAK_URL` | Keycloak base URL |
| `MAILCOW_URL` | Mailcow base URL |
| `PLATFORM_HOME` | Remote deployment root |
| `CREDMAN_PATH` | Explicit path to `credential-vault/scripts/credman.py` |

## Account Policy

- Use role-oriented account names in docs and scripts, such as `platform_demo_user` or `soc_breakglass_admin`.
- Keep real usernames, passwords, API keys, and PATs in the vault or runtime environment.
- Never commit generated `.env`, `.gitlab-token`, `.api_key`, `.cred_key`, or `.cred_vault.json` files.

## User Manager

The multi-platform user manager must be location-neutral:

```bash
PLATFORM_HOME=/opt/agentic-it \
python scripts/multiplatform_user_manager.py list
```

Supported actions:

- `create`: create a user on selected platforms.
- `delete`: remove a user from selected platforms.
- `update`: modify user attributes.
- `list`: list users across platforms.
- `set-password`: rotate a user password across platforms.

## Platform Backends

- Keycloak: Admin REST API.
- iTop: direct database access only when explicitly configured; use parameterized SQL.
- Wazuh: native Wazuh API preferred; SQLite fallback only for controlled maintenance.
- GitLab: Rails runner or GitLab API with PAT loaded from vault.
- Mailcow: API compatibility shim or direct MySQL when explicitly configured.

## Required Hygiene

- Reference service URLs with environment variables, not fixed private IPs.
- Reference deployment roots with `PLATFORM_HOME`, not a personal home directory.
- Reference secrets with vault keys, not plaintext values.
- Run `python scripts/text_hygiene.py --check-lab-values` before committing platform credential changes.

For detailed login issue diagnosis and fix steps, see the [login-troubleshooting](../login-troubleshooting/SKILL.md) skill.
