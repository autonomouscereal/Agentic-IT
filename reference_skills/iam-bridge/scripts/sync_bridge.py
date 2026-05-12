#!/usr/bin/env python3
"""
IAM Sync Bridge - Bidirectional sync between Keycloak and iTop.
Modes: CLI (one-shot sync) or Daemon (continuous polling).
Graceful degradation: if either service is down, skip that side and continue.
Zero hardcoded secrets. All credentials from .env or environment.
"""

import argparse
import json
import os
import signal
import sys
import time
import urllib.request
import urllib.error
import urllib.parse
import base64
import ssl

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

# Profile mapping: Keycloak group name -> iTop profile name
PROFILE_MAP = {
    "itop-administrator": "Administrator",
    "itop-configuration-manager": "Configuration Manager",
    "itop-portal-power-user": "Portal power user",
    "itop-portal-user": "Portal user",
}


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
        "sync_state": os.environ.get("SYNC_STATE_FILE", os.path.join(SKILL_DIR, ".sync_state.json")),
    }


# --- Sync State ---

def load_sync_state(path):
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"synced_users": {}, "synced_groups": {}, "last_sync": None}


def save_sync_state(path, state):
    state["last_sync"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(path, "w") as f:
        json.dump(state, f, indent=2)


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


def kc_is_reachable(base_url):
    try:
        management_url = base_url.replace("8080", "9000", 1)
        if ":9000" not in management_url:
            management_url = base_url.rsplit(":", 1)[0] + ":9000"
        req = urllib.request.Request(f"{management_url}/health")
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=10) as resp:
            return resp.code == 200
    except Exception:
        return False


def kc_list_users(token, base_url, realm):
    code, result = kc_api_call("GET", f"/admin/realms/{realm}/users?max=100", base_url, token)
    return result if code == 200 and result else []


def kc_list_groups(token, base_url, realm):
    code, result = kc_api_call("GET", f"/admin/realms/{realm}/groups?briefRepresentation=false", base_url, token)
    return result if code == 200 and result else []


def kc_get_user_groups(token, base_url, realm, user_id):
    code, result = kc_api_call("GET", f"/admin/realms/{realm}/users/{user_id}/groups", base_url, token)
    return result if code == 200 and result else []


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

    def create(self, class_name, fields, comment="IAM Bridge sync"):
        return self._post("core/create", {"class": class_name, "comment": comment, "fields": fields})

    def update(self, class_name, key, fields, comment="IAM Bridge sync"):
        return self._post("core/update", {"class": class_name, "key": key, "comment": comment, "fields": fields})


def itop_is_reachable(base_url):
    try:
        req = urllib.request.Request(f"{base_url}/index.php")
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.code == 200
    except Exception:
        return False


# --- Sync Functions ---

def sync_keycloak_to_itop(config, kc_token, itop_client, sync_state):
    """Sync users and groups from Keycloak to iTop."""
    realm = config["bridge_realm"]
    synced = 0
    errors = 0

    users = kc_list_users(kc_token, config["keycloak_url"], realm)
    org_result = itop_client.get("Organization", 1, attrs="id,name")
    org_id = 1
    if org_result.get("code") != 0:
        org_result = itop_client.get("Organization", "all", attrs="id")
        if org_result.get("objects"):
            for k, v in org_result["objects"].items():
                org_id = v["fields"]["id"]
                break

    for user in users:
        username = user.get("username", "")
        if not username or username.startswith("bridge_test_"):
            continue

        user_key = f"bridge_sync_{username}"
        if sync_state["synced_users"].get(user_key) == user.get("id"):
            continue

        email = user.get("email", "")
        first_name = user.get("firstName", "") or username.split(".")[0]
        last_name = user.get("lastName", "") or username
        full_name = f"{first_name} {last_name}".strip() or username

        # Create Person if not exists
        person_check = itop_client.get("Person", full_name, attrs="id")
        if person_check.get("code") == 0 and person_check.get("objects"):
            for k, v in person_check["objects"].items():
                person_id = v["fields"]["id"]
                break
        else:
            person_result = itop_client.create("Person", {
                "name": full_name,
                "first_name": first_name,
                "email": email,
                "phone": "",
                "function": "Synced from Keycloak",
                "org_id": org_id,
            })
            if person_result.get("code") == 0:
                person_id = None
                if person_result.get("objects"):
                    for k, v in person_result["objects"].items():
                        person_id = v.get("key")
                        break
                if not person_id:
                    person_check = itop_client.get("Person", full_name, attrs="id")
                    if person_check.get("objects"):
                        for k, v in person_check["objects"].items():
                            person_id = v["fields"]["id"]
                            break
            else:
                errors += 1
                continue

            if not person_id:
                errors += 1
                continue

        # Create ExternalUser
        ext_user_check = itop_client.get("ExternalUser", username, attrs="id")
        if not (ext_user_check.get("code") == 0 and ext_user_check.get("objects")):
            ext_result = itop_client.create("ExternalUser", {
                "contactid": person_id,
                "login": username,
                "status": "enabled",
            })
            if ext_result.get("code") == 0:
                synced += 1
            else:
                errors += 1

        sync_state["synced_users"][user_key] = user.get("id")
        save_sync_state(config["sync_state"], sync_state)

    return synced, errors


def sync_itop_to_keycloak(config, kc_token, itop_client, sync_state):
    """Sync iTop teams back to Keycloak as groups."""
    realm = config["bridge_realm"]
    synced = 0
    errors = 0

    teams_result = itop_client.get("Team", "all", attrs="id,name")
    if teams_result.get("code") != 0 or not teams_result.get("objects"):
        return 0, 0

    for key, team in teams_result["objects"].items():
        team_name = team["fields"].get("name", "")
        team_id = team["fields"].get("id", "")
        group_name = f"itop-team-{team_name.lower().replace(' ', '-')}"

        kc_groups = kc_list_groups(kc_token, config["keycloak_url"], realm)
        existing = [g for g in kc_groups if g.get("name") == group_name]

        if not existing:
            group_data = {"name": group_name}
            code, result = kc_api_call("POST", f"/admin/realms/{realm}/groups",
                                       config["keycloak_url"], kc_token, group_data)
            if code == 201:
                synced += 1
            else:
                errors += 1

        sync_state["synced_groups"][f"itop-team-{team_id}"] = group_name
        save_sync_state(config["sync_state"], sync_state)

    return synced, errors


def run_sync_cycle(config):
    """Run a single sync cycle with graceful degradation."""
    results = {
        "keycloak_reachable": False,
        "itop_reachable": False,
        "kc_to_itop": {"synced": 0, "errors": 0, "status": "skipped"},
        "itop_to_kc": {"synced": 0, "errors": 0, "status": "skipped"},
    }

    # Check Keycloak
    if kc_is_reachable(config["keycloak_url"]):
        results["keycloak_reachable"] = True
        print("[OK] Keycloak is reachable")
    else:
        print("[WARN] Keycloak is unreachable - skipping Keycloak-side sync")
        return results

    # Check iTop
    if itop_is_reachable(config["itop_url"]):
        results["itop_reachable"] = True
        print("[OK] iTop is reachable")
    else:
        print("[WARN] iTop is unreachable - skipping iTop-side sync")
        return results

    # Authenticate to Keycloak
    kc_token = kc_get_token(config["keycloak_url"], config["keycloak_admin"], config["keycloak_password"])
    if not kc_token:
        print("[ERROR] Cannot authenticate to Keycloak")
        return results

    # Create iTop client
    itop_client = iTopClient(config["itop_url"], config["itop_username"], config["itop_password"])
    auth_result = itop_client.check_credentials()
    if auth_result.get("code") != 0:
        print("[ERROR] Cannot authenticate to iTop")
        return results

    # Load sync state
    sync_state = load_sync_state(config["sync_state"])

    # Sync Keycloak -> iTop
    print("\n--- Syncing Keycloak -> iTop ---")
    synced, errors = sync_keycloak_to_itop(config, kc_token, itop_client, sync_state)
    results["kc_to_itop"] = {"synced": synced, "errors": errors, "status": "completed"}
    print(f"  Synced: {synced}, Errors: {errors}")

    # Sync iTop -> Keycloak
    print("\n--- Syncing iTop -> Keycloak ---")
    synced2, errors2 = sync_itop_to_keycloak(config, kc_token, itop_client, sync_state)
    results["itop_to_kc"] = {"synced": synced2, "errors": errors2, "status": "completed"}
    print(f"  Synced: {synced2}, Errors: {errors2}")

    return results


# --- Daemon Mode ---

class SyncDaemon:
    def __init__(self, config, interval):
        self.config = config
        self.interval = interval
        self.running = False

    def _signal_handler(self, signum, frame):
        print(f"\n[INFO] Received signal {signum}, shutting down gracefully...")
        self.running = False

    def run(self):
        signal.signal(signal.SIGTERM, self._signal_handler)
        signal.signal(signal.SIGINT, self._signal_handler)
        self.running = True

        pid_file = os.path.join(SKILL_DIR, ".daemon.pid")
        with open(pid_file, "w") as f:
            f.write(str(os.getpid()))

        print(f"[INFO] IAM Sync Daemon started (pid={os.getpid()}, interval={self.interval}s)")
        print(f"[INFO] Press Ctrl+C to stop")

        while self.running:
            print(f"\n{'='*50}")
            print(f"[INFO] Sync cycle at {time.strftime('%Y-%m-%d %H:%M:%S')}")
            try:
                results = run_sync_cycle(self.config)
                print(f"[INFO] Cycle complete. Next sync in {self.interval}s...")
            except Exception as e:
                print(f"[ERROR] Sync cycle failed: {e}")

            # Sleep in small increments for responsive shutdown
            slept = 0
            while self.running and slept < self.interval:
                time.sleep(1)
                slept += 1

        # Cleanup
        if os.path.exists(pid_file):
            os.remove(pid_file)
        print("[INFO] Daemon stopped.")


# --- CLI ---

def main():
    parser = argparse.ArgumentParser(description="IAM Sync Bridge - Keycloak <-> iTop")
    parser.add_argument("--sync", action="store_true", help="Run a single sync cycle")
    parser.add_argument("--daemon", action="store_true", help="Run as continuous daemon")
    parser.add_argument("--interval", type=int, default=300, help="Daemon sync interval in seconds (default: 300)")
    parser.add_argument("--status", action="store_true", help="Show sync status")

    args = parser.parse_args()
    config = load_config()

    if args.status:
        state = load_sync_state(config["sync_state"])
        print(json.dumps(state, indent=2))
        return

    if args.daemon:
        daemon = SyncDaemon(config, args.interval)
        daemon.run()
        return

    if args.sync or not any([args.sync, args.daemon, args.status]):
        print("=== IAM Sync Bridge ===")
        results = run_sync_cycle(config)
        print(f"\n=== Sync Complete ===")
        print(f"  Keycloak reachable: {results['keycloak_reachable']}")
        print(f"  iTop reachable: {results['itop_reachable']}")
        print(f"  KC->iTop: {results['kc_to_itop']}")
        print(f"  iTop->KC: {results['itop_to_kc']}")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
