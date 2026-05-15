#!/usr/bin/env python3
"""Compatibility wrapper for the canonical server-manager credential vault.

Older skills referenced credential-vault/scripts/credman.py directly. Keep
that path working, but route all operations to the single server-manager vault
so deployments do not accidentally create a second secret store.
"""

from pathlib import Path
import runpy
import sys


def main():
    skill_dir = Path(__file__).resolve().parents[2]
    target = skill_dir.parent / "server-manager" / "credman.py"
    if not target.exists():
        print(f"[ERROR] Canonical credman.py not found: {target}", file=sys.stderr)
        raise SystemExit(1)
    sys.argv[0] = str(target)
    runpy.run_path(str(target), run_name="__main__")


if __name__ == "__main__":
    main()
