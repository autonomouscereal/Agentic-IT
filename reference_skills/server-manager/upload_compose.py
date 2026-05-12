#!/usr/bin/env python3
r"""
Script to upload docker-compose configuration files to AI Server.
Uses the encrypted credential vault (credman.py) for auth.
"""

import paramiko
import subprocess
import sys
from pathlib import Path

# Server config (no secrets — password resolved from vault at runtime)
AI_SERVER_CONFIG = {
    'host': '192.168.50.222',
    'username': 'cereal',
    'port': 22,
}

def _get_password():
    """Get password from encrypted credential vault."""
    credman = Path(__file__).resolve().parent / "credman.py"
    try:
        result = subprocess.run(
            [sys.executable, str(credman), "get", "ai"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return result.stdout
    except Exception:
        pass
    # Fallback: env var
    import os
    return os.environ.get("SERVER_AI_PASSWORD", "")

def upload_file(ssh_client, local_path, remote_path):
    """Upload a file to the remote server."""
    sftp = ssh_client.open_sftp()
    try:
        sftp.put(local_path, remote_path)
        print(f"Uploaded: {local_path} -> {remote_path}")
        return True
    except Exception as e:
        print(f"Failed to upload {local_path}: {e}")
        return False
    finally:
        sftp.close()

def main():
    local_base = Path("C:/Users/cereal/SOC_TESTING")
    remote_base = "/home/cereal/SOC_TESTING"

    files_to_upload = [
        ("docker-compose.yml", f"{remote_base}/docker/docker-compose.yml"),
        ("zeek-scripts/local.zeek", f"{remote_base}/config/zeek/local.zeek"),
        ("suricata.yaml", f"{remote_base}/config/suricata/suricata.yaml"),
    ]

    # Connect to AI Server
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    pw = _get_password()
    ssh.connect(
        hostname=AI_SERVER_CONFIG['host'],
        username=AI_SERVER_CONFIG['username'],
        password=pw,
        port=AI_SERVER_CONFIG['port'],
        timeout=30
    )

    print("Connected to AI Server")

    # Upload each file
    for local_file, remote_path in files_to_upload:
        local_full = local_base / local_file
        if local_full.exists():
            upload_file(ssh, str(local_full), remote_path)
        else:
            print(f"Warning: {local_full} not found")

    ssh.close()
    print("\nUpload complete!")

if __name__ == '__main__':
    main()
