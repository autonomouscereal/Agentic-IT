#!/usr/bin/env python3
"""Helper script to upload bash scripts to the AI server using paramiko."""
import sys
import os

# Add server-manager to path
sys.path.insert(0, "C:/Users/cereal/.claude/skills/server-manager")

# Import paramiko directly to avoid the CLI wrapper
import paramiko

REMOTE_HOST = "192.168.50.222"
REMOTE_USER = "cereal"
REMOTE_PASS = "root"
REMOTE_DIR = "/home/cereal/gitlab-keycloak-integration/scripts/"

LOCAL_DIR = "/c/Users/cereal/.claude/skills/gitlab-keycloak-integration/scripts"

FILES_TO_UPLOAD = [
    "diagnose.sh",
    "test_integration.sh",
    "validate_automation.sh",
    "backup_restore.sh",
]

def main():
    # Connect
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(REMOTE_HOST, username=REMOTE_USER, password=REMOTE_PASS, timeout=30)

    # Ensure remote directory exists
    stdin, stdout, stderr = ssh.exec_command(f"mkdir -p {REMOTE_DIR}")
    stdout.channel.recv_exit_status()

    # Upload each file
    sftp = ssh.open_sftp()
    for fname in FILES_TO_UPLOAD:
        local_path = os.path.join(LOCAL_DIR, fname)
        remote_path = os.path.join(REMOTE_DIR, fname)
        try:
            sftp.put(local_path, remote_path)
            print(f"[OK] Uploaded {fname} ({os.path.getsize(local_path)} bytes)")
        except Exception as e:
            print(f"[FAIL] {fname}: {e}")
    sftp.close()
    ssh.close()

if __name__ == "__main__":
    main()
