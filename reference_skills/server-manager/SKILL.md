---
name: server-manager
description: >-
  Secure SSH client for remote server management. Encrypted credential vault,
  agnostic server config, robust path handling. Supports command execution,
  script deployment, and SFTP file/directory upload and download.
when_to_use: >-
  Use when connecting to remote servers via SSH, executing commands, uploading
  or downloading files, running scripts on remote hosts, or managing server
  infrastructure. Trigger on asks to SSH into a managed server, AI server, or any
  server defined in servers.json.
allowed-tools:
  - Read
  - Bash(python *)
  - Bash(ssh *)
  - Bash(find *)
  - Bash(rm *)
  - Bash(mkdir *)
  - Bash(cat *)
  - Bash(df *)
  - Bash(docker *)
  - Bash(tree *)
---

# Server Manager

Encrypted, agnostic SSH management tool. Zero hardcoded secrets. Zero escaping issues. Works with any server defined in config.

## Architecture

| Component | File | Purpose |
|---|---|---|
| SSH Client | `ssh_client.py` | Paramiko-based SSH with command execution, SFTP, script deployment |
| Credential Vault | `credman.py` | Fernet-encrypted password storage - decrypts at runtime only |
| Server Config | `servers.json` | Defines servers by name. References secrets by env-var name, never stores them |
| Encryption Key | `.cred_key` | Master encryption key (600 permissions, owner-only) |
| Credential Store | `.cred_vault.json` | Encrypted tokens (base64 Fernet ciphertext, not plaintext) |

**Secrets flow:** `servers.json` (no secrets) -> `credman.py` decrypts from `.cred_vault.json` -> password lives in memory only -> SSH connects.

**Command flow (no escaping issues):** Script writes command to file -> `--command-file` or `--script` reads it -> passes to remote bash via SFTP upload + execution. Bash shell never parses the command string.

## Stable Credential Access After Skill Sync

For the Windows lab, the stable credential command is:

```powershell
python "C:\Users\me\.agents\skills\server-manager\credman.py" get <vault-key>
```

Use this for application credentials such as `demo_account_1` and
`keycloak_admin`. The command prints the secret because that is its purpose, so
do not paste the value into docs, source, logs, or chat transcripts.

The skill sync installer preserves local-only excluded files in this directory:

- `.cred_key`
- `.cred_vault.json`
- `servers.json`

Those files are deliberately not committed to the portable `reference_skills`
bundle. If a legacy sync ever removes them, restore them from
`C:\Users\me\.claude\skills\server-manager` or the `vault-backup` skill
checkpoints before running credential commands again.

---

## First-Time Setup (any environment)

Run these steps **once** when planted in a new environment. Set `SERVER_MANAGER_SKILL_DIR` to this skill directory, for example `C:/Users/me/.agents/skills/server-manager`.

### Step 1: Initialize the encrypted credential vault

```bash
python "${SERVER_MANAGER_SKILL_DIR}/credman.py" setup
```

This generates `.cred_key` (master encryption key) with restricted permissions.

### Step 2: Store server passwords (one-time, encrypted at rest)

```bash
python "${SERVER_MANAGER_SKILL_DIR}/credman.py" set <server-name> "<password>"
```

For example, with a configured AI server:
```bash
python "${SERVER_MANAGER_SKILL_DIR}/credman.py" set ai "<from secure handoff>"
```

**After this, passwords NEVER appear in bash again.** They are encrypted in `.cred_vault.json` and only decrypted in-memory when needed.

### Step 3: Verify connection

```bash
python "${SERVER_MANAGER_SKILL_DIR}/ssh_client.py" --server ai --test
```

Expected output: `Auth: password (from vault)` followed by `[OK] Connected`.

---

## Adding a New Server

Edit `servers.json` to add a new server entry, then store its password:

```json
{
    "servers": {
        "my-new-server": {
            "host": "10.0.0.50",
            "port": 22,
            "user": "admin",
            "password_env": "MY_NEW_SERVER_PASSWORD",
            "ssh_key_path": "~/.ssh/id_ed25519",
            "label": "My New Server",
            "base_directory": "/home/admin"
        }
    },
    "default_server": "ai"
}
```

Then store the password:
```bash
python "${SERVER_MANAGER_SKILL_DIR}/credman.py" set my-new-server "the-password"
```

That's it. Use `--server my-new-server` from then on.

---

## CLI Reference

### Server selection

| Flag | Description |
|---|---|
| `--server <name>` / `-s <name>` | Server key from `servers.json` (e.g. `ai`, `staging`, `prod`). Defaults to `default_server` in config. |
| `--list-servers` | Show all configured server names. |

### Actions (mutually exclusive)

| Flag | Description | Best for |
|---|---|---|
| `--test` | Test connection only | Verifying auth/network |
| `--execute "cmd"` / `-e "cmd"` | Run a single command | Simple commands with NO special characters (no `$`, no nested quotes, no backticks) |
| `--command-file "/path/to/file"` / `-f` | Read command from a local file | Commands with quotes, `$()`, backticks - anything bash would mangle |
| `--script "multiline bash"` | Execute via temp-file upload | Complex scripts with loops, conditionals, pipes, subshells |
| `--upload "LOCAL" "REMOTE"` / `-u` | Upload a single file | One-off file transfer |
| `--upload-dir "LOCAL_DIR" "REMOTE_DIR"` | Upload directory tree recursively | Deploying multiple files |
| `--download "REMOTE" "LOCAL_DIR"` / `-d` | Download a file to local directory | Retrieving remote files |

### Options

| Flag | Description |
|---|---|
| `--json` / `-j` | Output results as JSON (machine-parseable) |
| `--config "/path/to/servers.json"` / `-c` | Override config file path |
| `--timeout <seconds>` | Connection timeout (default: 30) |

---

## Usage Patterns

### Pattern 1: Simple command (no special characters)

```bash
python "${SERVER_MANAGER_SKILL_DIR}/ssh_client.py" --server ai --execute "docker compose ps"
```

### Pattern 2: Complex command via file (avoids ALL escaping)

When the command contains `$()`, quotes, backticks, pipes, or any bash special characters:

```bash
# Step 1: Write command to a file
python -c "
with open('/tmp/my_cmd.txt', 'w') as f:
    f.write('cd /opt/agentic-it && docker compose logs -n 20 zeek | grep ERROR')
"

# Step 2: Execute via command-file
python "${SERVER_MANAGER_SKILL_DIR}/ssh_client.py" --server ai --command-file "/tmp/my_cmd.txt"
```

### Pattern 3: Multi-line scripts (most robust for complex work)

```bash
python "${SERVER_MANAGER_SKILL_DIR}/ssh_client.py" --server ai --script '
echo "=== Status ==="
echo "Hostname: $(hostname)"
echo "User: $(whoami)"
docker compose ps 2>/dev/null || echo "no docker"
df -h / | tail -1
echo "=== Done ==="
'
```

The `--script` flag uploads the script to a secure temp file on the remote server, executes it with `bash`, and cleans up. **No escaping issues whatsoever.**

### Pattern 4: File and directory transfer

```bash
# Upload a single file
python "${SERVER_MANAGER_SKILL_DIR}/ssh_client.py" --server ai --upload "C:/reports/output.csv" "/opt/agentic-it/output.csv"

# Upload a directory tree (handles nested directories)
python "${SERVER_MANAGER_SKILL_DIR}/ssh_client.py" --server ai --upload-dir "C:/project/src" "/opt/agentic-it/project/src"

# Download a file
python "${SERVER_MANAGER_SKILL_DIR}/ssh_client.py" --server ai --download "/opt/agentic-it/logs/app.log" "C:/Users/me/Downloads"
```

### Pattern 5: JSON output for programmatic consumption

```bash
python "${SERVER_MANAGER_SKILL_DIR}/ssh_client.py" --server ai --execute "hostname" --json
```

---

## Path Handling

The script normalizes paths automatically. You can use any of these formats for **local paths**:

| Format | Example | Works? |
|---|---|---|
| Windows native | `C:/Users/me/file.txt` | Yes |
| Git Bash | `/c/Users/cereal/file.txt` | Yes |
| cygwin | `/cygdrive/c/Users/cereal/file.txt` | Yes |
| Tilde | `~/file.txt` | Yes |

**Remote paths** are always Unix-style (`/home/user/path`). The script detects and reverses Git Bash path translation.

---

## Security Model

1. **`servers.json`** - Contains hostnames, ports, usernames. **NO passwords. NO secrets.**
2. **`.cred_vault.json`** - Contains Fernet-encrypted tokens. Cannot be decrypted without `.cred_key`.
3. **`.cred_key`** - Master encryption key stored with `0600` permissions. Never transmitted over network.
4. **`ssh_client.py`** - Calls `credman.py` via subprocess to decrypt password in-memory only.

### Auth resolution order

For each server: encrypted vault -> environment variable -> SSH key.

### Credential management

```bash
python "${SERVER_MANAGER_SKILL_DIR}/credman.py" list      # Show stored server names
python "${SERVER_MANAGER_SKILL_DIR}/credman.py" set ai "new-password"
python "${SERVER_MANAGER_SKILL_DIR}/credman.py" rm ai
python "${SERVER_MANAGER_SKILL_DIR}/credman.py" clear     # Remove all
```

---

## Programmatic API

```python
import sys
sys.path.insert(0, "${SERVER_MANAGER_SKILL_DIR}")

from ssh_client import ServerConfig, SSHClient

config = ServerConfig()
server_cfg = config.get("ai")
ssh = SSHClient.from_config(server_cfg)

if ssh.connect():
    code, stdout, stderr = ssh.execute("hostname")
    code, out, err = ssh.execute_script("echo 'User: $(whoami)'")
    ssh.upload_file("C:/local/file.txt", "/opt/agentic-it/file.txt")
    results = ssh.upload_directory("C:/local/dir", "/opt/agentic-it/dir")
    ssh.download_file("/opt/agentic-it/output.csv", "C:/Users/me/Downloads")
    ssh.close()
```

---

## Troubleshooting

| Symptom | Cause | Fix |
|---|---|---|
| `[AUTH FAIL]` after `from vault` | Wrong password stored | `python credman.py set <server> "correct-password"` |
| `[FATAL] Config file not found` | Missing `servers.json` | Check path or use `--config` flag |
| `[FATAL] Unknown server 'x'` | Not in config | Run `--list-servers` to see names |
| `[ERROR] No master key found` | Vault not initialized | `python credman.py setup` |
| `[UPLOAD ERROR] Local file not found` | Bad local path | Use `C:/path` or `/c/path` format |
| Commands fail with `unexpected EOF` | Complex quoting in `--execute` | Use `--script` or `--command-file` instead |
| `No module named 'cryptography'` | Missing dependency | `pip install cryptography paramiko` |

---

## Migration from v1

1. Run `python credman.py setup` to create the encryption key.
2. Run `python credman.py set ai "<pw>"` for each configured server key.
3. Replace `--server ai` flag with `--server ai`.
4. For complex commands, use `--script` or `--command-file` instead of `--execute`.

---

## Release Notes

### v2.1 - End-to-End Testing & Bug Fixes

**Bugs fixed:**
- `_ensure_remote_dir()` had a `break` after creating the first parent directory, causing `--upload-dir` to fail on nested paths (e.g., `a/b/c/deep.txt`). Removed the `break` - recursive directory creation now works for arbitrary depth.
- `normalize_local_path()` dropped the separator between drive letter and path when converting Git Bash paths (`/c/Users/...` became `C:Users/...`). Fixed to produce `C:/Users/...`.
- `_print_result()` had no early check for error dicts from `--command-file`, causing confusing `[EXECUTE] exit code -1` output. Added error-first display.

**Verified:** 29/29 end-to-end tests pass across both servers covering path normalization, config loading, vault auth, command execution, script deployment, file upload/download, nested directory uploads, error handling, and JSON output.
