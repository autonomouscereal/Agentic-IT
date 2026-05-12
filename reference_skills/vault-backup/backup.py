#!/usr/bin/env python3
r"""
Vault Backup - versioned backup and restore for credential-vault runtime files.

Creates integrity-verified, date-stamped checkpoints of .cred_key and .cred_vault.json.
Supports listing, restoring, and cleaning up old checkpoints.

Usage:
    python backup.py backup                     # Create versioned backup
    python backup.py list                       # List all checkpoints
    python backup.py verify                     # Verify vault integrity only
    python backup.py restore <checkpoint_name>  # Restore to checkpoint
    python backup.py cleanup --older-than <N>   # Delete checkpoints older than N days
"""

import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

from cryptography.fernet import Fernet

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_SKILL_DIR = Path(__file__).resolve().parent
_VAULT_DIR = _SKILL_DIR.parent / "server-manager"
_KEY_FILE = _VAULT_DIR / ".cred_key"
_VAULT_FILE = _VAULT_DIR / ".cred_vault.json"
_BACKUPS_DIR = _SKILL_DIR / "backups"

# ---------------------------------------------------------------------------
# Integrity verification
# ---------------------------------------------------------------------------

def verify_vault() -> tuple[bool, str]:
    """Attempt to decrypt all credentials. Return (ok, message)."""
    if not _KEY_FILE.exists():
        return False, "No master key found (.cred_key missing)"
    if not _VAULT_FILE.exists():
        return False, "No vault file found (.cred_vault.json missing)"

    try:
        key_bytes = _KEY_FILE.read_bytes()
        fernet = Fernet(key_bytes)
    except Exception as e:
        return False, f"Corrupt key file: {e}"

    try:
        vault = json.loads(_VAULT_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return False, f"Corrupt vault file: {e}"

    if not vault:
        return True, "Vault is empty (no credentials stored)"

    failed = []
    for name, token_b64 in vault.items():
        try:
            import base64
            token = base64.b64decode(token_b64.encode("ascii"))
            fernet.decrypt(token)
        except Exception as e:
            failed.append(f"{name}: {e}")

    if failed:
        return False, f"Decryption failed for {len(failed)}/{len(vault)} credentials:\n" + "\n".join(failed)

    return True, f"All {len(vault)} credentials verified OK"

# ---------------------------------------------------------------------------
# Backup operations
# ---------------------------------------------------------------------------

def create_backup() -> str | None:
    """Create a versioned backup checkpoint. Returns checkpoint name or None."""
    ok, msg = verify_vault()
    print(f"[VERIFY] {msg}")
    if not ok:
        print("[ABORT] Vault integrity check failed. No backup created.")
        return None

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
    checkpoint_dir = _BACKUPS_DIR / timestamp
    checkpoint_dir.mkdir(parents=True, exist_ok=True)

    # Copy vault files
    shutil.copy2(str(_KEY_FILE), str(checkpoint_dir / ".cred_key"))
    shutil.copy2(str(_VAULT_FILE), str(checkpoint_dir / ".cred_vault.json"))

    # Compute integrity hash of vault file
    vault_hash = hashlib.sha256(_VAULT_FILE.read_bytes()).hexdigest()

    # Load vault to count credentials
    vault = json.loads(_VAULT_FILE.read_text(encoding="utf-8"))

    # Write manifest
    manifest = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "checkpoint": timestamp,
        "credential_count": len(vault),
        "vault_hash": vault_hash,
        "verified": True,
    }
    (checkpoint_dir / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    print(f"[OK] Backup created: {timestamp} ({len(vault)} credentials, hash: {vault_hash[:16]}...)")
    return timestamp

# ---------------------------------------------------------------------------
# List checkpoints
# ---------------------------------------------------------------------------

def list_checkpoints():
    """Show all available backup checkpoints."""
    if not _BACKUPS_DIR.exists():
        print("No backups found.")
        return

    checkpoints = sorted(_BACKUPS_DIR.iterdir())
    if not checkpoints:
        print("No backups found.")
        return

    print(f"Available checkpoints ({len(checkpoints)} total):")
    print(f"{'Checkpoint':<22} {'Credentials':<14} {'Vault Hash':<18} {'Time UTC'}")
    print("-" * 80)

    for cp in checkpoints:
        manifest_file = cp / "manifest.json"
        if manifest_file.exists():
            try:
                m = json.loads(manifest_file.read_text(encoding="utf-8"))
                ts = m.get("timestamp", "unknown")
                count = m.get("credential_count", "?")
                h = m.get("vault_hash", "?")[:16] + "..."
                print(f"{cp.name:<22} {count:<14} {h:<18} {ts}")
            except Exception:
                print(f"{cp.name:<22} {'???':<14} {'???':<18} manifest error")
        else:
            print(f"{cp.name:<22} {'???':<14} {'???':<18} no manifest")

# ---------------------------------------------------------------------------
# Restore checkpoint
# ---------------------------------------------------------------------------

def restore_checkpoint(name: str) -> bool:
    """Restore vault files from a checkpoint."""
    checkpoint_dir = _BACKUPS_DIR / name

    if not checkpoint_dir.exists():
        print(f"[ERROR] Checkpoint not found: {name}")
        return False

    key_file = checkpoint_dir / ".cred_key"
    vault_file = checkpoint_dir / ".cred_vault.json"

    if not key_file.exists() or not vault_file.exists():
        print(f"[ERROR] Checkpoint incomplete (missing key or vault file): {name}")
        return False

    # Verify checkpoint integrity before restoring
    try:
        key_bytes = key_file.read_bytes()
        fernet = Fernet(key_bytes)
        vault = json.loads(vault_file.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[ERROR] Checkpoint corrupt: {e}")
        return False

    import base64
    failed = []
    for cred_name, token_b64 in vault.items():
        try:
            token = base64.b64decode(token_b64.encode("ascii"))
            fernet.decrypt(token)
        except Exception:
            failed.append(cred_name)

    if failed:
        print(f"[ERROR] Checkpoint has {len(failed)} broken credentials. Aborting restore.")
        return False

    # Create a backup of current state before restoring (safety net)
    if _KEY_FILE.exists() or _VAULT_FILE.exists():
        safety_backup = _BACKUPS_DIR / f"pre_restore_{name}"
        safety_backup.mkdir(exist_ok=True)
        if _KEY_FILE.exists():
            shutil.copy2(str(_KEY_FILE), str(safety_backup / ".cred_key"))
        if _VAULT_FILE.exists():
            shutil.copy2(str(_VAULT_FILE), str(safety_backup / ".cred_vault.json"))
        (safety_backup / "manifest.json").write_text(
            json.dumps({"auto_backup": True, "restored_to": name}),
            encoding="utf-8",
        )

    # Perform restore
    shutil.copy2(str(key_file), str(_KEY_FILE))
    shutil.copy2(str(vault_file), str(_VAULT_FILE))

    print(f"[OK] Restored vault from checkpoint: {name} ({len(vault)} credentials)")
    return True

# ---------------------------------------------------------------------------
# Cleanup old checkpoints
# ---------------------------------------------------------------------------

def cleanup(older_than_days: int):
    """Delete checkpoints older than N days."""
    if not _BACKUPS_DIR.exists():
        print("No backups to clean up.")
        return

    cutoff = datetime.now(timezone.utc).timestamp() - (older_than_days * 86400)
    deleted = 0

    for cp in _BACKUPS_DIR.iterdir():
        if not cp.is_dir():
            continue
        # Skip safety backups (pre_restore_*)
        if cp.name.startswith("pre_restore_"):
            continue
        mtime = cp.stat().st_mtime
        if mtime < cutoff:
            shutil.rmtree(str(cp))
            deleted += 1
            print(f"[OK] Deleted old checkpoint: {cp.name}")

    print(f"[DONE] Cleanup complete: deleted {deleted} checkpoint(s) older than {older_than_days} days")

# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(prog="vault-backup", description="Versioned vault backup and restore")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("backup", help="Create a versioned backup (verifies integrity first)")
    sub.add_parser("list", help="List all available checkpoints")
    sub.add_parser("verify", help="Verify current vault integrity")

    restore_p = sub.add_parser("restore", help="Restore to a specific checkpoint")
    restore_p.add_argument("checkpoint", help="Checkpoint name (e.g. 2026-05-06_143000)")

    cleanup_p = sub.add_parser("cleanup", help="Delete old checkpoints")
    cleanup_p.add_argument("--older-than", type=int, default=30,
                          help="Delete checkpoints older than N days (default: 30)")

    args = parser.parse_args()

    if args.command == "backup":
        create_backup()
    elif args.command == "list":
        list_checkpoints()
    elif args.command == "verify":
        ok, msg = verify_vault()
        print(f"[{'OK' if ok else 'FAIL'}] {msg}")
        sys.exit(0 if ok else 1)
    elif args.command == "restore":
        ok = restore_checkpoint(args.checkpoint)
        sys.exit(0 if ok else 1)
    elif args.command == "cleanup":
        cleanup(args.older_than)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
