#!/usr/bin/env python3
"""Upload docker-compose configuration files to a managed server.

This helper is intentionally generic: host, user, paths, and vault key come
from environment variables instead of baked-in lab values.
"""

import os
import subprocess
import sys
from pathlib import Path

import paramiko


SERVER_CONFIG = {
    "host": os.environ.get("TARGET_HOST", "127.0.0.1"),
    "username": os.environ.get("TARGET_USER", os.environ.get("USER", "operator")),
    "port": int(os.environ.get("TARGET_PORT", "22")),
}


def _get_password():
    """Get password from the credential-vault skill or TARGET_PASSWORD."""
    skill_dir = Path(__file__).resolve().parent
    credman = Path(os.environ.get(
        "CREDMAN_PATH",
        str(skill_dir.parent / "credential-vault" / "scripts" / "credman.py"),
    ))
    vault_key = os.environ.get("TARGET_VAULT_KEY", "ai")
    try:
        result = subprocess.run(
            [sys.executable, str(credman), "get", vault_key],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if result.returncode == 0:
            return result.stdout
    except (OSError, subprocess.SubprocessError):
        pass
    return os.environ.get("TARGET_PASSWORD", "")


def upload_file(ssh_client, local_path, remote_path):
    """Upload a file to the remote server."""
    sftp = ssh_client.open_sftp()
    try:
        sftp.put(local_path, remote_path)
        print(f"Uploaded: {local_path} -> {remote_path}")
        return True
    except Exception as exc:
        print(f"Failed to upload {local_path}: {exc}")
        return False
    finally:
        sftp.close()


def main():
    local_base = Path(os.environ.get("LOCAL_SOC_TESTING_DIR", "."))
    remote_base = os.environ.get("REMOTE_SOC_TESTING_DIR", "/opt/soc-testing")

    files_to_upload = [
        ("docker-compose.yml", f"{remote_base}/docker/docker-compose.yml"),
        ("zeek-scripts/local.zeek", f"{remote_base}/config/zeek/local.zeek"),
        ("suricata.yaml", f"{remote_base}/config/suricata/suricata.yaml"),
    ]

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(
        hostname=SERVER_CONFIG["host"],
        username=SERVER_CONFIG["username"],
        password=_get_password(),
        port=SERVER_CONFIG["port"],
        timeout=30,
    )

    print("Connected to managed server")
    for local_file, remote_path in files_to_upload:
        local_full = local_base / local_file
        if local_full.exists():
            upload_file(ssh, str(local_full), remote_path)
        else:
            print(f"Warning: {local_full} not found")

    ssh.close()
    print("\nUpload complete")


if __name__ == "__main__":
    main()
