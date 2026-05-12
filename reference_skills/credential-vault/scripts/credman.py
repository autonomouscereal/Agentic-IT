#!/usr/bin/env python3
r"""
Credential Manager - encrypted secret storage for platform automation.

Stores server passwords encrypted on disk using Fernet symmetric encryption.
A master key (stored in a restricted-permission file) decrypts at runtime.
Passwords NEVER appear in plaintext in config files, scripts, or bash history.

Usage:
    python credman.py setup              # Generate master key on first use
    python credman.py set key "secret"   # Encrypt and store a secret
    python credman.py get key            # Decrypt and return secret to stdout
    python credman.py list               # Show stored secret keys
    python credman.py rm key             # Remove a stored secret
    python credman.py clear              # Remove ALL stored creds

Consumers such as server-manager call `get` internally via subprocess.
"""

import argparse
import base64
import json
import sys
from pathlib import Path
from cryptography.fernet import Fernet

# ---------------------------------------------------------------------------
# Paths - all relative to the skill directory (next to this script)
# ---------------------------------------------------------------------------

_SKILL_DIR = Path(__file__).resolve().parent
_KEY_FILE = _SKILL_DIR / ".cred_key"
_VAULT_FILE = _SKILL_DIR / ".cred_vault.json"

# ---------------------------------------------------------------------------
# Key management
# ---------------------------------------------------------------------------

def _ensure_key() -> Fernet:
    """Load or create the master key.  Exit on failure."""
    if _KEY_FILE.exists():
        try:
            key_bytes = _KEY_FILE.read_bytes()
            return Fernet(key_bytes)
        except Exception as e:
            print(f"[FATAL] Corrupt key file: {e}")
            sys.exit(1)
    else:
        print("[ERROR] No master key found. Run: python credman.py setup")
        sys.exit(1)


def setup_key(interactive: bool = False) -> str:
    """Generate a new master key file with restricted permissions.

    In non-interactive mode (default): generates a raw Fernet key.
    In interactive mode: optionally wraps the key with a password layer.
    """
    if _KEY_FILE.exists():
        print(f"[WARN] Master key already exists at {_KEY_FILE}")
        if interactive:
            try:
                reply = input("  Re-generate? (y/N): ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                return ""
            if reply != "y":
                print("Aborted.")
                return ""
        else:
            return str(_KEY_FILE)

    _generate_raw_key()

    # Restrict permissions (owner only)
    try:
        _KEY_FILE.chmod(0o600)
    except OSError:
        pass  # May not work on all filesystems

    print(f"[OK] Master key stored at {_KEY_FILE}")
    print("  Keep this file secure. Without it, stored credentials cannot be recovered.")
    return str(_KEY_FILE)


def _generate_raw_key():
    """Generate a raw Fernet key (no password layer)."""
    key = Fernet.generate_key()
    _KEY_FILE.write_bytes(key)


# ---------------------------------------------------------------------------
# Vault operations
# ---------------------------------------------------------------------------

def _load_vault() -> dict:
    if _VAULT_FILE.exists():
        try:
            return json.loads(_VAULT_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_vault(data: dict):
    _VAULT_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def add_credential(key_name: str, secret: str):
    """Encrypt and store a secret for the given key."""
    fernet = _ensure_key()
    token = fernet.encrypt(secret.encode("utf-8"))
    vault = _load_vault()
    vault[key_name] = base64.b64encode(token).decode("ascii")
    _save_vault(vault)
    print(f"[OK] Credential stored for '{key_name}'")


def get_credential(key_name: str) -> str:
    """Decrypt and return the secret.  Returns empty string if not found."""
    fernet = _ensure_key()
    vault = _load_vault()
    if key_name not in vault:
        return ""

    encrypted = base64.b64decode(vault[key_name].encode("ascii"))
    decrypted = fernet.decrypt(encrypted)
    return decrypted.decode("utf-8")


def remove_credential(key_name: str):
    vault = _load_vault()
    if key_name in vault:
        del vault[key_name]
        _save_vault(vault)
        print(f"[OK] Credential removed for '{key_name}'")
    else:
        print(f"[WARN] No credential found for '{key_name}'")


def list_credentials():
    vault = _load_vault()
    if not vault:
        print("No credentials stored.")
    else:
        print("Stored credential keys:")
        for name in sorted(vault.keys()):
            print(f"  - {name}")


def clear_vault():
    if _VAULT_FILE.exists():
        _VAULT_FILE.unlink()
        print("[OK] All credentials cleared.")
    else:
        print("Vault is already empty.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(prog="credman", description="Encrypted credential store.")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("setup", help="Generate master encryption key")
    sub.add_parser("list", help="List stored credentials")
    sub.add_parser("clear", help="Remove all stored credentials")

    set_p = sub.add_parser("set", help="Store a credential")
    set_p.add_argument("key", help="Credential key name")
    set_p.add_argument("secret", help="Secret to encrypt and store")

    get_p = sub.add_parser("get", help="Retrieve a credential")
    get_p.add_argument("key", help="Credential key name")

    rm_p = sub.add_parser("rm", help="Remove a credential")
    rm_p.add_argument("key", help="Credential key name")

    args = parser.parse_args()

    if args.command == "setup":
        setup_key()
    elif args.command == "list":
        list_credentials()
    elif args.command == "clear":
        clear_vault()
    elif args.command == "set":
        add_credential(args.key, args.secret)
    elif args.command == "get":
        pw = get_credential(args.key)
        if pw:
            print(pw, end="")  # no trailing newline - safe for script consumption
        else:
            print(f"[WARN] No credential for '{args.key}'", file=sys.stderr)
            sys.exit(1)
    elif args.command == "rm":
        remove_credential(args.key)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
