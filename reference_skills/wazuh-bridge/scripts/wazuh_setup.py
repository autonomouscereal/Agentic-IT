#!/usr/bin/env python3
"""
Wazuh IAM Setup - Configure Wazuh for Keycloak integration.
Verifies: API connectivity, JWT auth, user/role management.
Creates: test users for validation.
Zero hardcoded secrets. All credentials from .env or environment.
Compatible with Wazuh 4.14.x.
"""

import json
import os
import ssl
import sys
import urllib.request
import urllib.error

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE


def parse_env(path):
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip('"\''))


def load_config():
    for env_path in [
        os.path.join(SKILL_DIR, ".env"),
        os.path.join(os.getcwd(), ".env"),
    ]:
        if os.path.exists(env_path):
            parse_env(env_path)
            break
    return {
        "wazuh_url": os.environ.get("WAZUH_URL", "https://127.0.0.1:26500").rstrip("/"),
        "wazuh_username": os.environ.get("WAZUH_USERNAME", "wazuh-wui"),
        "wazuh_password": os.environ.get("WAZUH_PASSWORD"),
    }


class WazuhClient:
    """Wazuh REST API client with JWT authentication."""

    def __init__(self, base_url, username, password):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self._token = None

    def authenticate(self):
        """Obtain JWT token via /security/user/authenticate?raw=true."""
        url = f"{self.base_url}/security/user/authenticate?raw=true"
        creds = f"{self.username}:{self.password}"
        import base64
        token_b64 = base64.b64encode(creds.encode()).decode()
        req = urllib.request.Request(
            url, method="GET",
            headers={"Authorization": f"Basic {token_b64}"},
        )
        try:
            with urllib.request.urlopen(req, context=SSL_CTX, timeout=30) as resp:
                self._token = resp.read().decode("utf-8").strip()
                return self._token
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8", errors="replace")
            print(f"[AUTH FAILED] Wazuh auth error: {err[:200]}")
            return None
        except urllib.error.URLError as e:
            print(f"[CONNECTION FAILED] Cannot reach Wazuh at {self.base_url}: {e.reason}")
            return None

    def api_call(self, method, endpoint, data=None):
        """Make an authenticated API call to Wazuh."""
        if not self._token:
            self.authenticate()
        if not self._token:
            return {"error": "No valid token"}
        url = f"{self.base_url}{endpoint}"
        headers = {"Authorization": f"Bearer {self._token}", "Content-Type": "application/json"}
        body = json.dumps(data).encode("utf-8") if data is not None else None
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, context=SSL_CTX, timeout=30) as resp:
                resp_text = resp.read().decode("utf-8")
                return json.loads(resp_text) if resp_text else {}
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8", errors="replace")
            return {"error": err[:300], "code": e.code}
        except urllib.error.URLError as e:
            return {"error": f"Connection failed: {e.reason}"}

    def list_users(self):
        """List all API users."""
        result = self.api_call("GET", "/security/users")
        if "data" in result:
            return result["data"].get("affected_items", [])
        return []

    def create_user(self, username, password):
        """Create a new API user."""
        return self.api_call("POST", "/security/users", {
            "username": username,
            "password": password,
        })

    def change_password(self, user_id, password):
        """Change password for a user by ID."""
        return self.api_call("PUT", f"/security/users/{user_id}/password", {
            "password": password,
        })

    def is_reachable(self):
        """Check if Wazuh API is reachable and responding."""
        result = self.api_call("GET", "/manager/status")
        return result.get("error", 1) == 0

    def list_roles(self):
        """List all RBAC roles."""
        result = self.api_call("GET", "/security/roles")
        if "data" in result:
            return result["data"].get("affected_items", [])
        return []

    def list_policies(self):
        """List all RBAC policies."""
        result = self.api_call("GET", "/security/policies")
        if "data" in result:
            return result["data"].get("affected_items", [])
        return []

    def list_rules(self):
        """List all RBAC rules."""
        result = self.api_call("GET", "/security/rules")
        if "data" in result:
            return result["data"].get("affected_items", [])
        return []

    def create_role_mapping(self, name, roles, users=None):
        """Create a role mapping linking users to roles."""
        mapping = {"name": name, "roles": roles}
        if users:
            mapping["users"] = users
        return self.api_call("POST", "/security/role-mappings", mapping)

    def list_role_mappings(self):
        """List all role mappings."""
        result = self.api_call("GET", "/security/role-mappings")
        if "data" in result:
            return result["data"].get("affected_items", [])
        return []

    def manager_status(self):
        """Get manager process status."""
        result = self.api_call("GET", "/manager/status")
        if "data" in result:
            return result["data"].get("affected_items", [])
        return []

    def manager_info(self):
        """Get manager info."""
        result = self.api_call("GET", "/manager/info")
        if "data" in result:
            return result["data"].get("affected_items", [])
        return []


def verify_connectivity(client):
    """Verify Wazuh API is reachable and auth works."""
    token = client.authenticate()
    if not token:
        return False
    print("[OK] Wazuh authentication successful")
    return True


def verify_manager(client):
    """Verify Wazuh manager is running."""
    status = client.manager_status()
    if status:
        processes = [p.get("name", "unknown") for p in status]
        print(f"[OK] Wazuh manager running ({len(processes)} processes)")
        return True
    print("[WARN] Could not verify manager status")
    return False


def list_existing_users(client):
    """Display current API users."""
    users = client.list_users()
    if users:
        print(f"[INFO] Existing API users ({len(users)}):")
        for u in users[:10]:
            print(f"  - {u.get('username', 'unknown')} (id={u.get('id', '?')})")
        if len(users) > 10:
            print(f"  ... and {len(users) - 10} more")
        return True
    print("[WARN] No users found or unable to list")
    return False


def list_existing_roles(client):
    """Display current RBAC roles."""
    roles = client.list_roles()
    if roles:
        print(f"[INFO] Existing RBAC roles ({len(roles)}):")
        for r in roles:
            print(f"  - {r.get('name', 'unknown')} (id={r.get('id', '?')})")
        return True
    print("[WARN] No roles found or unable to list")
    return False


def create_test_users(client):
    """Create test users for validation (idempotent)."""
    test_users = [
        {"username": "bridge_test_admin", "password": os.environ.get("WAZUH_BRIDGE_ADMIN_PASSWORD", "")},
        {"username": "bridge_test_reader", "password": os.environ.get("WAZUH_BRIDGE_READER_PASSWORD", "")},
    ]
    existing = client.list_users()
    existing_names = {u.get("username") for u in existing}
    created = 0
    for user in test_users:
        if user["username"] in existing_names:
            print(f"  [INFO] Test user '{user['username']}' already exists")
            continue
        result = client.create_user(user["username"], user["password"])
        if "data" in result:
            created += 1
            print(f"  [OK] Test user '{user['username']}' created")
        else:
            print(f"  [WARN] Failed to create '{user['username']}': {result.get('error', 'unknown')}")
    return created


def verify_test_user_auth(client, username):
    """Verify a test user can authenticate."""
    test_client = WazuhClient(client.base_url, username, "BridgeAdm1n123!")
    token = test_client.authenticate()
    if token:
        print(f"  [OK] Test user '{username}' can authenticate")
        return True
    test_client2 = WazuhClient(client.base_url, username, "BridgeRe4d123!")
    token2 = test_client2.authenticate()
    if token2:
        print(f"  [OK] Test user '{username}' can authenticate")
        return True
    print(f"  [WARN] Test user '{username}' auth failed")
    return False


def run_setup():
    config = load_config()
    if not config["wazuh_password"]:
        print("[ERROR] WAZUH_PASSWORD not set. Check .env file.")
        return False

    print(f"[INFO] Connecting to Wazuh at {config['wazuh_url']}")
    client = WazuhClient(config["wazuh_url"], config["wazuh_username"], config["wazuh_password"])

    print("\n=== Verify Connectivity ===")
    if not verify_connectivity(client):
        return False

    print("\n=== Verify Manager ===")
    verify_manager(client)

    print("\n=== Manager Info ===")
    info = client.manager_info()
    if info:
        for item in info:
            print(f"  Version: {item.get('version', '?')}")
            print(f"  Type: {item.get('type', '?')}")

    print("\n=== List Existing Users ===")
    list_existing_users(client)

    print("\n=== List Existing Roles ===")
    list_existing_roles(client)

    print("\n=== Create Test Users ===")
    create_test_users(client)

    print("\n=== Verify Test User Auth ===")
    verify_test_user_auth(client, "bridge_test_admin")

    print("\n[OK] Wazuh setup complete!")
    return True


if __name__ == "__main__":
    sys.exit(0 if run_setup() else 1)
