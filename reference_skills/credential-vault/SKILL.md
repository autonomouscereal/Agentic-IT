---
name: credential-vault
description: Encrypted credential storage and retrieval for platform secrets. Use when storing, retrieving, listing, rotating, or wiring scripts to consume secrets from the local Fernet vault instead of hardcoded passwords, tokens, API keys, host-specific files, or environment-only fallbacks.
---

# Credential Vault

Use this skill for secret storage and lookup across platform automation. Keep SSH clients, GitLab tools, dashboard demos, and provider adapters as consumers of the vault; do not put vault implementation code inside those tools.

## Layout

- Vault CLI: `scripts/credman.py`
- Shell resolver: `scripts/load_secret.sh`
- Vault files at runtime: `.cred_key` and `.cred_vault.json` next to `scripts/credman.py`

The vault files are runtime state and must not be committed.

## Commands

```bash
python scripts/credman.py setup
python scripts/credman.py set <key> "<secret>"
python scripts/credman.py get <key>
python scripts/credman.py list
python scripts/credman.py rm <key>
```

## Shell Usage

Source `scripts/load_secret.sh` and call `load_secret` with a vault key plus optional environment and file fallbacks.

```bash
. /path/to/credential-vault/scripts/load_secret.sh
TOKEN="$(load_secret gitlab_manager_pat GITLAB_PAT GITLAB_PAT_FILE /run/secrets/gitlab_pat)"
```

Resolution order:

1. Explicit environment variable.
2. Explicit file environment variable.
3. Optional default file path.
4. Encrypted credential vault using `credman.py`.

Set `CREDMAN_PATH` to override the vault CLI path. Set `CREDENTIAL_VAULT_DIR` to point at a skill directory that contains `scripts/credman.py`.

## Naming

Use stable, service-scoped keys:

- `gitlab_manager_pat`
- `gitlab_oidc_setup_pat`
- `itop_web`
- `wazuh_api`
- `mailcow_mysql_root`

Never encode usernames, hostnames, or passwords directly into key names unless they describe the service role rather than a personal account.
