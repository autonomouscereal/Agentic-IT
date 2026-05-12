#!/usr/bin/env python3
"""
Wazuh Sync Bridge - Unidirectional sync Keycloak → Wazuh.
Modes: CLI (one-shot sync) or Daemon (continuous polling).
Graceful degradation: if either service is down, skip and continue.
Zero hardcoded secrets. All credentials from .env or environment.
"""

import argparse
import json
import os
import secrets
import signal
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

ROLE_MAP = {
    "wazuh-administrator": "administrator",
    "wazuh-security-analyst": "readonly",
    "wazuh-agent-admin": "agents_admin",
    "wazuh-cluster-admin": "cluster_admin",
    "wazuh-user-admin": "users_admin",
}


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
        "sync_state": os.environ.get("SYNC_STATE_FILE", os.path.join(SKILL_DIR, ".sync_state.json")),
        "sync_interval": int(os.environ.get("SYNC_INTERVAL", "300")),
    }


# --- Sync State ---

def load_sync_state(path):
    if os.path.exists(path):
        try:
            with open(path, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"synced_users": {}, "last_sync": None}


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
        parsed = urllib.parse.urlparse(base_url)
        mgmt_url = f"{parsed.scheme}://{parsed.hostname}:9000"
        req = urllib.request.Request(f"{mgmt_url}/health")
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=10) as resp:
            return resp.code == 200
    except Exception:
        return False


def kc_list_users(token, base_url, realm):
    code, result = kc_api_call("GET", f"/admin/realms/{realm}/users?max=100", base_url, token)
    return result if code == 200 and result else []


def kc_get_user_groups(token, base_url, realm, user_id):
    code, result = kc_api_call("GET", f"/admin/realms/{realm}/users/{user_id}/groups", base_url, token)
    return result if code == 200 and result else []


# --- Wazuh API ---

class WazuhClient:
    def __init__(self, base_url, username, password):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self._token = None

    def authenticate(self):
        url = f"{self.base_url}/security/user/authenticate?raw=true"
        creds = f"{self.username}:{self.password}"
        token_b64 = base64.b64encode(creds.encode()).decode()
        req = urllib.request.Request(url, method="GET",
                                    headers={"Authorization": f"Basic {token_b64}"})
        try:
            with urllib.request.urlopen(req, context=SSL_CTX, timeout=30) as resp:
                self._token = resp.read().decode("utf-8").strip()
                return self._token
        except Exception:
            return None

    def api_call(self, method, endpoint, data=None):
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
        result = self.api_call("GET", "/security/users")
        if "data" in result:
            return result["data"].get("affected_items", [])
        return []

    def create_user(self, username, password):
        return self.api_call("POST", "/security/users", {"username": username, "password": password})

    def change_password(self, user_id, password):
        return self.api_call("PUT", f"/security/users/{user_id}/password", {"password": password})

    def is_reachable(self):
        result = self.api_call("GET", "/manager/status")
        return result.get("error", 1) == 0


def wazuh_get_user_by_name(wazuh_client, username):
    users = wazuh_client.list_users()
    for u in users:
        if u.get("username") == username:
            return u
    return None


# --- Sync Logic ---

def sync_keycloak_to_wazuh(config, kc_token, wazuh_client, sync_state):
    """Sync users from Keycloak wazuh realm to Wazuh API users."""
    realm = config["bridge_realm"]
    synced = 0
    updated = 0
    errors = 0

    kc_users = kc_list_users(kc_token, config["keycloak_url"], realm)
    wazuh_users = wazuh_client.list_users()
    existing_wazuh = {u.get("username"): u for u in wazuh_users}

    active_usernames = set()
    for user in kc_users:
        username = user.get("username", "")
        if not username or username.startswith("bridge_test_"):
            continue

        active_usernames.add(username)
        user_key = user.get("id", "")
        prev_id = sync_state["synced_users"].get(username)

        if prev_id == user_key:
            updated += 1
            continue

        if username in existing_wazuh:
            updated += 1
        else:
            password = secrets.token_urlsafe(24)
            result = wazuh_client.create_user(username, password)
            if "data" in result:
                synced += 1
                print(f"  [OK] Created Wazuh user '{username}'")
            else:
                errors += 1
                print(f"  [FAIL] Create '{username}': {result.get('error', 'unknown')}")

        sync_state["synced_users"][username] = user_key
        save_sync_state(config["sync_state"], sync_state)

    # Disable Wazuh users no longer in Keycloak
    for wazuh_name in list(existing_wazuh.keys()):
        if wazuh_name not in active_usernames and not wazuh_name.startswith("bridge_test_"):
            wazuh_user = existing_wazuh[wazuh_name]
            uid = wazuh_user.get("id")
            if uid:
                random_pw = secrets.token_urlsafe(32)
                result = wazuh_client.change_password(uid, random_pw)
                if "data" in result:
                    print(f"  [OK] Disabled Wazuh user '{wazuh_name}' (removed from Keycloak)")
                    if wazuh_name in sync_state["synced_users"]:
                        del sync_state["synced_users"][wazuh_name]
                        save_sync_state(config["sync_state"], sync_state)

    return synced, updated, errors


def run_sync_cycle(config):
    """Run a single sync cycle with graceful degradation."""
    results = {
        "keycloak_reachable": False,
        "wazuh_reachable": False,
        "kc_to_wazuh": {"synced": 0, "updated": 0, "errors": 0, "status": "skipped"},
    }

    if kc_is_reachable(config["keycloak_url"]):
        results["keycloak_reachable"] = True
        print("[OK] Keycloak is reachable")
    else:
        print("[WARN] Keycloak unreachable — skipping sync")
        return results

    wazuh_client = WazuhClient(config["wazuh_url"], config["wazuh_username"], config["wazuh_password"])
    if wazuh_client.is_reachable():
        results["wazuh_reachable"] = True
        print("[OK] Wazuh is reachable")
    else:
        print("[WARN] Wazuh unreachable — skipping sync")
        return results

    kc_token = kc_get_token(config["keycloak_url"], config["keycloak_admin"], config["keycloak_password"])
    if not kc_token:
        print("[ERROR] Cannot authenticate to Keycloak")
        return results

    if not wazuh_client.authenticate():
        print("[ERROR] Cannot authenticate to Wazuh")
        return results

    sync_state = load_sync_state(config["sync_state"])
    print("\n--- Syncing Keycloak → Wazuh ---")
    synced, updated, errors = sync_keycloak_to_wazuh(config, kc_token, wazuh_client, sync_state)
    results["kc_to_wazuh"] = {"synced": synced, "updated": updated, "errors": errors, "status": "completed"}
    print(f"  New: {synced}, Updated: {updated}, Errors: {errors}")
    save_sync_state(config["sync_state"], sync_state)

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

        print(f"[INFO] Wazuh Sync Daemon started (pid={os.getpid()}, interval={self.interval}s)")
        print(f"[INFO] Press Ctrl+C to stop")

        while self.running:
            print(f"\n{'='*50}")
            print(f"[INFO] Sync cycle at {time.strftime('%Y-%m-%d %H:%M:%S')}")
            try:
                run_sync_cycle(self.config)
            except Exception as e:
                print(f"[ERROR] Sync cycle failed: {e}")

            slept = 0
            while self.running and slept < self.interval:
                time.sleep(1)
                slept += 1

        if os.path.exists(pid_file):
            os.remove(pid_file)
        print("[INFO] Daemon stopped.")


# --- CLI ---

def main():
    parser = argparse.ArgumentParser(description="Wazuh Sync Bridge - Keycloak → Wazuh")
    parser.add_argument("--sync", action="store_true", help="Run a single sync cycle")
    parser.add_argument("--daemon", action="store_true", help="Run as continuous daemon")
    parser.add_argument("--interval", type=int, default=300, help="Daemon sync interval (default: 300s)")
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
        print("=== Wazuh Sync Bridge ===")
        results = run_sync_cycle(config)
        print(f"\n=== Sync Complete ===")
        print(f"  Keycloak reachable: {results['keycloak_reachable']}")
        print(f"  Wazuh reachable: {results['wazuh_reachable']}")
        print(f"  KC→Wazuh: {results['kc_to_wazuh']}")
        return

    parser.print_help()


if __name__ == "__main__":
    main()
