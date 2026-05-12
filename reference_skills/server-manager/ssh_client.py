#!/usr/bin/env python3
r"""
Server Manager SSH Client - Secure, agnostic SSH management tool.

Loads server configuration from servers.json (no hardcoded secrets).
Reads passwords from environment variables. Supports SSH key fallback.
Passes commands via file to avoid shell escaping issues.

Usage via CLI:
    # Test connection to a server by name
    python ssh_client.py --server ai --test
    python ssh_client.py --server ai --test

    # Execute a simple command (no special chars)
    python ssh_client.py --server ai --execute "pwd && whoami"

    # Execute complex commands via file (avoids ALL escaping issues)
    # 1. Write your command to a temp file
    echo 'cd /home/cereal && docker compose ps && echo "done"' > /tmp/cmd.txt
    # 2. Pass the file path
    python ssh_client.py --server ai --command-file "/tmp/cmd.txt"

    # Upload a file
    python ssh_client.py --server ai --upload "~/local/file.txt" "/home/cereal/file.txt"

    # Upload directory recursively
    python ssh_client.py --server ai --upload-dir "~/local/dir" "/home/cereal/remote"

    # Download a file
    python ssh_client.py --server ai --download "/home/cereal/file.txt" "~/downloads"

    # List configured servers
    python ssh_client.py --list-servers

    # JSON output for machine parsing
    python ssh_client.py --server ai --execute "pwd" --json

Usage via Python:
    from ssh_client import ServerConfig, SSHClient

    config = ServerConfig.load()
    server = config.get("ai")
    ssh = SSHClient.from_config(server)
    ssh.connect()
    exit_code, output, errors = ssh.execute("pwd")
    ssh.close()
"""

import json
import os
import sys
import subprocess
import argparse
import paramiko
from pathlib import Path
from typing import Tuple, Optional, List, Dict, Any


def _fallback_skill_dir() -> Optional[Path]:
    """Return canonical fallback skill dir when this synced copy lacks state."""
    configured = os.environ.get("SERVER_MANAGER_FALLBACK_DIR", "").strip()
    candidates = []
    if configured:
        candidates.append(Path(configured))
    home = Path(os.environ.get("USERPROFILE") or os.environ.get("HOME") or "")
    if home:
        candidates.append(home / ".claude" / "skills" / "server-manager")
    for candidate in candidates:
        if candidate and candidate.exists():
            return candidate
    return None


# ---------------------------------------------------------------------------
# Path normalization utilities - handle Windows / Git Bash / cygwin chaos
# ---------------------------------------------------------------------------

def normalize_local_path(p: str) -> Path:
    r"""
    Convert any path format to a proper Windows Path object.

    Handles:
      - Git Bash style:  /c/Users/cereal/file.txt  ->  C:/Users/cereal/file.txt
      - cygwin style:    /cygdrive/c/Users/cereal/file.txt
      - Native Windows:  C:/Users/cereal/file.txt
      - Forward slashes: /d/some/path
    """
    if not p:
        return Path(p)

    # cygwin: /cygdrive/c/Users/... -> C:/Users/...
    if p.startswith("/cygdrive/"):
        drive = p[10].upper()
        p = f"{drive}:{p[11:]}"

    # Git Bash WSL-style: /c/... or /C/... -> C:/...
    elif len(p) >= 3 and p[0] == "/" and p[2] == "/":
        drive = p[1].upper()
        p = f"{drive}:/{p[3:]}"

    # Replace forward slashes with OS separator for pathlib compatibility
    p = p.replace("/", os.sep)

    return Path(p)


def normalize_remote_path(p: str) -> str:
    """
    Ensure a remote path is a clean Unix-style path.

    Handles Git Bash path translation where /home/... gets turned into
    C:/Program Files/Git/home/...  - detects and reverses this.
    Always returns forward-slash Unix paths suitable for SSH/SFTP.
    """
    if not p:
        return p

    # Git Bash translates /home to C:/Program Files/Git/home
    # Detect and reverse this mangle
    git_prefix = "C:/Program Files/Git"
    git_prefix_bs = "C:\\Program Files\\Git"

    for prefix in (git_prefix, git_prefix_bs):
        if p.startswith(prefix):
            p = p[len(prefix):]
            break

    # If it somehow still has a Windows drive letter, strip it
    if len(p) >= 3 and p[1] == ":" and p[2] in ("/", "\\"):
        p = p[2:]  # strip drive letter and colon

    # Normalize to forward slashes
    p = p.replace("\\", "/")

    # Ensure leading slash for absolute paths
    if not p.startswith("/"):
        p = "/" + p

    return p


def _try_credman(server_name: str) -> str:
    """Try to get password from the encrypted credential vault.

    Calls credman.py via subprocess.  Returns empty string if vault is
    not set up, key is missing, or no credential exists for this server.
    All silent - no error output on failure (those are expected during
    the resolution cascade).
    """
    try:
        skill_dir = Path(__file__).resolve().parent
        credman_candidates = [skill_dir / "credman.py"]
        fallback = _fallback_skill_dir()
        if fallback and fallback != skill_dir:
            credman_candidates.append(fallback / "credman.py")
        python = sys.executable or "python"
        for credman_path in credman_candidates:
            if not credman_path.exists():
                continue
            result = subprocess.run(
                [python, str(credman_path), "get", server_name],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return result.stdout
    except (subprocess.SubprocessError, OSError):
        pass
    return ""


# ---------------------------------------------------------------------------
# Configuration loader - reads servers.json, never stores secrets
# ---------------------------------------------------------------------------

class ServerConfig:
    """Loads and validates server configuration from a JSON file."""

    def __init__(self, path: str = None):
        self._path = path
        self._servers: Dict[str, Dict[str, Any]] = {}
        self._default: str = "ai"

        if self._path is None:
            # Default: servers.json next to this script
            script_dir = Path(__file__).resolve().parent
            local_config = script_dir / "servers.json"
            fallback = _fallback_skill_dir()
            fallback_config = fallback / "servers.json" if fallback else None
            if local_config.exists() or not fallback_config:
                self._path = str(local_config)
            else:
                self._path = str(fallback_config)

        self._load()

    def _load(self):
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except FileNotFoundError:
            print(f"[FATAL] Config file not found: {self._path}")
            print("  Create a servers.json file - see .env.template for setup.")
            sys.exit(1)
        except json.JSONDecodeError as e:
            print(f"[FATAL] Invalid JSON in {self._path}: {e}")
            sys.exit(1)

        self._servers = data.get("servers", {})
        self._default = data.get("default_server", "ai")

        if not self._servers:
            print("[FATAL] No servers defined in config.")
            sys.exit(1)

    def list_servers(self) -> List[str]:
        return list(self._servers.keys())

    def default_server(self) -> str:
        if self._default in self._servers:
            return self._default
        return next(iter(self._servers), "")

    def get(self, name: str) -> Dict[str, Any]:
        """Get server config by name, resolving secrets securely.

        Resolution order:
          1. Encrypted credential vault (credman.py)
          2. Environment variable (password_env field in config)
          3. SSH key (ssh_key_path field in config)
        """
        if name not in self._servers:
            available = ", ".join(self.list_servers())
            print(f"[FATAL] Unknown server '{name}'. Available: {available}")
            sys.exit(1)

        srv = dict(self._servers[name])
        host = srv.get("host", "")
        port = srv.get("port", 22)
        user = srv.get("user", "")
        label = srv.get("label", name)
        key_path = srv.get("ssh_key_path", "")
        password = None
        password_env_name = srv.get("password_env", "")

        # 1. Try encrypted credential vault
        password = _try_credman(name)
        auth_source = "vault" if password else ""

        # 2. Fall back to environment variable
        if not password and password_env_name and password_env_name in os.environ:
            password = os.environ[password_env_name]
            auth_source = f"${password_env_name}"

        # 3. SSH key fallback
        if not password:
            auth_source = "ssh-key" if key_path else "none"

        return {
            "host": host,
            "port": port,
            "user": user,
            "password": password,
            "auth_source": auth_source,
            "password_env": password_env_name,
            "ssh_key_path": key_path,
            "label": label,
        }


# ---------------------------------------------------------------------------
# SSH client - paramiko-based with robust error handling
# ---------------------------------------------------------------------------

class SSHClient:
    """SSH client with command execution, SFTP upload/download, and key auth."""

    def __init__(self, host: str, port: int = 22, user: str = "",
                 password: str = None, ssh_key_path: str = None,
                 auth_source: str = "unknown"):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.ssh_key_path = ssh_key_path
        self.auth_source = auth_source
        self.ssh = None
        self._is_connected = False

    @staticmethod
    def from_config(cfg: Dict[str, Any]) -> "SSHClient":
        """Factory: create SSHClient from a ServerConfig.get() dict."""
        return SSHClient(
            host=cfg["host"],
            port=cfg["port"],
            user=cfg["user"],
            password=cfg.get("password"),
            ssh_key_path=cfg.get("ssh_key_path", ""),
            auth_source=cfg.get("auth_source", "unknown"),
        )

    # -- connection ---------------------------------------------------------

    def connect(self, timeout: int = 30) -> bool:
        """Establish SSH connection.  Returns True on success."""
        print(f"\n{'='*60}")
        print(f"CONNECTING -> {self.user}@{self.host}:{self.port}")
        print(f"{'='*60}")

        try:
            self.ssh = paramiko.SSHClient()
            self.ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

            kwargs = dict(
                hostname=self.host,
                username=self.user,
                port=self.port,
                timeout=timeout,
                allow_agent=True,
                look_for_keys=False if not self.ssh_key_path else True,
            )

            # Password auth
            if self.password:
                kwargs["password"] = self.password
                src = self.auth_source
                print(f"Auth: password (from {src})")

            # SSH key auth (fallback or primary if no password)
            elif self.ssh_key_path and self.ssh_key_path != "~/.ssh/id_ed25519_server_manager":
                key_path = os.path.expanduser(self.ssh_key_path)
                if os.path.isfile(key_path):
                    kwargs["key_filename"] = key_path
                    print(f"Auth: ssh key ({key_path})")
                else:
                    print(f"[WARN] SSH key not found: {key_path}, trying password-less")
                    del kwargs["look_for_keys"]

            else:
                print("[WARN] No password or SSH key configured - connection will likely fail")

            self.ssh.connect(**kwargs)
            self._is_connected = True
            print(f"[OK] Connected to {self.host}")
            return True

        except paramiko.AuthenticationException as e:
            print(f"[AUTH FAIL] {e}")
            if self.auth_source == "vault":
                print("  -> Run: python credman.py set <server> \"password\"")
            elif self.auth_source.startswith("$"):
                print(f"  -> Set the '{self.auth_source}' environment variable.")
            return False
        except paramiko.SSHException as e:
            print(f"[SSH ERROR] {e}")
            return False
        except Exception as e:
            print(f"[CONNECT ERROR] {e}")
            return False

    # -- command execution --------------------------------------------------

    def execute(self, command: str) -> Tuple[int, str, str]:
        """Run a single command, return (exit_code, stdout, stderr)."""
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")

        cmd_display = command[:100]
        if len(command) > 100:
            cmd_display += "..."

        stdin, stdout, stderr = self.ssh.exec_command(command)
        out_raw = stdout.read()
        err_raw = stderr.read()
        exit_code = stdout.channel.recv_exit_status()

        out = _decode(out_raw)
        err = _decode(err_raw)

        return exit_code, out, err

    def execute_script(self, script: str, shebang: str = "#!/bin/bash") -> Tuple[int, str, str]:
        """
        Execute a multi-line script safely by uploading to a temp file,
        running it, and cleaning up.  Avoids ALL shell escaping issues.
        """
        if not self._connected:
            raise RuntimeError("Not connected. Call connect() first.")

        import tempfile
        import stat

        # Write script to a secure temp file on the remote
        remote_path = f"/tmp/.ssh_client_cmd_{os.getpid()}"

        try:
            # Upload script via SFTP
            script_content = (shebang + "\n" + script).encode("utf-8")
            sftp = self.ssh.open_sftp()

            sftp_file = sftp.open(remote_path, "w")
            sftp_file.write(script_content)
            sftp_file.close()

            # Make executable
            sftp.chmod(remote_path, 0o700)
            sftp.close()

            # Execute
            exit_code, out, err = self.execute(f"bash {remote_path}")

            return exit_code, out, err

        finally:
            # Cleanup remote temp file
            try:
                self.execute(f"rm -f {remote_path}")
            except Exception:
                pass

    # -- SFTP file operations -----------------------------------------------

    def upload_file(self, local_path: str, remote_path: str) -> bool:
        """Upload a single file."""
        if not self._connected:
            raise RuntimeError("Not connected.")

        local = normalize_local_path(local_path)
        remote = normalize_remote_path(remote_path)

        if not local.is_file():
            print(f"[ERROR] Local file not found: {local}")
            return False

        try:
            sftp = self.ssh.open_sftp()

            # Ensure remote parent directory exists
            remote_parent = "/".join(remote.split("/")[:-1])
            if remote_parent:
                self._ensure_remote_dir(remote_parent, sftp)

            sftp.put(str(local), remote)
            sftp.close()
            print(f"[UPLOAD OK] {local} -> {remote}")
            return True
        except Exception as e:
            print(f"[UPLOAD ERROR] {e}")
            return False

    def upload_directory(self, local_dir: str, remote_dir: str,
                         file_filter=None) -> dict:
        """Upload a directory tree. Returns {'success': [...], 'failed': [...]}. """
        if not self._connected:
            raise RuntimeError("Not connected.")

        local = normalize_local_path(local_dir)
        remote = normalize_remote_path(remote_dir)

        if not local.is_dir():
            print(f"[ERROR] Local directory not found: {local}")
            return {"success": [], "failed": [str(local)]}

        results = {"success": [], "failed": []}

        try:
            sftp = self.ssh.open_sftp()

            # Ensure the top-level remote directory exists
            self._ensure_remote_dir(remote, sftp)

            for file_path in local.rglob("*"):
                if not file_path.is_file():
                    continue

                rel = file_path.relative_to(local).as_posix()

                if file_filter and not file_filter(rel):
                    continue

                remote_file = f"{remote}/{rel}"
                remote_parent = "/".join(remote_file.split("/")[:-1])

                try:
                    self._ensure_remote_dir(remote_parent, sftp)
                    sftp.put(str(file_path), remote_file)
                    results["success"].append(rel)
                except Exception as e:
                    print(f"[ERROR] {rel}: {e}")
                    results["failed"].append(rel)

            sftp.close()
            print(f"[UPLOAD DIR] {len(results['success'])} ok, {len(results['failed'])} failed")

        except Exception as e:
            print(f"[UPLOAD DIR ERROR] {e}")

        return results

    def download_file(self, remote_path: str, local_dir: str) -> bool:
        """Download a file to a local directory."""
        if not self._connected:
            raise RuntimeError("Not connected.")

        remote = normalize_remote_path(remote_path)
        local = normalize_local_path(local_dir)

        try:
            os.makedirs(str(local), exist_ok=True)
            filename = remote.rsplit("/", 1)[-1] if "/" in remote else remote
            local_file = local / filename

            sftp = self.ssh.open_sftp()
            sftp.get(remote, str(local_file))
            sftp.close()
            print(f"[DOWNLOAD OK] {remote} -> {local_file}")
            return True
        except Exception as e:
            print(f"[DOWNLOAD ERROR] {e}")
            return False

    # -- helpers ------------------------------------------------------------

    def _ensure_remote_dir(self, remote_dir: str, sftp):
        """Create remote directory recursively via SFTP (no shell needed)."""
        parts = remote_dir.split("/")
        path = ""
        for part in parts:
            if not part:
                continue
            path += "/" + part
            try:
                sftp.stat(path)
            except FileNotFoundError:
                sftp.mkdir(path)

    def close(self):
        """Close the SSH connection."""
        if self.ssh:
            try:
                self.ssh.close()
            except Exception:
                pass
            self.ssh = None
        self._is_connected = False
        print("[INFO] SSH connection closed.")

    @property
    def _connected(self) -> bool:
        return self._is_connected and self.ssh is not None


# ---------------------------------------------------------------------------
# Encoding helper
# ---------------------------------------------------------------------------

def _decode(raw: bytes) -> str:
    """Decode bytes to string with UTF-8 -> latin-1 fallback."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("latin-1", errors="replace")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ssh_client",
        description="Server Manager - SSH client for remote server operations.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List available servers
  python ssh_client.py --list-servers

  # Test connection
  python ssh_client.py --server ai --test

  # Simple command
  python ssh_client.py --server ai --execute "docker compose ps"

  # Complex command via file (no escaping issues!)
  echo 'cd /home/cereal && docker compose logs -n 20 zeek' > /tmp/cmd.txt
  python ssh_client.py --server ai --command-file "/tmp/cmd.txt"

  # Upload file
  python ssh_client.py --server ai --upload "C:/reports/log.txt" "/home/cereal/log.txt"

  # Upload directory
  python ssh_client.py --server ai --upload-dir "C:/project" "/home/cereal/project"

  # Download file
  python ssh_client.py --server ai --download "/home/cereal/output.csv" "C:/Users/cereal/Downloads"

  # JSON output (machine-parseable)
  python ssh_client.py --server ai --execute "pwd" --json
        """,
    )

    # Server selection
    parser.add_argument(
        "--server", "-s",
        type=str,
        default=None,
        help="Server name from servers.json (e.g. ai, staging, prod). Defaults to config default.",
    )

    # List servers
    parser.add_argument(
        "--list-servers",
        action="store_true",
        help="List configured servers and exit.",
    )

    # Actions (mutually exclusive)
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--test", action="store_true", help="Test connection only.")
    group.add_argument(
        "--execute", "-e",
        type=str,
        help="Execute a single shell command.",
    )
    group.add_argument(
        "--command-file", "-f",
        type=str,
        help="Read command(s) from a file and execute. Avoids all shell escaping issues.",
    )
    group.add_argument(
        "--script",
        type=str,
        help="Execute a multi-line bash script string safely via temp file upload.",
    )
    group.add_argument(
        "--upload", "-u",
        nargs=2,
        metavar=("LOCAL", "REMOTE"),
        help="Upload a file.",
    )
    group.add_argument(
        "--upload-dir",
        nargs=2,
        metavar=("LOCAL_DIR", "REMOTE_DIR"),
        help="Upload a directory recursively.",
    )
    group.add_argument(
        "--download", "-d",
        nargs=2,
        metavar=("REMOTE", "LOCAL_DIR"),
        help="Download a file.",
    )

    # Output format
    parser.add_argument(
        "--json", "-j",
        action="store_true",
        help="Output results as JSON instead of formatted text.",
    )

    # Config file override
    parser.add_argument(
        "--config", "-c",
        type=str,
        default=None,
        help="Path to servers.json config file (default: next to this script).",
    )

    # Timeout
    parser.add_argument(
        "--timeout",
        type=int,
        default=30,
        help="Connection timeout in seconds (default: 30).",
    )

    return parser


def main():
    args = build_parser().parse_args()

    # Load config
    config = ServerConfig(path=args.config)

    # Handle --list-servers
    if args.list_servers:
        servers = config.list_servers()
        default = config.default_server()
        if args.json:
            print(json.dumps({"servers": servers, "default": default}))
        else:
            print("Configured servers:")
            for name in servers:
                marker = " (default)" if name == default else ""
                print(f"  - {name}{marker}")
        sys.exit(0)

    # Resolve server name
    server_name = args.server or config.default_server()
    srv_cfg = config.get(server_name)

    # Create and connect
    ssh = SSHClient.from_config(srv_cfg)

    if not ssh.connect(timeout=args.timeout):
        sys.exit(1)

    try:
        result = _run_action(ssh, args)
        _print_result(result, args.json)
    finally:
        ssh.close()


def _run_action(ssh: SSHClient, args) -> dict:
    """Execute the requested action and return a result dict."""
    if args.test:
        code, out, err = ssh.execute("echo 'Connection OK' && hostname && whoami")
        return {"action": "test", "exit_code": code, "stdout": out.strip(), "stderr": err.strip()}

    elif args.execute:
        code, out, err = ssh.execute(args.execute)
        return {"action": "execute", "command": args.execute, "exit_code": code,
                "stdout": out, "stderr": err}

    elif args.command_file:
        cmd_path = normalize_local_path(args.command_file)
        if not cmd_path.is_file():
            return {"action": "command-file", "error": f"Command file not found: {cmd_path}"}
        command = cmd_path.read_text(encoding="utf-8").strip()
        code, out, err = ssh.execute(command)
        return {"action": "command-file", "source": str(cmd_path), "exit_code": code,
                "stdout": out, "stderr": err}

    elif args.script:
        code, out, err = ssh.execute_script(args.script)
        return {"action": "script", "exit_code": code, "stdout": out, "stderr": err}

    elif args.upload:
        local, remote = args.upload
        ok = ssh.upload_file(local, remote)
        return {"action": "upload", "local": local, "remote": remote, "success": ok}

    elif args.upload_dir:
        local, remote = args.upload_dir
        results = ssh.upload_directory(local, remote)
        return {"action": "upload-dir", "local": local, "remote": remote,
                "uploaded": len(results["success"]),
                "failed": len(results["failed"]),
                "files": results["success"], "errors": results["failed"]}

    elif args.download:
        remote, local_dir = args.download
        ok = ssh.download_file(remote, local_dir)
        return {"action": "download", "remote": remote, "local": local_dir, "success": ok}

    return {"action": "none", "error": "No action specified."}


def _print_result(result: dict, as_json: bool):
    """Format and print the action result."""
    if as_json:
        print(json.dumps(result, indent=2))
        return

    # Human-readable output
    if result.get("error"):
        print(f"\n[ERROR] {result['error']}")
        return

    action = result.get("action", "unknown")

    if action == "test":
        status = "PASSED" if result.get("exit_code", 1) == 0 else "FAILED"
        print(f"\n[TEST] Connection {status}")
        if result.get("stdout"):
            print(f"  {result['stdout']}")

    elif action in ("execute", "command-file", "script"):
        code = result.get("exit_code", -1)
        status = "OK" if code == 0 else f"exit code {code}"
        src = ""
        if action == "command-file":
            src = f" (from {result.get('source', '')})"
        print(f"\n[EXECUTE] {status}{src}")
        if result.get("stdout"):
            print(f"\n{result['stdout']}")
        if result.get("stderr"):
            print(f"\n[STDERR]\n{result['stderr']}")

    elif action == "upload":
        if result.get("success"):
            print(f"\n[UPLOAD] Complete.")
        else:
            print(f"\n[UPLOAD] Failed.")

    elif action == "upload-dir":
        print(f"\n[UPLOAD DIR] {result.get('uploaded', 0)} files uploaded, "
              f"{result.get('failed', 0)} failed.")

    elif action == "download":
        if result.get("success"):
            print(f"\n[DOWNLOAD] Complete.")
        else:
            print(f"\n[DOWNLOAD] Failed.")

    if result.get("error") and action not in ("execute", "command-file", "script"):
        print(f"\n[ERROR] {result['error']}")


if __name__ == "__main__":
    main()
