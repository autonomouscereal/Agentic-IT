#!/usr/bin/env python3
"""Upload SOC testing compose files through server-manager.

Kept for older runbooks that call this helper directly. Authentication is
delegated to ssh_client.py, which resolves credentials from the encrypted vault
or environment at runtime.
"""
import subprocess
import sys
from pathlib import Path


SERVER_MANAGER = Path(__file__).resolve().parent / "ssh_client.py"
LOCAL_BASE = Path("C:/Users/cereal/SOC_TESTING")
REMOTE_BASE = "/home/cereal/SOC_TESTING"
FILES_TO_UPLOAD = [
    ("docker-compose.yml", f"{REMOTE_BASE}/docker/docker-compose.yml"),
    ("zeek-scripts/local.zeek", f"{REMOTE_BASE}/config/zeek/local.zeek"),
    ("suricata.yaml", f"{REMOTE_BASE}/config/suricata/suricata.yaml"),
]


def run(cmd):
    result = subprocess.run(cmd, text=True)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def main():
    if not SERVER_MANAGER.exists():
        raise SystemExit(f"server-manager CLI not found: {SERVER_MANAGER}")

    for local_name, remote_path in FILES_TO_UPLOAD:
        local_path = LOCAL_BASE / local_name
        if not local_path.exists():
            print(f"[WARN] Missing local file: {local_path}")
            continue
        remote_dir = remote_path.rsplit("/", 1)[0]
        run([sys.executable, str(SERVER_MANAGER), "--server", "ai", "--execute", f"mkdir -p {remote_dir}"])
        run([sys.executable, str(SERVER_MANAGER), "--server", "ai", "--upload", str(local_path), remote_path])
        print(f"[OK] Uploaded {local_path} -> {remote_path}")


if __name__ == "__main__":
    main()
