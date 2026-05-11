#!/usr/bin/env python3
"""Debug script to test MySQL connectivity as the deploy script sees it."""
import os, subprocess

MYSQL_ROOT_PASSWORD = os.environ.get("MYSQL_ROOT_PASSWORD", "")
MYSQL_DATABASE = "mailcow"

print(f"PWD length: {len(MYSQL_ROOT_PASSWORD)}")
print(f"PWD first 5: {MYSQL_ROOT_PASSWORD[:5]}...")

# Test 1: Direct command
cmd1 = f"sudo docker exec mysql-mailcow mysql -uroot -p{MYSQL_ROOT_PASSWORD} -e 'SELECT 1' {MYSQL_DATABASE} 2>&1"
print(f"\nCMD1: {cmd1}")
r1 = subprocess.run(cmd1, shell=True, capture_output=True, text=True)
print(f"STDOUT: [{r1.stdout.strip()}]")
print(f"STDERR: [{r1.stderr.strip()[:200]}]")
print(f"RC: {r1.returncode}")

# Test 2: The exact check from deploy script
cmd2 = f"sudo docker exec mysql-mailcow mysql -uroot -p{MYSQL_ROOT_PASSWORD} -e 'SELECT 1' {MYSQL_DATABASE} 2>/dev/null && echo 'OK'"
print(f"\nCMD2: {cmd2}")
r2 = subprocess.run(cmd2, shell=True, capture_output=True, text=True)
wc = r2.stdout.strip()
print(f"STDOUT: [{wc}]")
print(f"RC: {r2.returncode}")
print(f"wc == 'OK': {wc == 'OK'}")

# Test 3: Without 2>/dev/null
cmd3 = f"sudo docker exec mysql-mailcow mysql -uroot -p{MYSQL_ROOT_PASSWORD} -B -e 'SELECT 1' {MYSQL_DATABASE} && echo 'OK'"
print(f"\nCMD3: {cmd3}")
r3 = subprocess.run(cmd3, shell=True, capture_output=True, text=True)
wc3 = r3.stdout.strip()
print(f"STDOUT: [{wc3}]")
print(f"STDERR: [{r3.stderr.strip()[:200]}]")
print(f"RC: {r3.returncode}")
