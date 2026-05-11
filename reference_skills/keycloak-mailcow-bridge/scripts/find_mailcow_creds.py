#!/usr/bin/env python3
"""Find Mailcow credentials and test API connectivity."""
import json
import os
import secrets
import subprocess
import sys
import urllib.error
import urllib.request

base_url = "http://localhost"
mysql_root_password = os.environ.get("MYSQL_ROOT_PASSWORD", "")
if not mysql_root_password:
    print("[ERROR] MYSQL_ROOT_PASSWORD environment variable not set")
    sys.exit(1)

# Test 1: API info without auth
print("--- API Connectivity Tests ---")
try:
    req = urllib.request.Request(f"{base_url}/api/v1/get/info/server")
    with urllib.request.urlopen(req, timeout=10) as resp:
        print(f"No auth: {resp.status}")
except urllib.error.HTTPError as e:
    body = e.read().decode(errors="replace") if e.fp else ""
    print(f"No auth: HTTP {e.code} - {body[:200]}")
except Exception as e:
    print(f"No auth: {e}")

# Test 2: API with random key
api_key = secrets.token_urlsafe(32)
try:
    req = urllib.request.Request(f"{base_url}/api/v1/get/info/server",
        headers={"X-API-Key": api_key})
    with urllib.request.urlopen(req, timeout=10) as resp:
        print(f"Random key: {resp.status}")
except urllib.error.HTTPError as e:
    body = e.read().decode(errors="replace") if e.fp else ""
    print(f"Random key: HTTP {e.code} - {body[:200]}")
except Exception as e:
    print(f"Random key: {e}")

# Test 3: Find admin mailbox in MySQL
print("\n--- MySQL Admin Mailbox ---")
result = subprocess.run(
    ["docker", "exec", "mysql-mailcow", "mysql", "-uroot", f"-p{mysql_root_password}",
     "-e", "SELECT username, email, active FROM mailbox WHERE admin=1 LIMIT 3",
     "mailcow_dockerized"],
    capture_output=True, text=True
)
print(f"Admin mailboxes:\n{result.stdout[:500]}")
if result.stderr:
    print(f"MySQL stderr: {result.stderr[:200]}")

# Test 4: Show all tables
print("\n--- Database Tables ---")
result2 = subprocess.run(
    ["docker", "exec", "mysql-mailcow", "mysql", "-uroot", f"-p{mysql_root_password}",
     "-e", "SHOW TABLES",
     "mailcow_dockerized"],
    capture_output=True, text=True
)
print(result2.stdout[:1000])

# Test 5: Check if API key table exists and has data
print("\n--- API Key Table ---")
for table_name in ["mailcow_api_keys", "api_keys", "apikey"]:
    result3 = subprocess.run(
        ["docker", "exec", "mysql-mailcow", "mysql", "-uroot", f"-p{mysql_root_password}",
         "-e", f"SELECT * FROM {table_name} LIMIT 3",
         "mailcow_dockerized"],
        capture_output=True, text=True
    )
    if "No such table" not in result3.stderr:
        print(f"Table {table_name}: {result3.stdout[:300]}")
    else:
        print(f"Table {table_name}: not found")
