#!/usr/bin/env python3
"""
Multi-Platform User Manager
===========================
Manage users across Keycloak, iTop, Wazuh, GitLab, and Mailcow from a single CLI.

Usage:
    python3 multiplatform_user_manager.py create <username> <password> [--platforms all|keycloak,itop,wazuh,gitlab,mailcow] [--role administrator] [--email user@domain]
    python3 multiplatform_user_manager.py delete <username> [--platforms all]
    python3 multiplatform_user_manager.py update <username> --new-password <password> [--platforms all]
    python3 multiplatform_user_manager.py list [--platform all|keycloak,itop,wazuh,gitlab,mailcow]
    python3 multiplatform_user_manager.py status

Examples:
    python3 multiplatform_user_manager.py create demo_account_1 "<from vault: demo_account_1>" --platforms all --role administrator
    python3 multiplatform_user_manager.py delete demo_account_1 --platforms keycloak,itop
    python3 multiplatform_user_manager.py update demo_account_1 --new-password "NewPass123!" --platforms wazuh,gitlab
    python3 multiplatform_user_manager.py list --platform all
    python3 multiplatform_user_manager.py status
"""

import argparse
import base64
import hashlib
import json
import os
import secrets
import sqlite3
import subprocess
import sys
import tempfile
import ssl
import urllib.error
import urllib.parse
import urllib.request

# ============================================================================
# Configuration
# ============================================================================

def load_env_file(path):
    """Load key=value pairs from a .env file."""
    config = {}
    if not os.path.exists(path):
        return config
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#'):
                continue
            if '=' in line:
                key, _, value = line.partition('=')
                config[key.strip()] = value.strip()
    return config

# Keycloak
KC_ENV = load_env_file("/home/cereal/keycloak-manager/.env")
KEYCLOAK_ADMIN_PASSWORD = KC_ENV.get("KC_BOOTSTRAP_ADMIN_PASSWORD", "")
KEYCLOAK_REALMS = ["itop", "wazuh", "mailcow", "gitlab"]
KC_ADMIN_SCRIPT = "/home/cereal/keycloak-manager/scripts/keycloak_admin.py"

# ============================================================================
# Helpers
# ============================================================================

def run_cmd(args, timeout=60, input_text=None):
    """Run a local command without a shell so secrets and hashes are not expanded."""
    r = subprocess.run(
        args,
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout,
        shell=False,
    )
    return r.returncode, r.stdout.strip(), r.stderr.strip()

def run_remote(cmd, container=None, timeout=60):
    """Run a shell command for legacy read-only/simple operations."""
    if container:
        full_cmd = ["docker", "exec", container, "sh", "-lc", cmd]
    else:
        full_cmd = ["bash", "-lc", cmd]
    return run_cmd(full_cmd, timeout=timeout)

def docker_exec(container, args, timeout=60, input_text=None):
    """Execute a command inside a container without shell interpretation."""
    docker_args = ["docker", "exec"]
    if input_text is not None:
        docker_args.append("-i")
    docker_args.extend([container, *args])
    return run_cmd(docker_args, timeout=timeout, input_text=input_text)

def get_container_env(container, key):
    """Resolve a single environment variable from a Docker container."""
    code, out, _ = run_cmd(
        ["docker", "inspect", "-f", "{{range .Config.Env}}{{println .}}{{end}}", container],
        timeout=30,
    )
    if code != 0:
        return ""
    prefix = f"{key}="
    for line in out.splitlines():
        if line.startswith(prefix):
            return line[len(prefix):]
    return ""

def sql_literal(value):
    """Escape a value for SQL literals used in non-shell SQL streams."""
    return "'" + str(value).replace("\\", "\\\\").replace("'", "''") + "'"

def run_mysql_stream(container, client, user, password, database, sql, timeout=60):
    """Run SQL by streaming stdin into mysql/mariadb; avoids shell expansion of bcrypt/scrypt hashes."""
    if not password:
        return 1, "", "Database password is not configured"
    args = [client, f"-u{user}", f"-p{password}", database, "--batch", "--raw"]
    return docker_exec(container, args, input_text=sql, timeout=timeout)

def _docker_cp_in(container, host_path, container_path):
    """Copy a file from host into a Docker container."""
    return run_cmd(["docker", "cp", host_path, f"{container}:{container_path}"], timeout=30)

def _docker_cp_out(container, container_path, host_path):
    """Copy a file from a Docker container to the host."""
    return run_cmd(["docker", "cp", f"{container}:{container_path}", host_path], timeout=30)

def run_py_in_container(container, py_code, timeout=60):
    """Write Python code to a temp file on host, docker cp into container, execute, cleanup."""
    script_path = f"/tmp/_ump_script_{secrets.token_hex(4)}.py"
    try:
        with open(script_path, "w") as f:
            f.write(py_code)
        _docker_cp_in(container, script_path, script_path)
        code, out, err = docker_exec(container, ["python3", script_path], timeout=timeout)
        docker_exec(container, ["rm", "-f", script_path], timeout=30)
        return code, out, err
    finally:
        try:
            os.remove(script_path)
        except OSError:
            pass

def print_ok(msg):
    print(f"[OK] {msg}")

def print_err(msg):
    print(f"[ERROR] {msg}", file=sys.stderr)

def print_info(msg):
    print(f"[INFO] {msg}")


# iTop
ITOP_DB_CONTAINER = os.environ.get("ITOP_DB_CONTAINER", "itop-deployment-db-1")
ITOP_DB_USER = os.environ.get("ITOP_DB_USER") or get_container_env(ITOP_DB_CONTAINER, "MYSQL_USER") or "itop"
ITOP_DB_PASSWORD = os.environ.get("ITOP_DB_PASSWORD") or get_container_env(ITOP_DB_CONTAINER, "MYSQL_PASSWORD")
ITOP_DB_NAME = os.environ.get("ITOP_DB_NAME") or get_container_env(ITOP_DB_CONTAINER, "MYSQL_DATABASE") or "itop"

# Wazuh
WAZUH_RBAC_DB = os.environ.get("WAZUH_RBAC_DB", "/var/ossec/api/configuration/security/rbac.db")
WAZUH_MANAGER_CONTAINER = os.environ.get("WAZUH_MANAGER_CONTAINER", "wazuh_deploy-wazuh.manager-1")
WAZUH_INDEXER_CONTAINER = os.environ.get("WAZUH_INDEXER_CONTAINER", "wazuh_deploy-wazuh.indexer-1")
WAZUH_API_URL = os.environ.get("WAZUH_API_URL", "https://127.0.0.1:26500")
WAZUH_API_USER = os.environ.get("WAZUH_API_USER") or get_container_env(WAZUH_MANAGER_CONTAINER, "API_USERNAME") or "wazuh-wui"
WAZUH_API_PASSWORD = os.environ.get("WAZUH_API_PASSWORD") or get_container_env(WAZUH_MANAGER_CONTAINER, "API_PASSWORD")
WAZUH_INTERNAL_USERS = os.environ.get(
    "WAZUH_INTERNAL_USERS",
    "/usr/share/wazuh-indexer/config/opensearch-security/internal_users.yml",
)
WAZUH_SECURITY_CONFIG_DIR = os.environ.get(
    "WAZUH_SECURITY_CONFIG_DIR",
    "/usr/share/wazuh-indexer/config/opensearch-security/",
)

# GitLab
GITLAB_CONTAINER = os.environ.get("GITLAB_CONTAINER", "gitlab")

# Mailcow
MAILCOW_DB_CONTAINER = os.environ.get("MAILCOW_DB_CONTAINER", "mysql-mailcow")
MAILCOW_DB_USER = os.environ.get("MAILCOW_DB_USER") or "root"
_MAILCOW_ENV_KEY = "MYSQL_ROOT_PASSWORD" if MAILCOW_DB_USER == "root" else "MYSQL_PASSWORD"
MAILCOW_DB_PASSWORD = os.environ.get("MAILCOW_DB_PASSWORD") or get_container_env(MAILCOW_DB_CONTAINER, _MAILCOW_ENV_KEY)
MAILCOW_DB_NAME = os.environ.get("MAILCOW_DB_NAME") or get_container_env(MAILCOW_DB_CONTAINER, "MYSQL_DATABASE") or "mailcow"


# ============================================================================
# Keycloak Backend
# ============================================================================

class KeycloakBackend:
    NAME = "keycloak"

    def create_user(self, username, password, email="", role="administrator"):
        if not KEYCLOAK_ADMIN_PASSWORD:
            return print_err("Keycloak: admin password not configured")
        ok = True
        for realm in KEYCLOAK_REALMS:
            code, out, err = run_cmd([
                "python3", KC_ADMIN_SCRIPT, "-r", realm, "create-user", username,
                "--email", email, "--first-name", "SOC", "--last-name", "Demo",
                "--password", password,
            ])
            if "created" in out.lower():
                print_ok(f"Keycloak/{realm}: Created {username}")
            elif code == 0:
                run_cmd(["python3", KC_ADMIN_SCRIPT, "-r", realm, "set-password", "--", username, password])
                print_ok(f"Keycloak/{realm}: Updated password for {username}")
            else:
                print_err(f"Keycloak/{realm}: {err[:200]}")
                ok = False
        return ok

    def delete_user(self, username):
        for realm in KEYCLOAK_REALMS:
            code, out, err = run_cmd(["python3", KC_ADMIN_SCRIPT, "-r", realm, "delete-user", username])
            if code == 0:
                print_ok(f"Keycloak/{realm}: Deleted {username}")
            else:
                print_err(f"Keycloak/{realm}: {err[:200]}")
        return True

    def update_password(self, username, new_password):
        for realm in KEYCLOAK_REALMS:
            code, out, err = run_cmd(["python3", KC_ADMIN_SCRIPT, "-r", realm, "set-password", "--", username, new_password])
            if code == 0:
                print_ok(f"Keycloak/{realm}: Updated password for {username}")
            else:
                print_err(f"Keycloak/{realm}: {err[:200]}")
        return True

    def list_users(self):
        print("--- Keycloak Users ---")
        for realm in KEYCLOAK_REALMS:
            code, out, err = run_cmd(["python3", KC_ADMIN_SCRIPT, "-r", realm, "list-users"])
            if code == 0:
                try:
                    users = json.loads(out)
                    names = [u["username"] for u in users]
                    print(f"  Realm '{realm}': {names}")
                except:
                    print(f"  Realm '{realm}': {out[:100]}")


# ============================================================================
# iTop Backend
# ============================================================================

class iTopBackend:
    NAME = "itop"

    def _run_sql(self, sql):
        """Run SQL against iTop MariaDB."""
        # Pass SQL directly — callers construct the SQL strings
        return run_mysql_stream(
            ITOP_DB_CONTAINER, "mariadb", ITOP_DB_USER, ITOP_DB_PASSWORD, ITOP_DB_NAME, sql
        )

    def create_user(self, username, password, email="", role="Administrator"):
        username_sql = sql_literal(username)
        # Check if exists
        code, out, err = self._run_sql(
            f"SELECT login FROM priv_user WHERE login={username_sql};"
        )
        if code == 0 and username in out:
            print_info(f"iTop: User {username} already exists, updating password")
            return self.update_password(username, password)

        # Get max ID
        code, out, err = self._run_sql("SELECT COALESCE(MAX(id), 0) FROM priv_user_local;")
        try:
            lines = out.strip().split("\n")
            # MariaDB output includes header row; value is in last line
            max_id = int(lines[-1].strip())
        except:
            max_id = 0
        new_id = max_id + 1

        # Generate bcrypt hash
        try:
            import bcrypt
            pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
            if pw_hash.startswith("$2b$"):
                pw_hash = "$2y$" + pw_hash[len("$2b$"):]
        except ImportError:
            pw_hash = f"$2y$10${secrets.token_hex(22)}"

        pw_safe = sql_literal(pw_hash)

        # Insert priv_user_local
        self._run_sql(
            f"INSERT INTO priv_user_local (id, password_hash, password_salt, expiration, password_renewed_date) "
            f"VALUES ({new_id}, {pw_safe}, '', 'never_expire', CURRENT_DATE());"
        )

        # Insert priv_user
        self._run_sql(
            f"INSERT INTO priv_user (id, login, language, status, finalclass, contactid, log, log_index) "
            f"VALUES ({new_id}, {username_sql}, 'EN US', 'enabled', 'UserLocal', 0, '', 'a:0:{{}}');"
        )

        # Assign Administrator and REST Services profiles.
        self._run_sql(
            f"INSERT INTO priv_urp_userprofile (userid, profileid, description) "
            f"VALUES ({new_id}, 1, 'Demo admin account'), ({new_id}, 1024, 'REST API access');"
        )

        print_ok(f"iTop: Created {username} (ID={new_id}) with Administrator profile")
        return True

    def delete_user(self, username):
        username_sql = sql_literal(username)
        self._run_sql(
            f"DELETE FROM priv_urp_userprofile WHERE userid IN "
            f"(SELECT id FROM priv_user WHERE login={username_sql});"
        )
        self._run_sql(
            f"DELETE FROM priv_user_local WHERE id IN "
            f"(SELECT id FROM priv_user WHERE login={username_sql});"
        )
        self._run_sql(f"DELETE FROM priv_user WHERE login={username_sql};")
        print_ok(f"iTop: Deleted {username}")
        return True

    def update_password(self, username, new_password):
        try:
            import bcrypt
            pw_hash = bcrypt.hashpw(new_password.encode(), bcrypt.gensalt()).decode()
            if pw_hash.startswith("$2b$"):
                pw_hash = "$2y$" + pw_hash[len("$2b$"):]
        except ImportError:
            pw_hash = f"$2y$10${secrets.token_hex(22)}"

        pw_safe = sql_literal(pw_hash)
        username_sql = sql_literal(username)
        self._run_sql(
            f"UPDATE priv_user SET finalclass='UserLocal', status='enabled', "
            f"log='', log_index='a:0:{{}}' "
            f"WHERE login={username_sql};"
        )
        self._run_sql(
            f"UPDATE priv_user_local SET password_hash={pw_safe}, password_salt='', "
            f"password_renewed_date=CURRENT_DATE() "
            f"WHERE id IN (SELECT id FROM priv_user WHERE login={username_sql});"
        )
        print_ok(f"iTop: Updated password for {username}")
        return True

    def list_users(self):
        print("--- iTop Users ---")
        code, out, err = self._run_sql(
            "SELECT pu.login, pu.status, pp.name as profile "
            "FROM priv_user pu "
            "JOIN priv_user_local pul ON pul.id = pu.id "
            "JOIN priv_urp_userprofile purp ON purp.userid = pu.id "
            "JOIN priv_urp_profiles pp ON pp.id = purp.profileid;"
        )
        if code == 0:
            for line in out.strip().split("\n"):
                print(f"  {line}")


# ============================================================================
# Wazuh Backend
# ============================================================================

class WazuhBackend:
    NAME = "wazuh"

    def _api_request(self, method, path, token=None, basic=None, data=None, timeout=15):
        """Call the Wazuh API using stdlib urllib so no extra dependencies are required."""
        body = None
        headers = {}
        if data is not None:
            body = json.dumps(data).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(WAZUH_API_URL.rstrip("/") + path, data=body, method=method, headers=headers)
        if token:
            req.add_header("Authorization", "Bearer " + token)
        if basic:
            token_bytes = base64.b64encode(basic.encode("utf-8")).decode("ascii")
            req.add_header("Authorization", "Basic " + token_bytes)
        ctx = ssl._create_unverified_context()
        with urllib.request.urlopen(req, context=ctx, timeout=timeout) as response:
            return response.status, response.read().decode("utf-8", "ignore")

    def _api_token(self):
        if not WAZUH_API_PASSWORD:
            return ""
        try:
            _, token = self._api_request(
                "GET",
                "/security/user/authenticate?raw=true",
                basic=f"{WAZUH_API_USER}:{WAZUH_API_PASSWORD}",
            )
            return token.strip()
        except Exception as e:
            print_info(f"Wazuh API: native auth unavailable, falling back to RBAC DB ({type(e).__name__})")
            return ""

    def _sync_api_user(self, username, password):
        """Create/update a Wazuh API user through the official API when available."""
        token = self._api_token()
        if not token:
            return False
        try:
            _, users_body = self._api_request("GET", "/security/users?limit=500", token=token)
            users = json.loads(users_body).get("data", {}).get("affected_items", [])
            user_id = next((u.get("id") for u in users if u.get("username") == username), None)
            if user_id is None:
                _, body = self._api_request(
                    "POST", "/security/users", token=token, data={"username": username, "password": password}
                )
                created = json.loads(body).get("data", {}).get("affected_items", [])
                user_id = created[0].get("id") if created else None
                print_ok(f"Wazuh API: Created {username} (ID={user_id})")
            else:
                self._api_request("PUT", f"/security/users/{user_id}", token=token, data={"password": password})
                print_ok(f"Wazuh API: Updated password for {username}")
            if user_id is not None:
                try:
                    self._api_request("POST", f"/security/users/{user_id}/roles?role_ids=1", token=token)
                except urllib.error.HTTPError as e:
                    if e.code not in (400, 409):
                        raise
                self._api_request("PUT", f"/security/users/{user_id}/run_as?allow_run_as=true", token=token)
            return True
        except Exception as e:
            print_info(f"Wazuh API: native user sync failed, falling back to RBAC DB ({type(e).__name__}: {str(e)[:120]})")
            return False

    def _exec_wazuh_py(self, py_code, args=(), timeout=30):
        """Execute Python code inside Wazuh manager container via docker cp."""
        script_path = f"/tmp/_wazuh_{secrets.token_hex(4)}.py"
        try:
            with open(script_path, "w") as f:
                f.write(py_code)
            _docker_cp_in(WAZUH_MANAGER_CONTAINER, script_path, script_path)
            code, out, err = docker_exec(
                WAZUH_MANAGER_CONTAINER, ["python3", script_path, *[str(a) for a in args]], timeout=timeout
            )
            docker_exec(WAZUH_MANAGER_CONTAINER, ["rm", "-f", script_path], timeout=30)
            return code, out, err
        finally:
            try:
                os.remove(script_path)
            except OSError:
                pass

    def _run_sql(self, sql):
        """Run SQL against Wazuh RBAC SQLite database inside container."""
        py_code = '''
import sqlite3, sys
db = sqlite3.connect(sys.argv[1])
c = db.cursor()
c.execute(sys.argv[2])
for r in c.fetchall():
    print(r)
db.commit()
db.close()
'''
        return self._exec_wazuh_py(py_code, args=[WAZUH_RBAC_DB, sql])

    @staticmethod
    def _generate_scrypt_hash(password):
        """Generate Wazuh-compatible scrypt hash on the HOST (Python 3.12, maxmem supported)."""
        salt = secrets.token_bytes(8)
        dk = hashlib.scrypt(
            password.encode(), salt=salt, n=32768, r=8, p=1, dklen=64, maxmem=67108864
        )
        return f"scrypt:32768:8:1${salt.hex()}${dk.hex()}"

    @staticmethod
    def _generate_dashboard_bcrypt(password):
        """Generate an OpenSearch Security bcrypt hash for Wazuh Dashboard login."""
        try:
            import bcrypt
        except ImportError:
            return ""
        digest = bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()
        if digest.startswith("$2b$"):
            digest = "$2y$" + digest[len("$2b$"):]
        return digest

    def _sync_dashboard_user(self, username, password):
        """Create/update the Wazuh Dashboard internal user and reload OpenSearch Security config."""
        pw_hash = self._generate_dashboard_bcrypt(password)
        if not pw_hash:
            print_err("Wazuh Dashboard: bcrypt module missing; cannot generate internal user hash")
            return False

        tmp_in = f"/tmp/internal_users_{secrets.token_hex(4)}.yml"
        tmp_out = f"/tmp/internal_users_{secrets.token_hex(4)}.yml"
        try:
            code, out, err = _docker_cp_out(WAZUH_INDEXER_CONTAINER, WAZUH_INTERNAL_USERS, tmp_in)
            if code != 0:
                print_err(f"Wazuh Dashboard: Could not read internal_users.yml: {err[:200]}")
                return False

            with open(tmp_in, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()

            block = [
                f"{username}:",
                f"  hash: \"{pw_hash}\"",
                "  reserved: false",
                "  backend_roles:",
                "  - \"admin\"",
                "  description: \"SOC demo account managed by multiplatform_user_manager\"",
            ]

            start = None
            for i, line in enumerate(lines):
                if line == f"{username}:":
                    start = i
                    break

            if start is None:
                if lines and lines[-1].strip():
                    lines.append("")
                lines.extend(block)
            else:
                end = start + 1
                while end < len(lines):
                    line = lines[end]
                    if line and not line.startswith(" ") and not line.startswith("\t") and not line.startswith("#"):
                        break
                    end += 1
                lines = lines[:start] + block + lines[end:]

            with open(tmp_out, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")

            container_tmp = f"/tmp/internal_users_{secrets.token_hex(4)}.yml"
            code, out, err = _docker_cp_in(WAZUH_INDEXER_CONTAINER, tmp_out, container_tmp)
            if code != 0:
                print_err(f"Wazuh Dashboard: Could not stage internal_users.yml: {err[:200]}")
                return False
            write_cmd = (
                f"cat {container_tmp} > {WAZUH_INTERNAL_USERS} && "
                f"chown wazuh-indexer:wazuh-indexer {WAZUH_INTERNAL_USERS} && "
                f"chmod 0640 {WAZUH_INTERNAL_USERS} && rm -f {container_tmp}"
            )
            code, out, err = docker_exec(WAZUH_INDEXER_CONTAINER, ["sh", "-lc", write_cmd], timeout=30)
            if code != 0:
                print_err(f"Wazuh Dashboard: Could not write internal_users.yml: {err[:200]}")
                return False

            reload_cmd = (
                "printf '#!/bin/sh\ncommand -v \"$1\"\n' > /tmp/which && "
                "chmod +x /tmp/which && "
                "PATH=/tmp:$PATH OPENSEARCH_JAVA_HOME=/usr/share/wazuh-indexer/jdk "
                "/usr/share/wazuh-indexer/plugins/opensearch-security/tools/securityadmin.sh "
                f"-cd {WAZUH_SECURITY_CONFIG_DIR} "
                "-icl "
                "-key /usr/share/wazuh-indexer/config/certs/admin-key.pem "
                "-cert /usr/share/wazuh-indexer/config/certs/admin.pem "
                "-cacert /usr/share/wazuh-indexer/config/certs/root-ca.pem "
                "-nhnv; status=$?; rm -f /tmp/which; exit $status"
            )
            code, out, err = docker_exec(WAZUH_INDEXER_CONTAINER, ["sh", "-lc", reload_cmd], timeout=120)
            if code == 0:
                print_ok(f"Wazuh Dashboard: Synced internal user {username}")
                return True
            print_err(f"Wazuh Dashboard: securityadmin failed: {(err or out)[:300]}")
            return False
        finally:
            for path in (tmp_in, tmp_out):
                try:
                    os.remove(path)
                except OSError:
                    pass

    def create_user(self, username, password, email="", role="administrator"):
        if self._sync_api_user(username, password):
            self._sync_dashboard_user(username, password)
            return True

        # Check if exists
        code, out, err = self._run_sql(
            f"SELECT id, username FROM users WHERE username={sql_literal(username)}"
        )
        if code == 0 and username in out:
            print_info(f"Wazuh: User {username} already exists, updating password")
            return self.update_password(username, password)

        # Generate hash on host (container OpenSSL blocks n=32768)
        pw_hash = self._generate_scrypt_hash(password)

        # Insert user and role via parameterized SQL
        py_code = '''
import sqlite3, sys
db_path, username, pw_hash = sys.argv[1], sys.argv[2], sys.argv[3]
db = sqlite3.connect(db_path)
c = db.cursor()
c.execute(
    "INSERT INTO users (username, password, allow_run_as, created_at) VALUES (?, ?, 1, datetime('now'))",
    (username, pw_hash)
)
user_id = c.lastrowid
c.execute(
    "INSERT INTO user_roles (user_id, role_id, level, created_at) VALUES (?, 1, 1, datetime('now'))",
    (user_id,)
)
db.commit()
db.close()
print(f"CREATED:{user_id}")
'''
        code, out, err = self._exec_wazuh_py(py_code, args=[WAZUH_RBAC_DB, username, pw_hash], timeout=30)
        if code == 0 and "CREATED" in out:
            uid = out.split("CREATED:")[1].strip()
            print_ok(f"Wazuh: Created {username} (ID={uid}) with administrator role")
        else:
            print_err(f"Wazuh: {err[:300]}")
        self._sync_dashboard_user(username, password)
        return True

    def delete_user(self, username):
        username_sql = sql_literal(username)
        self._run_sql(
            f"DELETE FROM user_roles WHERE user_id IN "
            f"(SELECT id FROM users WHERE username={username_sql})"
        )
        self._run_sql(f"DELETE FROM users WHERE username={username_sql}")
        print_ok(f"Wazuh: Deleted {username}")
        return True

    def update_password(self, username, new_password):
        if self._sync_api_user(username, new_password):
            self._sync_dashboard_user(username, new_password)
            return True

        # Generate hash on host (container OpenSSL blocks n=32768)
        pw_hash = self._generate_scrypt_hash(new_password)

        py_code = '''
import sqlite3, sys
db_path, username, pw_hash = sys.argv[1], sys.argv[2], sys.argv[3]
db = sqlite3.connect(db_path)
c = db.cursor()
c.execute("UPDATE users SET password=?, allow_run_as=1 WHERE username=?", (pw_hash, username))
db.commit()
db.close()
print(f"UPDATED:{c.rowcount}")
'''
        code, out, err = self._exec_wazuh_py(py_code, args=[WAZUH_RBAC_DB, username, pw_hash], timeout=30)
        if code == 0 and "UPDATED" in out:
            count = out.split("UPDATED:")[1].strip()
            if count != "0":
                print_ok(f"Wazuh: Updated password for {username}")
                self._sync_dashboard_user(username, new_password)
            else:
                print_err(f"Wazuh: User {username} not found")
        else:
            print_err(f"Wazuh: {err[:300]}")
        return True

    def list_users(self):
        print("--- Wazuh Users ---")
        code, out, err = self._run_sql(
            "SELECT u.username, r.name as role, u.allow_run_as "
            "FROM users u "
            "LEFT JOIN user_roles ur ON ur.user_id = u.id "
            "LEFT JOIN roles r ON r.id = ur.role_id"
        )
        if code == 0:
            for line in out.strip().split("\n"):
                print(f"  {line}")


# ============================================================================
# GitLab Backend
# ============================================================================

class GitLabBackend:
    NAME = "gitlab"

    def _run_rails(self, rails_code, timeout=120):
        """Run Rails console command inside GitLab container via docker cp."""
        script_path = f"/tmp/_gitlab_rails_{secrets.token_hex(4)}.rb"
        try:
            with open(script_path, "w") as f:
                f.write(rails_code)
            _docker_cp_in(GITLAB_CONTAINER, script_path, script_path)
            code, out, err = run_remote(f"gitlab-rails runner {script_path}", container=GITLAB_CONTAINER, timeout=timeout)
            run_remote(f"rm -f {script_path}", container=GITLAB_CONTAINER)
            return code, out, err
        finally:
            try:
                os.remove(script_path)
            except OSError:
                pass

    def _build_rails(self, template, **kwargs):
        """Build Ruby code from template, safely replacing placeholders."""
        result = template
        for k, v in kwargs.items():
            result = result.replace("{{" + k + "}}", str(v))
        return result

    def create_user(self, username, password, email="", role="admin"):
        if not email:
            email = f"{username}@soc.local"

        template = """
begin
  user = User.find_by(username: '{{username}}')
  if user
    puts "EXISTS:#{user.id}"
  else
    user = User.new(
      email: '{{email}}',
      password: '{{password}}',
      password_confirmation: '{{password}}',
      username: '{{username}}',
      name: 'SOC {{username}}'
    )
    if user.save(validate: false)
      user.confirm
      puts "CREATED:#{user.id}"
    else
      puts "SAVE_FAILED:#{user.errors.full_messages.join(',')}"
    end
  end
rescue => e
  puts "ERROR:#{e.class}:#{e.message}"
end
"""
        rails_code = self._build_rails(template, username=username, email=email, password=password)
        code, out, err = self._run_rails(rails_code)
        if code == 0:
            if "CREATED" in out:
                uid = out.split("CREATED:")[1].strip() if "CREATED:" in out else "?"
                print_ok(f"GitLab: Created {username} (ID: {uid})")
                # Make admin
                admin_template = """
begin
  u = User.find_by(username: '{{username}}')
  if u; u.admin = true; u.save(validate: false); puts 'ADMIN_SET'; else puts 'NOT_FOUND'; end
rescue => e
  puts "ERROR:#{e.message}"
end
"""
                self._run_rails(self._build_rails(admin_template, username=username))
                print_ok(f"GitLab: Made {username} an administrator")
            elif "EXISTS" in out:
                print_info(f"GitLab: User {username} already exists")
            elif "ERROR" in out or "SAVE_FAILED" in out:
                print_err(f"GitLab: {out[:300]}")
        else:
            print_err(f"GitLab: {err[:300]}")
        return True

    def delete_user(self, username):
        template = """
begin
  u = User.find_by(username: '{{username}}')
  if u; u.deactivate; puts 'DEACTIVATED:#{u.id}'; else puts 'NOT_FOUND'; end
rescue => e
  puts "ERROR:#{e.message}"
end
"""
        self._run_rails(self._build_rails(template, username=username))
        print_ok(f"GitLab: Deactivated {username}")
        return True

    def update_password(self, username, new_password):
        template = """
begin
  u = User.find_by(username: '{{username}}')
  if u; u.password = '{{password}}'; u.password_confirmation = '{{password}}'; u.save(validate: false); puts 'PASSWORD_UPDATED'; else puts 'NOT_FOUND'; end
rescue => e
  puts "ERROR:#{e.message}"
end
"""
        self._run_rails(self._build_rails(template, username=username, password=new_password))
        print_ok(f"GitLab: Updated password for {username}")
        return True

    def list_users(self):
        print("--- GitLab Users ---")
        code, out, err = self._run_rails(
            "User.all.each do |u|\n"
            "  role = u.admin ? 'admin' : 'user'\n"
            "  puts \"  #{u.username} (#{u.email}) - #{role}\"\n"
            "end"
        )
        if code == 0:
            print(out)


# ============================================================================
# Mailcow Backend
# ============================================================================

class MailcowBackend:
    NAME = "mailcow"

    def _run_sql(self, sql):
        """Run SQL against Mailcow MySQL."""
        return run_mysql_stream(
            MAILCOW_DB_CONTAINER, "mysql", MAILCOW_DB_USER, MAILCOW_DB_PASSWORD, MAILCOW_DB_NAME, sql
        )

    def create_user(self, username, password, email="", role="administrator"):
        # Try running the bridge sync first
        bridge_script = "/home/cereal/keycloak-mailcow-bridge/scripts/sync_engine.py"
        code, out, err = run_remote(f"python3 {bridge_script}")
        if code == 0:
            print_ok(f"Mailcow: Bridge sync completed")

        # Verify mailbox exists
        check_email = email or f"{username}@soc.local"
        code, out, err = self._run_sql(
            f"SELECT username, active FROM mailbox WHERE username={sql_literal(check_email)};"
        )
        if code == 0 and check_email in out:
            print_ok(f"Mailcow: Mailbox {check_email} exists and active")
        else:
            print_info(f"Mailcow: Mailbox {check_email} not found (bridge may need manual sync)")
        return True

    def delete_user(self, username):
        print_info(f"Mailcow: Delete delegated to bridge sync (remove from Keycloak first)")
        return True

    def update_password(self, username, new_password):
        print_info(f"Mailcow: Password delegated to bridge sync (update in Keycloak first)")
        return True

    def list_users(self):
        print("--- Mailcow Mailboxes ---")
        code, out, err = self._run_sql("SELECT username, active FROM mailbox LIMIT 20;")
        if code == 0:
            for line in out.strip().split("\n"):
                print(f"  {line}")


# ============================================================================
# CLI
# ============================================================================

BACKENDS = {
    "keycloak": KeycloakBackend(),
    "itop": iTopBackend(),
    "wazuh": WazuhBackend(),
    "gitlab": GitLabBackend(),
    "mailcow": MailcowBackend(),
}

def parse_platforms(s):
    if s == "all":
        return list(BACKENDS.keys())
    return [p.strip() for p in s.split(",")]

def main():
    parser = argparse.ArgumentParser(
        description="Multi-Platform User Manager — manage users across Keycloak, iTop, Wazuh, GitLab, Mailcow",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(cmd)s create demo_user "P@ss123!" --platforms all --role administrator
  %(cmd)s delete demo_user --platforms keycloak,itop
  %(cmd)s update demo_user --new-password "NewPass!" --platforms gitlab,wazuh
  %(cmd)s list --platform all
  %(cmd)s status
        """ % {"cmd": sys.argv[0]}
    )

    sub = parser.add_subparsers(dest="command")

    p_create = sub.add_parser("create", help="Create user")
    p_create.add_argument("username")
    p_create.add_argument("password")
    p_create.add_argument("--platforms", default="all")
    p_create.add_argument("--role", default="administrator")
    p_create.add_argument("--email", default="")

    p_delete = sub.add_parser("delete", help="Delete user")
    p_delete.add_argument("username")
    p_delete.add_argument("--platforms", default="all")

    p_update = sub.add_parser("update", help="Update password")
    p_update.add_argument("username")
    p_update.add_argument("--new-password", required=True)
    p_update.add_argument("--platforms", default="all")

    p_list = sub.add_parser("list", help="List users")
    p_list.add_argument("--platform", default="all")

    sub.add_parser("status", help="Check platform status")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    if args.command == "create":
        platforms = parse_platforms(args.platforms)
        print(f"=== Creating '{args.username}' on: {platforms} ===")
        for p in platforms:
            b = BACKENDS.get(p)
            if b:
                print(f"\n--- {p.upper()} ---")
                b.create_user(args.username, args.password, email=args.email, role=args.role)

    elif args.command == "delete":
        platforms = parse_platforms(args.platforms)
        print(f"=== Deleting '{args.username}' from: {platforms} ===")
        for p in platforms:
            b = BACKENDS.get(p)
            if b:
                print(f"\n--- {p.upper()} ---")
                b.delete_user(args.username)

    elif args.command == "update":
        platforms = parse_platforms(args.platforms)
        print(f"=== Updating '{args.username}' on: {platforms} ===")
        for p in platforms:
            b = BACKENDS.get(p)
            if b:
                print(f"\n--- {p.upper()} ---")
                b.update_password(args.username, args.new_password)

    elif args.command == "list":
        if args.platform == "all":
            for b in BACKENDS.values():
                b.list_users()
        else:
            b = BACKENDS.get(args.platform)
            if b:
                b.list_users()

    elif args.command == "status":
        print("=== Platform Status ===")
        print(f"  Keycloak: {'Configured' if KEYCLOAK_ADMIN_PASSWORD else 'MISSING'}")
        print(f"  iTop: {ITOP_DB_CONTAINER}")
        print(f"  Wazuh: {WAZUH_MANAGER_CONTAINER}")
        print(f"  GitLab: {GITLAB_CONTAINER}")
        print(f"  Mailcow: {MAILCOW_DB_CONTAINER}")

if __name__ == "__main__":
    main()
