#!/usr/bin/env python3
"""Setup .env file and create Mailcow API key."""
import json
import os
import secrets
import subprocess
import sys

def run_sql(sql):
    """Execute SQL on the mailcow database."""
    mysql_password = os.environ.get("MYSQL_ROOT_PASSWORD", "")
    if not mysql_password:
        print("[ERROR] MYSQL_ROOT_PASSWORD environment variable not set")
        sys.exit(1)
    result = subprocess.run(
        ["docker", "exec", "mysql-mailcow", "mysql", "-uroot", f"-p{mysql_password}",
         "-e", sql, "mailcow"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        print(f"SQL ERROR: {result.stderr}")
        return None
    return result.stdout

# 1. Generate API key
api_key = secrets.token_urlsafe(32)
print(f"Generated API key: {api_key}")

# 2. Insert API key into database
api_data = json.dumps({
    "key": api_key,
    "available_endpoints": ["*"],
    "username": "admin@mailcow.local"
})
# Escape single quotes for SQL
escaped_data = api_data.replace("'", "\\'")
sql = f"INSERT INTO api (data) VALUES ('{escaped_data}')"
result = run_sql(sql)
if result is not None:
    print("[OK] API key inserted into database")
else:
    print("[WARN] Could not insert API key - may already exist")

# 3. Verify API key works
import urllib.request
try:
    req = urllib.request.Request(
        "http://localhost/api/v1/get/info/server",
        headers={"X-API-Key": api_key}
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
        print(f"[OK] API key works! Server info: {data}")
except Exception as e:
    print(f"[WARN] API test: {e}")

# 4. Reset admin password
new_admin_password = secrets.token_urlsafe(24)
print(f"\nGenerated admin password: {new_admin_password}")

# Hash the password with bcrypt (Mailcow uses bcrypt for admin passwords)
import hashlib
# Mailcow uses {BLF-CRYPT} prefix with bcrypt
import crypt
hashed = crypt.crypt(new_admin_password, "$2y$10$" + secrets.token_hex(16)[:22])
hashed_full = f"{{BLF-CRYPT}}{hashed}"
escaped_hash = hashed_full.replace("'", "\\'")
sql2 = f"UPDATE admin SET password='{escaped_hash}' WHERE username='admin@mailcow.local'"
result2 = run_sql(sql2)
if result2 is not None:
    print("[OK] Admin password updated")

# 5. Output .env content
print("\n" + "=" * 60)
print("CREATE THIS .env FILE:")
print("=" * 60)
print(f"""# Keycloak Configuration
KEYCLOAK_URL=http://localhost:8080
KEYCLOAK_ADMIN_USER=admin
KEYCLOAK_ADMIN_PASSWORD=<from vault: keycloak-admin-password>

# Mailcow Configuration
MAILCOW_URL=http://localhost
MAILCOW_API_KEY={api_key}
MAILCOW_ADMIN_USER=admin@mailcow.local
MAILCOW_ADMIN_PASSWORD={new_admin_password}
MAILCOW_DOMAIN=mailcow.local

# Bridge Configuration
BRIDGE_REALM=mailcow
BRIDGE_CLIENT_ID=mailcow-oidc
BRIDGE_CLIENT_SECRET=
SYNC_INTERVAL=300
SYNC_STATE_FILE=.sync_state.json

# Mailcow OIDC Redirect URL
OIDC_REDIRECT_URL=http://localhost

# Keycloak Version
KEYCLOAK_VERSION=26

# Mailpassword Flow
ENABLE_MAILPASSWORD_FLOW=true

# Test Users
TEST_USER_PASSWORD=<from vault: mailcow-test-user-password>""")
