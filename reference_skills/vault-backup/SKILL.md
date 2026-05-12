---
name: vault-backup
description: >-
  Versioned backup and restore for the credential-vault (.cred_vault.json and .cred_key).
  Verifies vault integrity before backing up, creates date-stamped checkpoints, and supports
  restoring to any previous checkpoint. Use before major vault changes or periodically.
when_to_use: >-
  Before adding/removing many vault credentials, after bulk vault operations, periodic backup,
  or when the user asks to backup/restore the credential vault.
allowed-tools:
  - Read
  - Bash(python *)
  - Bash(mkdir *)
  - Bash(cp *)
  - Bash(find *)
---

# Vault Backup Skill

Versioned backup system for the credential-vault. Creates integrity-verified, date-stamped checkpoints that can be restored independently.

## Usage

```bash
# Create a versioned backup (verifies integrity first)
python "C:/Users/me/.Codex/skills/vault-backup/backup.py" backup

# List all available checkpoints
python "C:/Users/me/.Codex/skills/vault-backup/backup.py" list

# Verify current vault integrity (no backup)
python "C:/Users/me/.Codex/skills/vault-backup/backup.py" verify

# Restore to a specific checkpoint by date
python "C:/Users/me/.Codex/skills/vault-backup/backup.py" restore 2026-05-06_143000

# Delete old checkpoints older than N days
python "C:/Users/me/.Codex/skills/vault-backup/backup.py" cleanup --older-than 30
```

## How It Works

1. **Integrity Check** - Attempts to decrypt ALL stored credentials. If any decryption fails, the backup is aborted (no corrupted backups).
2. **Checkpoint Creation** - Copies `.cred_key` and `.cred_vault.json` to `vault-backup/backups/YYYY-MM-DD_HHMMSS/`.
3. **Manifest** - Each checkpoint includes a `manifest.json` with timestamp, credential count, and integrity hash.
4. **Restore** - Replaces current vault files with the checkpoint copy.

## Backup Storage

All backups stored at: `C:/Users/me/.Codex/skills/vault-backup/backups/`
