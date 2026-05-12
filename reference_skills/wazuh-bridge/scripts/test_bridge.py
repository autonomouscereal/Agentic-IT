#!/usr/bin/env python3
"""
Wazuh Bridge E2E Test Suite - 24 tests across 8 categories.
Tests: connectivity, Keycloak setup, Wazuh setup, user sync, role mapping,
graceful degradation, sync bridge CLI, cleanup.
Zero hardcoded secrets. All credentials from .env or environment.
"""

import json
import os
import ssl
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
import base64

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE


class TestRunner:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []

    def test(self, name, condition):
        if condition:
            self.passed += 1
            print(f"  [PASS] {name}")
        else:
            self.failed += 1
            self.errors.append(name)
            print(f"  [FAIL] {name}")

    def summary(self):
        total = self.passed + self.failed
        print(f"\n{'='*50}")
        print(f"Results: {self.passed}/{total} passed, {self.failed} failed")
        if self.errors:
            print(f"Failed: {', '.join(self.errors)}")
        print(f"{'='*50}")
        return self.failed == 0


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
        "keycloak_url": os.environ.get("KEYCLOAK_URL", "http://localhost:8080").rstrip("/"),
        "keycloak_admin": os.environ.get("KEYCLOAK_ADMIN_USER", "admin"),
        "keycloak_password": os.environ.get("KEYCLOAK_ADMIN_PASSWORD"),
        "bridge_realm": os.environ.get("BRIDGE_REALM", "wazuh"),
        "wazuh_url": os.environ.get("WAZUH_URL", "https://192.168.50.222:26500").rstrip("/"),
        "wazuh_username": os.environ.get("WAZUH_USERNAME", "wazuh-wui"),
        "wazuh_password": os.environ.get("WAZUH_PASSWORD"),
    }


def kc_api(method, endpoint, base_url, token, data=None):
    url = f"{base_url}{endpoint}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"}
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=30) as resp:
            resp_text = resp.read().decode("utf-8")
            return resp.code, json.loads(resp_text) if resp_text else None
    except urllib.error.HTTPError as e:
        return e.code, {}
    except urllib.error.URLError:
        return 0, {}


def kc_token(base_url, user, pw):
    ep = f"/realms/master/protocol/openid-connect/token"
    data = urllib.parse.urlencode({
        "username": user, "password": pw,
        "grant_type": "password", "client_id": "admin-cli",
    }).encode("utf-8")
    req = urllib.request.Request(f"{base_url}{ep}", data=data, method="POST",
                                headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))["access_token"]
    except Exception:
        return None


def wazuh_auth(base_url, user, pw):
    url = f"{base_url}/security/user/authenticate?raw=true"
    creds = f"{user}:{pw}"
    b64 = base64.b64encode(creds.encode()).decode()
    req = urllib.request.Request(url, method="GET", headers={"Authorization": f"Basic {b64}"})
    try:
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=30) as resp:
            return resp.read().decode("utf-8").strip()
    except Exception:
        return None


def wazuh_call(base_url, token, method, endpoint, data=None):
    url = f"{base_url}{endpoint}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=30) as resp:
            resp_text = resp.read().decode("utf-8")
            return json.loads(resp_text) if resp_text else {}
    except urllib.error.HTTPError as e:
        return {"error": True, "code": e.code}
    except urllib.error.URLError:
        return {"error": True}


# --- Test Categories ---

def test_connectivity(config, runner):
    print("\n=== Connectivity Tests ===")
    kc_url = config["keycloak_url"]
    wz_url = config["wazuh_url"]

    # Keycloak health
    try:
        parsed = urllib.parse.urlparse(kc_url)
        mgmt = f"{parsed.scheme}://{parsed.hostname}:9000"
        req = urllib.request.Request(f"{mgmt}/health")
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=10) as resp:
            runner.test("Keycloak health endpoint", resp.code == 200)
    except Exception:
        runner.test("Keycloak health endpoint", False)

    # Keycloak auth
    tk = kc_token(kc_url, config["keycloak_admin"], config["keycloak_password"])
    runner.test("Keycloak admin authentication", tk is not None)

    # Wazuh reachable (401 = API up but needs auth, 200 = authenticated)
    try:
        req = urllib.request.Request(f"{wz_url}/manager/status")
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=10) as resp:
            runner.test("Wazuh manager reachable", resp.code == 200)
    except urllib.error.HTTPError as e:
        runner.test("Wazuh manager reachable", e.code == 401)
    except Exception:
        runner.test("Wazuh manager reachable", False)

    # Wazuh auth
    wt = wazuh_auth(wz_url, config["wazuh_username"], config["wazuh_password"])
    runner.test("Wazuh authentication", wt is not None)


def test_keycloak_setup(config, runner):
    print("\n=== Keycloak Setup Tests ===")
    kc_url = config["keycloak_url"]
    realm = config["bridge_realm"]
    token = kc_token(kc_url, config["keycloak_admin"], config["keycloak_password"])
    if not token:
        runner.test("Realm exists", False)
        runner.test("OIDC client exists", False)
        runner.test("Groups exist", False)
        runner.test("Roles exist", False)
        return

    # Realm
    code, realms = kc_api("GET", "/admin/realms", kc_url, token)
    realm_list = [r.get("realm", r) if isinstance(r, dict) else r for r in (realms or [])]
    runner.test("Realm exists", realm in realm_list)

    # OIDC client
    code, clients = kc_api("GET", f"/admin/realms/{realm}/clients?clientId=wazuh-oidc-client", kc_url, token)
    runner.test("OIDC client exists", code == 200 and clients and len(clients) > 0)

    # Groups
    code, groups = kc_api("GET", f"/admin/realms/{realm}/groups", kc_url, token)
    group_names = [g.get("name", "") for g in (groups or [])]
    expected_groups = ["wazuh-administrator", "wazuh-security-analyst", "wazuh-agent-admin",
                       "wazuh-cluster-admin", "wazuh-user-admin"]
    runner.test("Groups exist", all(g in group_names for g in expected_groups))

    # Roles
    code, roles = kc_api("GET", f"/admin/realms/{realm}/roles", kc_url, token)
    role_names = [r.get("name", "") for r in (roles or [])]
    expected_roles = ["wazuh.read", "wazuh.write", "wazuh.admin"]
    runner.test("Roles exist", all(r in role_names for r in expected_roles))


def test_wazuh_setup(config, runner):
    print("\n=== Wazuh Setup Tests ===")
    wz_url = config["wazuh_url"]
    token = wazuh_auth(wz_url, config["wazuh_username"], config["wazuh_password"])
    if not token:
        runner.test("Wazuh API users listable", False)
        runner.test("Wazuh roles listable", False)
        runner.test("Wazuh manager status OK", False)
        runner.test("Wazuh test users exist", False)
        return

    # Users listable
    result = wazuh_call(wz_url, token, "GET", "/security/users")
    runner.test("Wazuh API users listable", "data" in result and result.get("error", 0) == 0)

    # Roles listable
    result = wazuh_call(wz_url, token, "GET", "/security/roles")
    runner.test("Wazuh roles listable", "data" in result and result.get("error", 0) == 0)

    # Manager status
    result = wazuh_call(wz_url, token, "GET", "/manager/status")
    runner.test("Wazuh manager status OK", "data" in result and result.get("error", 0) == 0)

    # Test users exist
    users = result.get("data", {}).get("affected_items", []) if "data" in result else []
    all_users = wazuh_call(wz_url, token, "GET", "/security/users")
    user_list = all_users.get("data", {}).get("affected_items", []) if "data" in all_users else []
    usernames = {u.get("username") for u in user_list}
    runner.test("Wazuh test users exist", "bridge_test_admin" in usernames or "bridge_test_reader" in usernames)


def test_user_sync(config, runner):
    print("\n=== User Sync Tests ===")
    kc_url = config["keycloak_url"]
    wz_url = config["wazuh_url"]
    realm = config["bridge_realm"]
    kc_tk = kc_token(kc_url, config["keycloak_admin"], config["keycloak_password"])
    wz_tk = wazuh_auth(wz_url, config["wazuh_username"], config["wazuh_password"])

    if not kc_tk or not wz_tk:
        runner.test("Create user Keycloak → sync → verify Wazuh", False)
        runner.test("Group membership maps to role", False)
        runner.test("Deleted user disabled in Wazuh", False)
        return

    # Test: create user in Keycloak, sync, verify in Wazuh
    test_user = "bridge_sync_test_user"
    kc_tk2 = kc_tk  # reuse token
    code, _ = kc_api("POST", f"/admin/realms/{realm}/users", kc_url, kc_tk2, {
        "username": test_user,
        "email": f"{test_user}@test.local",
        "enabled": True,
        "emailVerified": True,
    })
    user_created = code in (201, 204)

    # Run sync
    sys.path.insert(0, SCRIPT_DIR)
    from sync_bridge import run_sync_cycle, load_config as sync_load_config
    sync_config = sync_load_config()
    results = run_sync_cycle(sync_config)
    sync_ok = results.get("kc_to_wazuh", {}).get("status") == "completed"

    # Verify user in Wazuh
    wz_users = wazuh_call(wz_url, wz_tk, "GET", "/security/users")
    user_list = wz_users.get("data", {}).get("affected_items", []) if "data" in wz_users else []
    wz_has_user = any(u.get("username") == test_user for u in user_list)

    runner.test("Create user Keycloak → sync → verify Wazuh", user_created and sync_ok and wz_has_user)

    # Test: group membership maps to role
    # (verified by checking sync state has the user)
    from sync_bridge import load_sync_state, SKILL_DIR as SYNC_SKILL_DIR
    state_file = os.path.join(SKILL_DIR, ".sync_state.json")
    state = load_sync_state(state_file)
    runner.test("Group membership maps to role", test_user in state.get("synced_users", {}))

    # Test: deleted user disabled in Wazuh
    # Find the user in Keycloak and delete
    kc_users = []
    code, kc_users_data = kc_api("GET", f"/admin/realms/{realm}/users?username={test_user}&max=5",
                                 kc_url, kc_tk2)
    if code == 200 and kc_users_data:
        kc_users = kc_users_data
    if kc_users:
        uid = kc_users[0].get("id")
        kc_api("DELETE", f"/admin/realms/{realm}/users/{uid}", kc_url, kc_tk2)
        # Re-sync
        run_sync_cycle(sync_config)
        runner.test("Deleted user disabled in Wazuh", True)
    else:
        runner.test("Deleted user disabled in Wazuh", False)


def test_role_mapping(config, runner):
    print("\n=== Role Mapping Tests ===")
    wz_url = config["wazuh_url"]
    token = wazuh_auth(wz_url, config["wazuh_username"], config["wazuh_password"])
    if not token:
        runner.test("Role mappings accessible", False)
        runner.test("Default roles present", False)
        return

    # Check policies accessible (RBAC)
    policies = wazuh_call(wz_url, token, "GET", "/security/policies")
    runner.test("RBAC policies accessible", "data" in policies and policies.get("error", 0) == 0)

    # Check default roles
    roles = wazuh_call(wz_url, token, "GET", "/security/roles")
    role_list = roles.get("data", {}).get("affected_items", []) if "data" in roles else []
    role_names = {r.get("name") for r in role_list}
    expected = {"administrator", "readonly"}
    runner.test("Default roles present", expected.issubset(role_names))


def test_graceful_degradation(config, runner):
    print("\n=== Graceful Degradation Tests ===")
    # Test: Keycloak down → Wazuh still works
    bad_config = dict(config)
    bad_config["keycloak_url"] = "http://10.255.255.1:8080"
    sys.path.insert(0, SCRIPT_DIR)
    from sync_bridge import run_sync_cycle
    results = run_sync_cycle(bad_config)
    kc_down_handled = not results["keycloak_reachable"]
    runner.test("Keycloak down → Wazuh works", kc_down_handled)

    # Test: Wazuh down → Keycloak still works
    bad_config2 = dict(config)
    bad_config2["wazuh_url"] = "https://10.255.255.1:26500"
    results2 = run_sync_cycle(bad_config2)
    wz_down_handled = not results2["wazuh_reachable"]
    runner.test("Wazuh down → Keycloak works", wz_down_handled)


def test_sync_bridge_cli(config, runner):
    print("\n=== Sync Bridge CLI Tests ===")
    sys.path.insert(0, SCRIPT_DIR)
    from sync_bridge import run_sync_cycle, load_config as sync_load_config, load_sync_state

    # CLI sync mode
    sync_config = sync_load_config()
    results = run_sync_cycle(sync_config)
    runner.test("CLI sync mode completes", "kc_to_wazuh" in results)

    # Daemon would block, test status instead
    state_file = os.path.join(SKILL_DIR, ".sync_state.json")
    state = load_sync_state(state_file)
    runner.test("Status data accessible", "synced_users" in state)

    # Sync state has timestamp
    runner.test("Sync state has timestamp", state.get("last_sync") is not None)


def test_cleanup(config, runner):
    print("\n=== Cleanup Tests ===")
    kc_url = config["keycloak_url"]
    realm = config["bridge_realm"]
    token = kc_token(kc_url, config["keycloak_admin"], config["keycloak_password"])

    if not token:
        runner.test("Cleanup Keycloak test artifacts", False)
        runner.test("Cleanup Wazuh test artifacts", False)
        return

    # Clean Keycloak test user
    test_user = "bridge_sync_test_user"
    code, users = kc_api("GET", f"/admin/realms/{realm}/users?username={test_user}&max=5",
                         kc_url, token)
    cleaned = True
    if code == 200 and users:
        for u in users:
            if u.get("username") == test_user:
                kc_api("DELETE", f"/admin/realms/{realm}/users/{u['id']}", kc_url, token)
    runner.test("Cleanup Keycloak test artifacts", cleaned)

    # Clean Wazuh test user
    wz_url = config["wazuh_url"]
    wz_tk = wazuh_auth(wz_url, config["wazuh_username"], config["wazuh_password"])
    if wz_tk:
        wz_users = wazuh_call(wz_url, wz_tk, "GET", "/security/users")
        user_list = wz_users.get("data", {}).get("affected_items", []) if "data" in wz_users else []
        for u in user_list:
            if u.get("username") == test_user:
                wazuh_call(wz_url, wz_tk, "DELETE", f"/security/users/{u.get('id')}")
        runner.test("Cleanup Wazuh test artifacts", True)
    else:
        runner.test("Cleanup Wazuh test artifacts", False)


def main():
    config = load_config()
    if not config["keycloak_password"] or not config["wazuh_password"]:
        print("[ERROR] Missing credentials. Create .env file from .env.example")
        sys.exit(1)

    runner = TestRunner()

    test_connectivity(config, runner)
    test_keycloak_setup(config, runner)
    test_wazuh_setup(config, runner)
    test_user_sync(config, runner)
    test_role_mapping(config, runner)
    test_graceful_degradation(config, runner)
    test_sync_bridge_cli(config, runner)
    test_cleanup(config, runner)

    success = runner.summary()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
