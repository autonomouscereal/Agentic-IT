#!/usr/bin/env python3
"""Debug script to test MySQL connectivity as the deploy script sees it.

Uses the mysql-mailcow container-held environment. Do not pass or print database
passwords from the host.
"""
import os
import subprocess

MYSQL_DATABASE = "mailcow"

args = [
    "sudo",
    "docker",
    "exec",
    "-e",
    "SQL_QUERY=SELECT 1",
    "-e",
    f"SQL_DATABASE={MYSQL_DATABASE}",
    "mysql-mailcow",
    "sh",
    "-lc",
    'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -B -e "$SQL_QUERY" "$SQL_DATABASE" 2>/dev/null',
]
print("Running safe mysql-mailcow connectivity check")
result = subprocess.run(args, capture_output=True, text=True)
print(f"STDOUT: [{result.stdout.strip()}]")
print(f"RC: {result.returncode}")
