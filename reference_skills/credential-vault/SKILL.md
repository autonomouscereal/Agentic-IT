---
name: credential-vault
description: Encrypted credential storage and retrieval for platform secrets. Use when storing, retrieving, listing, rotating, or wiring scripts to consume secrets from the local Fernet vault instead of hardcoded passwords, tokens, API keys, host-specific files, or environment-only fallbacks.
---

# Credential Vault

Use this skill for shared secret lookup across platform automation. SSH clients,
GitLab tools, dashboard demos, provider adapters, and bridge scripts should
consume the vault through this resolver instead of copying credential logic or
putting secrets in source.

## Layout

- Vault CLI: prefer `server-manager/credman.py`
- Shell resolver: `scripts/load_secret.sh`
- Runtime vault files: `.cred_key` and `.cred_vault.json`

Vault files are runtime state and must never be committed.

## Commands

```bash
python "C:/Users/cereal/.agents/skills/server-manager/credman.py" setup
python "C:/Users/cereal/.agents/skills/server-manager/credman.py" set <key> "<secret>"
python "C:/Users/cereal/.agents/skills/server-manager/credman.py" get <key>
python "C:/Users/cereal/.agents/skills/server-manager/credman.py" list
python "C:/Users/cereal/.agents/skills/server-manager/credman.py" rm <key>
```

## Shell Usage

Source `scripts/load_secret.sh` and call `load_secret` with a vault key plus
optional environment and file fallbacks.

```bash
. /path/to/credential-vault/scripts/load_secret.sh
TOKEN="$(load_secret gitlab_manager_pat GITLAB_PAT GITLAB_PAT_FILE /run/secrets/gitlab_pat)"
```

Resolution order:

1. Explicit environment variable.
2. Explicit file environment variable.
3. Optional default file path.
4. Encrypted credential vault through `credman.py`.

Set `CREDMAN_PATH` to override the vault CLI path. Set
`CREDENTIAL_VAULT_DIR` to point at a skill directory that contains
`scripts/load_secret.sh`.

## Naming

Use stable, service-scoped keys:

- `gitlab_manager_pat`
- `gitlab_oidc_setup_pat`
- `itop_web`
- `wazuh_api`
- `mailcow_mysql_root`

Never encode usernames, hostnames, or passwords directly into key names unless
they describe the service role rather than a personal account.
