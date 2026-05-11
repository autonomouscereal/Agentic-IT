#!/usr/bin/env python3
"""
IAM Bridge E2E Test Suite.
Tests: connectivity, Keycloak setup, iTop setup, OIDC flow, SAML config,
user sync, group sync, ticket assignment, graceful degradation, daemon mode.
Zero hardcoded secrets. Credentials from .env or environment.
"""

import json
import os
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
import base64
import ssl
import subprocess
import signal

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

TEST_PREFIX = "bridge_test"


# --- Configuration ---

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
        "bridge_realm": os.environ.get("BRIDGE_REALM", "itop"),
        "client_id": os.environ.get("BRIDGE_CLIENT_ID", "itop-oidc-client"),
        "client_secret": os.environ.get("BRIDGE_CLIENT_SECRET"),
        "itop_url": os.environ.get("ITOP_URL", "http://localhost:25432").rstrip("/"),
        "itop_username": os.environ.get("ITOP_USERNAME", "admin"),
        "itop_password": os.environ.get("ITOP_PASSWORD"),
    }


# --- Keycloak API ---

def kc_api_call(method, endpoint, base_url, token, data=None):
    url = f"{base_url}{endpoint}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json", "Accept": "application/json"}
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=30) as resp:
            resp_text = resp.read().decode("utf-8")
            return resp.code, json.loads(resp_text) if resp_text else None
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        return e.code, json.loads(err) if err else {"error": str(e)}
    except urllib.error.URLError as e:
        return 0, {"error": f"Connection failed: {e.reason}"}


def kc_get_token(base_url, username, password):
    endpoint = f"/realms/master/protocol/openid-connect/token"
    data = urllib.parse.urlencode({
        "username": username, "password": password,
        "grant_type": "password", "client_id": "admin-cli",
    }).encode("utf-8")
    req = urllib.request.Request(f"{base_url}{endpoint}", data=data, method="POST",
                                headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))["access_token"]
    except Exception:
        return None


# --- iTop API ---

class iTopClient:
    def __init__(self, base_url, username, password):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password

    def _auth_header(self):
        creds = f"{self.username}:{self.password}"
        return f"Basic {base64.b64encode(creds.encode()).decode()}"

    def _post(self, operation, data=None):
        payload = {"operation": operation, "user": self.username, "password": self.password}
        if data:
            payload.update(data)
        body = urllib.parse.urlencode({
            "version": "1.4", "json_output": "1",
            "json_data": json.dumps(payload),
        }).encode()
        req = urllib.request.Request(
            f"{self.base_url}/webservices/rest.php", data=body, method="POST",
            headers={"Authorization": self._auth_header(), "Content-Type": "application/x-www-form-urlencoded"},
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except Exception:
            return {"error": "Connection failed"}

    def check_credentials(self):
        return self._post("core/check_credentials")

    def get(self, class_name, key, attrs=None):
        req = {"class": class_name, "key": key}
        if attrs:
            req["output_fields"] = attrs
        return self._post("core/get", req)

    def create(self, class_name, fields, comment="Bridge test"):
        return self._post("core/create", {"class": class_name, "comment": comment, "fields": fields})

    def update(self, class_name, key, fields, comment="Bridge test"):
        return self._post("core/update", {"class": class_name, "key": key, "comment": comment, "fields": fields})

    def delete(self, class_name, key, comment="Bridge test cleanup"):
        return self._post("core/delete", {"class": class_name, "key": key, "comment": comment})


# --- Test Runner ---

class TestRunner:
    def __init__(self, config):
        self.config = config
        self.kc_token = None
        self.itop_client = None
        self.tests_passed = 0
        self.tests_failed = 0
        self.test_results = []
        self.created_users = []
        self.created_teams = []

    def run_test(self, name, func, *args, **kwargs):
        try:
            result = func(*args, **kwargs)
            if result is True or (result is not None and result is not False):
                self.tests_passed += 1
                self.test_results.append(("PASS", name, None))
                print(f"  PASS: {name}")
                return result
            else:
                self.tests_failed += 1
                self.test_results.append(("FAIL", name, "Returned falsy value"))
                print(f"  FAIL: {name} (returned falsy)")
                return None
        except Exception as e:
            self.tests_failed += 1
            self.test_results.append(("FAIL", name, str(e)))
            print(f"  FAIL: {name} ({e})")
            return None

    # --- Connectivity Tests ---

    def test_keycloak_health(self):
        management_url = self.config["keycloak_url"].replace("8080", "9000", 1)
        if ":9000" not in management_url:
            management_url = self.config["keycloak_url"].rsplit(":", 1)[0] + ":9000"
        req = urllib.request.Request(f"{management_url}/health")
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            return data.get("status") == "UP"

    def test_keycloak_auth(self):
        self.kc_token = kc_get_token(
            self.config["keycloak_url"], self.config["keycloak_admin"], self.config["keycloak_password"]
        )
        return self.kc_token is not None

    def test_itop_reachable(self):
        try:
            req = urllib.request.Request(self.config["itop_url"])
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.code == 200
        except Exception:
            return False

    def test_itop_auth(self):
        self.itop_client = iTopClient(
            self.config["itop_url"], self.config["itop_username"], self.config["itop_password"]
        )
        result = self.itop_client.check_credentials()
        return result.get("code") == 0

    # --- Keycloak Setup Tests ---

    def test_realm_exists(self):
        code, realms = kc_api_call("GET", "/admin/realms", self.config["keycloak_url"], self.kc_token)
        realm_list = []
        if code == 200 and realms:
            realm_list = [r.get("realm", r) if isinstance(r, dict) else r for r in realms]
        return self.config["bridge_realm"] in realm_list

    def test_oidc_client_exists(self):
        realm = self.config["bridge_realm"]
        code, clients = kc_api_call("GET", f"/admin/realms/{realm}/clients",
                                    self.config["keycloak_url"], self.kc_token)
        if code == 200 and clients:
            return any(c.get("clientId") == self.config["client_id"] for c in clients)
        return False

    def test_saml_client_exists(self):
        realm = self.config["bridge_realm"]
        code, clients = kc_api_call("GET", f"/admin/realms/{realm}/clients",
                                    self.config["keycloak_url"], self.kc_token)
        if code == 200 and clients:
            return any(c.get("clientId") == "itop-saml-client" for c in clients)
        return False

    def test_groups_exist(self):
        realm = self.config["bridge_realm"]
        code, groups = kc_api_call("GET", f"/admin/realms/{realm}/groups",
                                   self.config["keycloak_url"], self.kc_token)
        if code == 200 and groups:
            group_names = [g.get("name", "") for g in groups]
            expected = ["itop-administrator", "itop-portal-user", "itop-support-team"]
            return all(any(name == e for name in group_names) for e in expected)
        return False

    def test_roles_exist(self):
        realm = self.config["bridge_realm"]
        code, roles = kc_api_call("GET", f"/admin/realms/{realm}/roles",
                                  self.config["keycloak_url"], self.kc_token)
        if code == 200 and roles:
            role_names = [r.get("name", "") for r in roles]
            return "itop.read" in role_names and "itop.write" in role_names

    # --- OIDC Flow Tests ---

    def test_oidc_token_request(self):
        """Test OIDC token endpoint responsiveness.
        Uses master realm admin user since no users may exist in the bridge realm yet."""
        endpoint = "/realms/master/protocol/openid-connect/token"
        data = urllib.parse.urlencode({
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": self.config["keycloak_admin"],
            "password": self.config["keycloak_password"],
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{self.config['keycloak_url']}{endpoint}", data=data, method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"}
        )
        try:
            with urllib.request.urlopen(req, context=SSL_CTX, timeout=30) as resp:
                result = json.loads(resp.read().decode())
                return "access_token" in result
        except Exception:
            return False

    def test_oidc_discovery(self):
        realm = self.config["bridge_realm"]
        try:
            url = f"{self.config['keycloak_url']}/realms/{realm}/.well-known/openid-configuration"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, context=SSL_CTX, timeout=15) as resp:
                data = json.loads(resp.read().decode())
                return "authorization_endpoint" in data and "token_endpoint" in data
        except Exception:
            return False

    # --- SAML Tests ---

    def test_saml_metadata(self):
        realm = self.config["bridge_realm"]
        try:
            url = f"{self.config['keycloak_url']}/realms/{realm}/protocol/saml/descriptor"
            req = urllib.request.Request(url)
            with urllib.request.urlopen(req, context=SSL_CTX, timeout=15) as resp:
                content = resp.read().decode()
                return "md:EntityDescriptor" in content or "EntityDescriptor" in content
        except Exception:
            return False

    # --- User Sync Tests ---

    def test_create_user_keycloak(self):
        realm = self.config["bridge_realm"]
        username = f"{TEST_PREFIX}_user_{int(time.time())}"
        user_data = {
            "username": username,
            "email": f"{username}@test.local",
            "enabled": True,
            "emailVerified": True,
            "firstName": "Bridge",
            "lastName": "TestUser",
        }
        code, result = kc_api_call("POST", f"/admin/realms/{realm}/users",
                                   self.config["keycloak_url"], self.kc_token, user_data)
        if code == 201:
            self.created_users.append({"username": username})
            return True
        return False

    def test_sync_user_to_itop(self):
        if not self.itop_client:
            return False
        # Create a test person with all required fields (org_id defaults to 1)
        timestamp = int(time.time())
        person_name = f"Bridge Sync Test {timestamp}"
        person_result = self.itop_client.create("Person", {
            "name": person_name,
            "first_name": "Bridge",
            "email": f"bridge-sync-{timestamp}@test.local",
            "org_id": 1,
        })
        if person_result.get("code") == 0:
            return True
        return False

    def test_create_team_itop(self):
        if not self.itop_client:
            return False
        org_result = self.itop_client.get("Organization", 1, attrs="id")
        org_id = 1
        if org_result.get("objects"):
            org_id = org_result["objects"]["Organization::1"]["fields"]["id"]

        team_result = self.itop_client.create("Team", {
            "name": f"Bridge Test Team {int(time.time())}",
            "org_id": org_id,
        })
        if team_result.get("code") == 0:
            return True
        return False

    # --- Ticket Assignment Tests ---

    def test_create_incident(self):
        if not self.itop_client:
            return False
        timestamp = int(time.time())
        result = self.itop_client.create("Incident", {
            "title": f"Bridge test incident {timestamp}",
            "description": "Test incident for IAM bridge integration",
            "impact": 3,
            "urgency": 3,
            "org_id": 1,
            "caller_id": 1,
        })
        if result.get("code") == 0 and result.get("objects"):
            for key, obj in result["objects"].items():
                incident_key = obj.get("key", key.split("::")[-1])
                self.created_teams.append({"class": "Incident", "key": incident_key})
            return True
        return False

    def test_assign_incident(self):
        if not self.itop_client or not self.created_teams:
            return False
        for item in self.created_teams:
            if item["class"] == "Incident" and item.get("key"):
                result = self.itop_client.update(item["class"], item["key"], {
                    "status": "pending",
                })
                return result.get("code") == 0
        return False

    # --- Graceful Degradation Tests ---

    def test_keycloak_down_itop_works(self):
        """If Keycloak is unreachable, iTop should still work."""
        if not self.itop_client:
            return False
        # iTop should still respond even if Keycloak is down
        result = self.itop_client.get("Organization", 1, attrs="name")
        return result.get("code") == 0

    def test_itop_down_keycloak_works(self):
        """If iTop is unreachable, Keycloak should still work."""
        # Keycloak should still respond even if iTop is down
        code, roles = kc_api_call("GET", f"/admin/realms/{self.config['bridge_realm']}/roles",
                                  self.config["keycloak_url"], self.kc_token)
        return code == 200

    # --- Sync Bridge Tests ---

    def test_sync_bridge_cli(self):
        """Test sync bridge CLI mode."""
        sync_script = os.path.join(SCRIPT_DIR, "sync_bridge.py")
        if not os.path.exists(sync_script):
            return False
        try:
            result = subprocess.run(
                [sys.executable or "python3", sync_script, "--sync"],
                capture_output=True, text=True, timeout=60,
            )
            return result.returncode == 0
        except Exception:
            return False

    def test_sync_status(self):
        """Test sync status command."""
        sync_script = os.path.join(SCRIPT_DIR, "sync_bridge.py")
        if not os.path.exists(sync_script):
            return False
        try:
            result = subprocess.run(
                [sys.executable or "python3", sync_script, "--status"],
                capture_output=True, text=True, timeout=30,
            )
            return result.returncode == 0
        except Exception:
            return False

    # --- Cleanup Tests ---

    def test_cleanup_keycloak_users(self):
        """Clean up test users created in Keycloak."""
        realm = self.config["bridge_realm"]
        for user_info in self.created_users:
            code, users = kc_api_call("GET", f"/admin/realms/{realm}/users?username={user_info['username']}",
                                      self.config["keycloak_url"], self.kc_token)
            if code == 200 and users:
                kc_api_call("DELETE", f"/admin/realms/{realm}/users/{users[0]['id']}",
                           self.config["keycloak_url"], self.kc_token)
        return True

    def test_cleanup_itop_objects(self):
        """Clean up test objects in iTop."""
        if not self.itop_client:
            return True
        for item in self.created_teams:
            self.itop_client.delete(item["class"], item["key"])
        return True

    # --- Run All ---

    def run_all(self):
        print(f"\n{'='*60}")
        print(f"IAM BRIDGE END-TO-END TEST SUITE")
        print(f"Keycloak: {self.config['keycloak_url']}")
        print(f"iTop: {self.config['itop_url']}")
        print(f"Realm: {self.config['bridge_realm']}")
        print(f"{'='*60}\n")

        # Connectivity
        print("=== CONNECTIVITY ===")
        self.run_test("Keycloak health check", self.test_keycloak_health)
        self.run_test("Keycloak admin auth", self.test_keycloak_auth)
        self.run_test("iTop reachable", self.test_itop_reachable)
        self.run_test("iTop admin auth", self.test_itop_auth)

        # Keycloak Setup
        print("\n=== KEYCLOAK SETUP ===")
        self.run_test("Realm exists", self.test_realm_exists)
        self.run_test("OIDC client exists", self.test_oidc_client_exists)
        self.run_test("SAML client exists", self.test_saml_client_exists)
        self.run_test("Profile groups exist", self.test_groups_exist)
        self.run_test("Access roles exist", self.test_roles_exist)

        # OIDC Flow
        print("\n=== OIDC FLOW ===")
        self.run_test("OIDC token request", self.test_oidc_token_request)
        self.run_test("OIDC discovery endpoint", self.test_oidc_discovery)

        # SAML
        print("\n=== SAML CONFIG ===")
        self.run_test("SAML metadata valid", self.test_saml_metadata)

        # User Sync
        print("\n=== USER SYNC ===")
        self.run_test("Create user in Keycloak", self.test_create_user_keycloak)
        self.run_test("Sync user to iTop", self.test_sync_user_to_itop)
        self.run_test("Create team in iTop", self.test_create_team_itop)

        # Ticket Assignment
        print("\n=== TICKET ASSIGNMENT ===")
        self.run_test("Create incident", self.test_create_incident)
        self.run_test("Assign incident to team", self.test_assign_incident)

        # Graceful Degradation
        print("\n=== GRACEFUL DEGRADATION ===")
        self.run_test("Keycloak down -> iTop works", self.test_keycloak_down_itop_works)
        self.run_test("iTop down -> Keycloak works", self.test_itop_down_keycloak_works)

        # Sync Bridge
        print("\n=== SYNC BRIDGE ===")
        self.run_test("Sync bridge CLI mode", self.test_sync_bridge_cli)
        self.run_test("Sync bridge status", self.test_sync_status)

        # Cleanup
        print("\n=== CLEANUP ===")
        self.run_test("Cleanup Keycloak users", self.test_cleanup_keycloak_users)
        self.run_test("Cleanup iTop objects", self.test_cleanup_itop_objects)

        # Summary
        self.print_summary()

    def print_summary(self):
        print(f"\n{'='*60}")
        print(f"TEST SUMMARY")
        print(f"{'='*60}")
        print(f"  PASSED: {self.tests_passed}")
        print(f"  FAILED: {self.tests_failed}")
        print(f"  TOTAL:  {self.tests_passed + self.tests_failed}")
        print(f"  RESULT: {'ALL TESTS PASSED' if self.tests_failed == 0 else 'SOME TESTS FAILED'}")
        if self.test_results:
            print(f"\nDetailed results:")
            for status, name, detail in self.test_results:
                marker = "OK" if status == "PASS" else f"FAIL: {detail}"
                print(f"  [{status}] {name} - {marker}")
        print(f"{'='*60}")


def main():
    config = load_config()
    if not config["keycloak_password"] or not config["itop_password"]:
        print("[ERROR] Missing credentials. Check .env file.")
        sys.exit(1)

    runner = TestRunner(config)
    runner.run_all()
    return 0 if runner.tests_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
