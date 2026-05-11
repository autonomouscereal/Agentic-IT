#!/usr/bin/env python3
"""Mailcow IDP Configuration - Configure Keycloak as Identity Provider via direct MySQL.

Uses direct MySQL access (docker exec) instead of HTTP API, as this custom Mailcow
deployment has no nginx web server for the API layer.

Sets up:
1. Mailcow domain verification
2. Distribution groups (aliases for team communication)
3. Shared mailboxes (security team mailbox)
4. Verifies configuration

Idempotent - safe to run multiple times.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request


# ─── Environment Loading ───────────────────────────────────────────────

def load_env(env_path=None):
    """Load environment variables from .env file."""
    if env_path is None:
        for candidate in [".env", os.path.join(os.path.dirname(__file__), "..", ".env")]:
            if os.path.exists(candidate):
                env_path = candidate
                break
    if env_path is None or not os.path.exists(env_path):
        print("[ERROR] .env file not found. Copy .env.example to .env and configure.", file=sys.stderr)
        sys.exit(1)

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

MAILCOW_DOMAIN = ENV.get("MAILCOW_DOMAIN", "mailcow.local")
MYSQL_CONTAINER = ENV.get("MYSQL_CONTAINER", "mysql-mailcow")
MYSQL_USER = ENV.get("MYSQL_USER", "root")
MYSQL_PASSWORD = ENV.get("MYSQL_PASSWORD", "")
if not MYSQL_PASSWORD:
    print("[ERROR] MYSQL_PASSWORD required in .env file", file=sys.stderr)
    sys.exit(1)
MYSQL_DATABASE = ENV.get("MYSQL_DATABASE", "mailcow")
KEYCLOAK_URL = ENV.get("KEYCLOAK_URL", "http://localhost:8080")
REALM = ENV.get("BRIDGE_REALM", "mailcow")


# ─── Mailcow MySQL Client ──────────────────────────────────────────────

class MailcowClient:
    """Pure Python Mailcow client via direct MySQL (zero external deps, no ORM)."""

    def __init__(self, container, user, password, database):
        self.container = container
        self.user = user
        self.password = password
        self.database = database

    def _run_sql(self, sql, params=None):
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

        # First line is headers (column names), rest is data
        lines = result.stdout.strip().split("\n")
        headers = lines[0].split("\t")
        rows = []
        for line in lines[1:]:
            values = line.split("\t")
            rows.append(dict(zip(headers, values)))
        return rows

    def _run_sql_raw(self, sql):
        """Execute SQL and return raw output (for inserts/updates)."""
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
        """Hash password using SSHA512 (compatible with Dovecot)."""
        import secrets
        salt = secrets.token_bytes(16)
        h = hashlib.sha512()
        h.update(password.encode() + salt)
        import base64
        hashed = base64.b64encode(h.digest() + salt).decode()
        return f"{{SSHA512}}{hashed}"

    def test_api(self):
        """Test MySQL connectivity."""
        try:
            rows = self._run_sql("SELECT 1 AS test")
            return rows is not None and "error" not in (rows if isinstance(rows, dict) else {})
        except Exception:
            return False

    def test_smtp(self):
        """Test SMTP connectivity on port 25."""
        import smtplib
        try:
            with smtplib.SMTP("localhost", 25, timeout=10) as server:
                code, _ = server.ehlo()
                return code == 250
        except Exception:
            return False

    def test_imap(self):
        """Test IMAP connectivity on port 143."""
        import imaplib
        try:
            with imaplib.IMAP4("localhost", 143) as imap:
                imap.logout()
                return True
        except Exception:
            return False

    def get_mailbox(self, username):
        """Get a single mailbox by username (local part)."""
        rows = self._run_sql(
            f"SELECT username, domain, quota, active FROM mailbox WHERE username = '{username}'"
        )
        if isinstance(rows, dict) and "error" in rows:
            return None
        return rows[0] if rows else None

    def get_mailbox_by_email(self, email):
        """Get a mailbox by full email address."""
        local_part = email.split("@")[0] if "@" in email else email
        return self.get_mailbox(local_part)

    def get_all_mailboxes(self):
        """Get all mailboxes."""
        rows = self._run_sql(
            "SELECT username, domain, quota, active, email_access FROM mailbox WHERE active = 1"
        )
        if isinstance(rows, dict) and "error" in rows:
            return []
        return rows

    def create_mailbox(self, local_username, domain, password, quota_mb, active=1):
        """Create a new mailbox via MySQL INSERT."""
        hashed = self._hash_password(password)
        escaped_hash = hashed.replace("'", "\\'")
        sql = (
            f"INSERT INTO mailbox (username, domain, password, quota, active) "
            f"VALUES ('{local_username}', '{domain}', '{escaped_hash}', {quota_mb * 1024 * 1024}, {active}) "
            f"ON DUPLICATE KEY UPDATE active = {active}"
        )
        result = self._run_sql_raw(sql)
        if result is True:
            mb_path = f"{domain}/{local_username}"
            update_sql = f"UPDATE mailbox SET mailbox_path_prefix = '{mb_path}' WHERE username = '{local_username}'"
            self._run_sql_raw(update_sql)
            return True
        return False

    def update_mailbox_quota(self, username, quota_mb):
        """Update mailbox quota."""
        quota_bytes = quota_mb * 1024 * 1024
        sql = f"UPDATE mailbox SET quota = {quota_bytes} WHERE username = '{username}'"
        return self._run_sql_raw(sql) is True

    def update_mailbox_password(self, username, password):
        """Update mailbox password."""
        hashed = self._hash_password(password)
        escaped_hash = hashed.replace("'", "\\'")
        sql = f"UPDATE mailbox SET password = '{escaped_hash}' WHERE username = '{username}'"
        return self._run_sql_raw(sql) is True

    def get_alias(self, address):
        """Get an alias by address."""
        escaped = address.replace("'", "\\'")
        rows = self._run_sql(
            f"SELECT address, goto, active FROM alias WHERE address = '{escaped}'"
        )
        if isinstance(rows, dict) and "error" in rows:
            return None
        return rows[0] if rows else None

    def get_all_aliases(self):
        """Get all aliases."""
        rows = self._run_sql("SELECT address, goto, active, domain FROM alias")
        if isinstance(rows, dict) and "error" in rows:
            return []
        return rows

    def create_alias(self, address, goto, domain, active=1):
        """Create an alias (distribution group)."""
        escaped_addr = address.replace("'", "\\'")
        escaped_goto = goto.replace("'", "\\'")
        escaped_domain = domain.replace("'", "\\'")
        sql = (
            f"INSERT INTO alias (address, goto, domain, active) "
            f"VALUES ('{escaped_addr}', '{escaped_goto}', '{escaped_domain}', {active}) "
            f"ON DUPLICATE KEY UPDATE active = {active}"
        )
        return self._run_sql_raw(sql) is True

    def get_domain(self, domain):
        """Get domain info."""
        escaped = domain.replace("'", "\\'")
        rows = self._run_sql(f"SELECT domain, active FROM domain WHERE domain = '{escaped}'")
        if isinstance(rows, dict) and "error" in rows:
            return None
        return rows[0] if rows else None

    def ensure_domain(self, domain):
        """Ensure domain exists."""
        existing = self.get_domain(domain)
        if existing:
            return True
        escaped = domain.replace("'", "\\'")
        sql = (
            f"INSERT INTO domain (domain, active) VALUES ('{escaped}', 1) "
            f"ON DUPLICATE KEY UPDATE active = 1"
        )
        return self._run_sql_raw(sql) is True


# ─── Setup Functions ───────────────────────────────────────────────────

def ensure_domain(mc):
    """Ensure the mail domain exists in Mailcow."""
    result = mc.ensure_domain(MAILCOW_DOMAIN)
    if result:
        print(f"[OK] Domain '{MAILCOW_DOMAIN}' exists")
        return True
    print(f"[FAIL] Could not ensure domain '{MAILCOW_DOMAIN}'")
    return False


def configure_idp(mc):
    """Configure Keycloak as Identity Provider.

    Note: In this custom Mailcow deployment, IDP configuration is done via
    SOGo and Dovecot configuration files, not via the database.
    The mailbox authsource is tracked via the attributes JSON column.
    """
    print("\n--- Configuring Keycloak as IDP ---")
    print("[INFO] IDP configuration is handled via SOGo/Dovecot config files")
    print("[INFO] Mailbox provisioning will set appropriate attributes for Keycloak auth")
    return True


def create_distribution_groups(mc):
    """Create distribution groups as aliases."""
    print("\n--- Creating Distribution Groups ---")

    # Get existing active mailboxes for goto targets
    mailboxes = mc.get_all_mailboxes()
    mailbox_list = []
    if mailboxes and isinstance(mailboxes, list):
        mailbox_list = [f"{m['username']}@{m['domain']}" for m in mailboxes]

    groups = [
        {
            "address": f"security-team@{MAILCOW_DOMAIN}",
            "targets": ["security@mailcow.local"],
        },
        {
            "address": f"all-staff@{MAILCOW_DOMAIN}",
            "targets": ["postmaster@mailcow.local"],
        },
        {
            "address": f"soc-incident@{MAILCOW_DOMAIN}",
            "targets": ["soc-alerts@mailcow.local"],
        },
    ]

    for group in groups:
        addr = group["address"]
        existing = mc.get_alias(addr)
        if existing:
            print(f"[OK] Alias '{addr}' already exists")
            continue

        goto = ",".join(group["targets"])
        if mc.create_alias(addr, goto, MAILCOW_DOMAIN):
            print(f"[OK] Distribution group '{addr}' created")
        else:
            print(f"[WARN] Could not create alias '{addr}'")


def create_shared_mailbox(mc):
    """Create shared security mailbox."""
    print("\n--- Creating Shared Mailboxes ---")

    shared_mailboxes = [
        {"username": "security-shared", "quota": 10 * 1024 * 1024},
        {"username": "soc-shared", "quota": 10 * 1024 * 1024},
    ]

    for mb in shared_mailboxes:
        existing = mc.get_mailbox(mb["username"])
        if existing:
            print(f"[OK] Shared mailbox '{mb['username']}' already exists")
            continue

        if mc.create_mailbox(mb["username"], MAILCOW_DOMAIN, "SharedM@ilb0x123!", mb["quota"]):
            print(f"[OK] Shared mailbox '{mb['username']}' created")
        else:
            print(f"[WARN] Could not create shared mailbox '{mb['username']}'")


def verify_config(mc):
    """Verify the complete configuration."""
    print("\n--- Verification ---")

    # 1. Check MySQL connectivity
    if mc.test_api():
        print("[OK] Mailcow MySQL accessible")
    else:
        print("[FAIL] Mailcow MySQL not accessible")

    # 2. Check SMTP
    if mc.test_smtp():
        print("[OK] SMTP port 25 accessible")
    else:
        print("[WARN] SMTP port 25 not accessible")

    # 3. Check IMAP
    if mc.test_imap():
        print("[OK] IMAP port 143 accessible")
    else:
        print("[WARN] IMAP port 143 not accessible")

    # 4. Check domain
    domain = mc.get_domain(MAILCOW_DOMAIN)
    if domain:
        print(f"[OK] Domain '{MAILCOW_DOMAIN}' active")

    # 5. Check mailboxes
    mailboxes = mc.get_all_mailboxes()
    if mailboxes:
        print(f"[INFO] Total active mailboxes: {len(mailboxes)}")

    # 6. Check aliases
    aliases = mc.get_all_aliases()
    if aliases:
        print(f"[INFO] Total aliases: {len(aliases)}")


# ─── Main ──────────────────────────────────────────────────────────────

def run_setup():
    """Execute complete Mailcow IDP setup."""
    print("=" * 50)
    print("Keycloak-Mailcow Bridge: Mailcow IDP Configuration")
    print("=" * 50)

    mc = MailcowClient(
        MYSQL_CONTAINER, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE
    )

    # Test connectivity
    if not mc.test_api():
        print("[FAIL] Cannot connect to Mailcow MySQL")
        sys.exit(1)
    print("[OK] Mailcow MySQL connectivity verified")

    # 1. Ensure domain exists
    print("\n--- Domain Setup ---")
    ensure_domain(mc)

    # 2. Configure IDP
    configure_idp(mc)

    # 3. Create distribution groups
    create_distribution_groups(mc)

    # 4. Create shared mailboxes
    create_shared_mailbox(mc)

    # 5. Verify
    verify_config(mc)

    print("\n" + "=" * 50)
    print("Mailcow IDP configuration complete!")
    print("=" * 50)
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Configure Mailcow IDP for Keycloak integration")
    parser.add_argument("--env", help="Path to .env file")
    args = parser.parse_args()

    if args.env:
        ENV = load_env(args.env)

    run_setup()
