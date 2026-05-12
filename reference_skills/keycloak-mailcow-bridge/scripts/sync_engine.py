#!/usr/bin/env python3
"""Bidirectional Sync Engine - Keycloak users <-> Mailcow mailboxes.

Syncs:
1. Keycloak -> Mailcow: Create/update mailboxes for Keycloak users with mailcow_template attribute
2. Mailcow -> Keycloak: Update user attributes based on mailbox changes

Uses direct MySQL for Mailcow communication (HTTP API unavailable in this deployment).
Supports CLI mode (single sync) and daemon mode (continuous polling).
State tracked in .sync_state.json for incremental updates.
"""

import argparse
import base64
import hashlib
import json
import os
import secrets
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone


# --- Environment Loading -----------------------------------------------

def load_env(env_path=None):
    """Load environment variables from .env file."""
    if env_path is None:
        for candidate in [".env", os.path.join(os.path.dirname(__file__), "..", ".env")]:
            if os.path.exists(candidate):
                env_path = candidate
                break
    if env_path is None or not os.path.exists(env_path):
        return {}
    vars = {}
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            vars[k.strip()] = v.strip()
    return vars


ENV = load_env()

KEYCLOAK_URL = ENV.get("KEYCLOAK_URL", "http://localhost:8080")
KEYCLOAK_ADMIN_USER = ENV.get("KEYCLOAK_ADMIN_USER", "admin")
KEYCLOAK_ADMIN_PASSWORD = ENV.get("KEYCLOAK_ADMIN_PASSWORD", "")
REALM = ENV.get("BRIDGE_REALM", "mailcow")
CLIENT_ID = ENV.get("BRIDGE_CLIENT_ID", "mailcow-oidc")
MAILCOW_DOMAIN = ENV.get("MAILCOW_DOMAIN", "mailcow.local")
MYSQL_CONTAINER = ENV.get("MYSQL_CONTAINER", "mysql-mailcow")
MYSQL_USER = ENV.get("MYSQL_USER", "root")
MYSQL_PASSWORD = ENV.get("MYSQL_PASSWORD", "")
MYSQL_DATABASE = ENV.get("MYSQL_DATABASE", "mailcow")
SYNC_STATE_FILE = ENV.get("SYNC_STATE_FILE", ".sync_state.json")
TEST_USER_PASSWORD = ENV.get("TEST_USER_PASSWORD", "")

# Template quota mapping (in MB)
TEMPLATE_QUOTAS = {
    "default": 5120,
    "premium": 25600,
    "admin": 51200,
}


# --- Sync State --------------------------------------------------------

def load_sync_state():
    """Load sync state from file."""
    if os.path.exists(SYNC_STATE_FILE):
        with open(SYNC_STATE_FILE) as f:
            return json.load(f)
    return {
        "last_sync": None,
        "keycloak_users": {},
        "mailcow_mailboxes": {},
        "sync_count": 0,
    }


def save_sync_state(state):
    """Save sync state to file."""
    state["last_sync"] = datetime.now(timezone.utc).isoformat()
    state["sync_count"] = state.get("sync_count", 0) + 1
    with open(SYNC_STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# --- Keycloak API Client ----------------------------------------------

class KeycloakSyncClient:
    """Lightweight Keycloak client for sync operations."""

    def __init__(self, url, admin_user, admin_password):
        self.url = url.rstrip("/")
        self.admin_user = admin_user
        self.admin_password = admin_password
        self.token = None

    def login(self):
        """Authenticate as admin."""
        data = urllib.parse.urlencode({
            "grant_type": "password",
            "username": self.admin_user,
            "password": self.admin_password,
            "client_id": "admin-cli",
        }).encode()
        req = urllib.request.Request(
            f"{self.url}/realms/master/protocol/openid-connect/token",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
                self.token = result["access_token"]
                return True
        except Exception as e:
            print(f"[WARN] Keycloak login failed: {e}")
            return False

    def get_all_users(self, realm):
        """Get all users from realm with attributes."""
        headers = {"Authorization": f"Bearer {self.token}"}
        path = f"{self.url}/admin/realms/{realm}/users?briefRepresentation=false&first=0&max=100"
        try:
            with urllib.request.urlopen(urllib.request.Request(path, headers=headers), timeout=30) as resp:
                return json.loads(resp.read())
        except Exception as e:
            print(f"[WARN] Failed to get users: {e}")
            return []

    def update_user_attribute(self, realm, user_id, attr_name, attr_value):
        """Update a user attribute."""
        headers = {"Authorization": f"Bearer {self.token}", "Content-Type": "application/json"}
        try:
            with urllib.request.urlopen(
                urllib.request.Request(f"{self.url}/admin/realms/{realm}/users/{user_id}", headers=headers),
                timeout=30,
            ) as resp:
                user = json.loads(resp.read())
        except Exception:
            return False

        attrs = user.get("attributes", {})
        attrs[attr_name] = attr_value
        user["attributes"] = attrs

        data = json.dumps(user).encode()
        try:
            with urllib.request.urlopen(
                urllib.request.Request(
                    f"{self.url}/admin/realms/{realm}/users/{user_id}",
                    data=data, headers=headers, method="PUT",
                ),
                timeout=30,
            ) as resp:
                return resp.status == 204
        except Exception:
            return False


# --- Mailcow MySQL Client ---------------------------------------------

class MailcowSyncClient:
    """Lightweight Mailcow client via direct MySQL for sync operations."""

    def __init__(self, container, user, password, database):
        self.container = container
        self.user = user
        self.password = password
        self.database = database

    def _run_sql(self, sql):
        """Execute SQL and return result rows as list of dicts."""
        cmd = [
            "docker", "exec", self.container,
            "mysql", "-u" + self.user, "-p" + self.password,
            "-B", "-e", sql, self.database,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return {"error": result.stderr.strip()[:300]}
        if not result.stdout.strip():
            return []
        lines = result.stdout.strip().split("\n")
        headers = lines[0].split("\t")
        rows = []
        for line in lines[1:]:
            values = line.split("\t")
            rows.append(dict(zip(headers, values)))
        return rows

    def _run_sql_raw(self, sql):
        """Execute SQL without parsing (for inserts/updates)."""
        cmd = [
            "docker", "exec", self.container,
            "mysql", "-u" + self.user, "-p" + self.password,
            "-e", sql, self.database,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return {"error": result.stderr.strip()[:300]}
        return True

    @staticmethod
    def _hash_password(password):
        """Hash password using SSHA512."""
        salt = secrets.token_bytes(16)
        h = hashlib.sha512()
        h.update(password.encode() + salt)
        hashed = base64.b64encode(h.digest() + salt).decode()
        return f"{{SSHA512}}{hashed}"

    def get_all_mailboxes(self):
        """Get all active mailboxes."""
        rows = self._run_sql(
            "SELECT username, domain, quota, active, email_access, attributes FROM mailbox WHERE active = 1"
        )
        if isinstance(rows, dict) and "error" in rows:
            return []
        return rows

    def get_mailbox(self, local_username):
        """Get a single mailbox by local username."""
        escaped = local_username.replace("'", "\\'")
        rows = self._run_sql(
            f"SELECT username, domain, quota, active, attributes FROM mailbox WHERE username = '{escaped}'"
        )
        if isinstance(rows, dict) and "error" in rows:
            return None
        return rows[0] if rows else None

    def create_mailbox(self, email, password, quota_mb, template="default"):
        """Create a mailbox via MySQL INSERT."""
        if "@" in email:
            local_part = email.split("@")[0]
        else:
            local_part = email
        domain = MAILCOW_DOMAIN

        hashed = self._hash_password(password)
        escaped_hash = hashed.replace("'", "\\'")
        quota_bytes = quota_mb * 1024 * 1024
        mb_path = f"{domain}/{local_part}"

        # Store template info in attributes JSON
        attrs = {"mailbox_format": "%d/%u/", "source": "keycloak", "template": template}
        attrs_json = json.dumps(attrs)
        escaped_attrs = attrs_json.replace("'", "\\'")

        sql = (
            f"INSERT INTO mailbox (username, domain, password, quota, active, attributes, mailbox_path_prefix) "
            f"VALUES ('{local_part}', '{domain}', '{escaped_hash}', {quota_bytes}, 1, '{escaped_attrs}', '{mb_path}') "
            f"ON DUPLICATE KEY UPDATE password = '{escaped_hash}', quota = {quota_bytes}, active = 1"
        )
        return self._run_sql_raw(sql) is True

    def update_quota(self, username, quota_mb):
        """Update mailbox quota."""
        quota_bytes = quota_mb * 1024 * 1024
        escaped = username.replace("'", "\\'")
        sql = f"UPDATE mailbox SET quota = {quota_bytes} WHERE username = '{escaped}'"
        return self._run_sql_raw(sql) is True

    def update_mailbox_password(self, username, password):
        """Update mailbox password."""
        hashed = self._hash_password(password)
        escaped_hash = hashed.replace("'", "\\'")
        escaped_user = username.replace("'", "\\'")
        sql = f"UPDATE mailbox SET password = '{escaped_hash}' WHERE username = '{escaped_user}'"
        return self._run_sql_raw(sql) is True


# --- Sync Logic --------------------------------------------------------

def sync_keycloak_to_mailcow(kc, mc, state):
    """Sync Keycloak users to Mailcow mailboxes."""
    print("\n--- Syncing Keycloak -> Mailcow ---")

    users = kc.get_all_users(REALM)
    if not users:
        print("[WARN] No users retrieved from Keycloak")
        return 0

    created = 0
    updated = 0
    kc_state = state.get("keycloak_users", {})

    for user in users:
        username = user.get("username", "")
        email = user.get("email", "")
        attrs = user.get("attributes", {})
        template_val = attrs.get("mailcow_template", ["default"])
        template = template_val[0] if isinstance(template_val, list) else template_val

        if not email:
            email = f"{username}@{MAILCOW_DOMAIN}"

        mailbox_addr = email.split("@")[0] if "@" in email else username

        # Check if already synced
        prev = kc_state.get(username, {})
        if prev.get("email") == email and prev.get("template") == template and prev.get("synced"):
            continue

        # Check if mailbox exists
        existing_mb = mc.get_mailbox(mailbox_addr)

        if existing_mb:
            # Update quota based on template
            quota = TEMPLATE_QUOTAS.get(template, TEMPLATE_QUOTAS["default"])
            existing_quota_mb = int(existing_mb.get("quota", 0)) // (1024 * 1024)
            if existing_quota_mb != quota:
                if mc.update_quota(mailbox_addr, quota):
                    print(f"[OK] Updated quota for {mailbox_addr} -> {quota}MB")
                    updated += 1
        else:
            # Create mailbox
            password = f"AutoGen_{username}_{int(time.time())}"
            quota = TEMPLATE_QUOTAS.get(template, TEMPLATE_QUOTAS["default"])
            if mc.create_mailbox(email, password, quota, template):
                print(f"[OK] Created mailbox {email} (template={template})")
                created += 1

        # Update state
        kc_state[username] = {
            "email": email,
            "template": template,
            "synced": True,
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }

    state["keycloak_users"] = kc_state
    print(f"[INFO] Keycloak -> Mailcow: created={created}, updated={updated}")
    return created + updated


def sync_mailcow_to_keycloak(kc, mc, state):
    """Sync Mailcow mailbox changes back to Keycloak (template updates)."""
    print("\n--- Syncing Mailcow -> Keycloak ---")

    mailboxes = mc.get_all_mailboxes()
    if not mailboxes:
        print("[WARN] No mailboxes retrieved from Mailcow")
        return 0

    updated = 0
    kc_state = state.get("keycloak_users", {})

    for mb in mailboxes:
        username = mb.get("username", "")
        if not username:
            continue

        # Check if this mailbox was provisioned from Keycloak
        attrs_str = mb.get("attributes", "{}")
        try:
            mb_attrs = json.loads(attrs_str) if attrs_str else {}
        except (json.JSONDecodeError, TypeError):
            mb_attrs = {}

        if mb_attrs.get("source") != "keycloak":
            continue

        # Find corresponding Keycloak user
        users = kc.get_all_users(REALM)
        kc_user = None
        for u in users:
            if u.get("username") == username:
                kc_user = u
                break

        if kc_user:
            quota_mb = int(mb.get("quota", 5242880)) // (1024 * 1024)
            template = "default"
            for tmpl, q in TEMPLATE_QUOTAS.items():
                if q == quota_mb:
                    template = tmpl
                    break

            user_attrs = kc_user.get("attributes", {})
            current_template = user_attrs.get("mailcow_template", "default")
            if isinstance(current_template, list):
                current_template = current_template[0]

            if current_template != template:
                if kc.update_user_attribute(REALM, kc_user["id"], "mailcow_template", template):
                    print(f"[OK] Updated template for {username} -> {template}")
                    updated += 1

    print(f"[INFO] Mailcow -> Keycloak: updated={updated}")
    return updated


# --- Main --------------------------------------------------------------

running = True


def signal_handler(sig, frame):
    """Handle shutdown signals."""
    global running
    running = False
    print("\n[INFO] Shutdown signal received. Saving state...")


def run_sync():
    """Run a single sync cycle."""
    if not KEYCLOAK_ADMIN_PASSWORD:
        print("[ERROR] KEYCLOAK_ADMIN_PASSWORD required in .env", file=sys.stderr)
        return False
    if not MYSQL_PASSWORD:
        print("[ERROR] MYSQL_PASSWORD required in .env", file=sys.stderr)
        return False

    state = load_sync_state()

    # Keycloak client
    kc = KeycloakSyncClient(KEYCLOAK_URL, KEYCLOAK_ADMIN_USER, KEYCLOAK_ADMIN_PASSWORD)
    if not kc.login():
        print("[WARN] Cannot connect to Keycloak - skipping Keycloak-side sync")
        return False

    # Mailcow MySQL client
    mc = MailcowSyncClient(MYSQL_CONTAINER, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE)

    # Sync Keycloak -> Mailcow
    sync_keycloak_to_mailcow(kc, mc, state)

    # Sync Mailcow -> Keycloak
    sync_mailcow_to_keycloak(kc, mc, state)

    # Save state
    save_sync_state(state)

    return True


def run_daemon(interval):
    """Run continuous sync daemon."""
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    print(f"[INFO] Sync daemon started (interval={interval}s)")
    print(f"[INFO] Press Ctrl+C to stop")

    while running:
        try:
            print(f"\n{'=' * 40}")
            print(f"[INFO] Sync cycle at {datetime.now(timezone.utc).isoformat()}")
            run_sync()
        except Exception as e:
            print(f"[ERROR] Sync cycle failed: {e}")

        for _ in range(interval):
            if not running:
                break
            time.sleep(1)

    state = load_sync_state()
    save_sync_state(state)
    print("[INFO] Sync daemon stopped. State saved.")


def show_status():
    """Show sync status."""
    state = load_sync_state()
    print("=== Sync Status ===")
    print(f"Last sync: {state.get('last_sync', 'never')}")
    print(f"Sync count: {state.get('sync_count', 0)}")
    print(f"Keycloak users synced: {len(state.get('keycloak_users', {}))}")
    print(f"Mailcow mailboxes tracked: {len(state.get('mailcow_mailboxes', {}))}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Bidirectional sync engine for Keycloak-Mailcow bridge")
    parser.add_argument("--sync", action="store_true", help="Run a single sync cycle")
    parser.add_argument("--daemon", action="store_true", help="Run as continuous daemon")
    parser.add_argument("--status", action="store_true", help="Show sync status")
    parser.add_argument("--interval", type=int, default=300, help="Daemon sync interval in seconds (default: 300)")
    parser.add_argument("--env", help="Path to .env file")
    args = parser.parse_args()

    if args.env:
        ENV = load_env(args.env)

    if args.status:
        show_status()
    elif args.daemon:
        run_daemon(args.interval)
    elif args.sync:
        run_sync()
    else:
        run_sync()
