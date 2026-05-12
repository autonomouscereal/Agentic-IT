---
name: server-manager
description: >-
  Generic SSH client for managed servers. Use when connecting to a server defined
  in servers.json, executing commands, uploading or downloading files, running
  scripts remotely, or validating SSH connectivity. Secrets are resolved from
  the credential-vault skill or environment variables; this skill must not own
  vault files or hardcode personal usernames, fixed private IPs, or lab paths.
allowed-tools:
  - Read
  - Bash(python *)
  - Bash(docker *)
  - Bash(find *)
  - Bash(df *)
---

# Server Manager

Use `ssh_client.py` for SSH operations against servers defined in `servers.json`.
Keep `servers.json` out of committed bundles because it is environment-specific.

## Secret Resolution

Server Manager consumes credentials; it does not implement the vault. Password lookup order:

1. `CREDMAN_PATH` when set.
2. Sibling `../credential-vault/scripts/credman.py` in a bundled install.
3. User skill installs under `~/.claude/skills/credential-vault` or `~/.agents/skills/credential-vault`.
4. Environment variable named by the server config `password_env`.
5. SSH key path from the server config.

Legacy `server-manager/credman.py` may be read only for backward compatibility on existing operator machines. Do not add new vault code to this skill.

## Server Config Shape

```json
{
  "servers": {
    "example": {
      "host": "example.internal",
      "port": 22,
      "user": "operator",
      "password_env": "EXAMPLE_SSH_PASSWORD",
      "ssh_key_path": "~/.ssh/id_ed25519",
      "label": "Example server",
      "base_directory": "/opt/platform"
    }
  },
  "default_server": "example"
}
```

## Common Commands

```bash
python ssh_client.py --list-servers
python ssh_client.py --server example --test
python ssh_client.py --server example --execute "docker compose ps"
python ssh_client.py --server example --script 'cd /opt/platform && docker compose logs --tail=50'
python ssh_client.py --server example --upload "C:/reports/output.csv" "/opt/platform/output.csv"
python ssh_client.py --server example --upload-dir "C:/project/src" "/opt/platform/src"
python ssh_client.py --server example --download "/opt/platform/output.csv" "C:/Users/me/Downloads"
```

Use `--script` or `--command-file` for commands containing quotes, pipes, `$()`, or backticks.

## Guardrails

- Do not commit `servers.json`, private keys, `.cred_key`, `.cred_vault.json`, generated `.env`, or token files.
- Do not commit fixed lab IPs, personal usernames, or personal home paths in this skill.
- Keep remote paths configurable with each server's `base_directory` or command arguments.
- Use the `credential-vault` skill for storing, listing, or rotating secrets.
