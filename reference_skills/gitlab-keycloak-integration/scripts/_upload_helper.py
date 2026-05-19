#!/usr/bin/env python3
"""Upload GitLab/Keycloak helper scripts through server-manager.

This file is kept for older runbooks that referenced `_upload_helper.py`, but
it now delegates to the encrypted-vault server-manager CLI instead of opening a
raw Paramiko session or carrying credentials in source.
"""
import argparse
import subprocess
import sys
from pathlib import Path


DEFAULT_SERVER_MANAGER = Path("C:/Users/me/.agents/skills/server-manager/ssh_client.py")
DEFAULT_REMOTE_DIR = "/opt/agentic-it/gitlab-keycloak-integration/scripts"
FILES_TO_UPLOAD = [
    "diagnose.sh",
    "test_integration.sh",
    "validate_automation.sh",
    "backup_restore.sh",
]


def run(cmd):
    result = subprocess.run(cmd, text=True)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def main():
    parser = argparse.ArgumentParser(description="Upload GitLab/Keycloak helper scripts via server-manager")
    parser.add_argument("--server", default="ai", help="server-manager server key")
    parser.add_argument("--remote-dir", default=DEFAULT_REMOTE_DIR)
    parser.add_argument("--server-manager", default=str(DEFAULT_SERVER_MANAGER))
    parser.add_argument("--local-dir", default=str(Path(__file__).resolve().parent))
    args = parser.parse_args()

    local_dir = Path(args.local_dir).resolve()
    server_manager = Path(args.server_manager).resolve()

    if not server_manager.exists():
        raise SystemExit(f"server-manager CLI not found: {server_manager}")

    run([sys.executable, str(server_manager), "--server", args.server, "--execute", f"mkdir -p {args.remote_dir}"])

    for filename in FILES_TO_UPLOAD:
        local_path = local_dir / filename
        if not local_path.exists():
            raise SystemExit(f"missing helper script: {local_path}")
        remote_path = f"{args.remote_dir.rstrip('/')}/{filename}"
        run([sys.executable, str(server_manager), "--server", args.server, "--upload", str(local_path), remote_path])
        print(f"[OK] Uploaded {filename} ({local_path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
