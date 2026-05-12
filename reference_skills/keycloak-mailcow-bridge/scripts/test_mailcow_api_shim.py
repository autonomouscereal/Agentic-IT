#!/usr/bin/env python3
"""Regression tests for the optional Mailcow HTTP API compatibility shim.

The test never prints the API key. It validates auth handling, read endpoint
shape, selector reads, and optional parity against the live Mailcow database.
"""

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request


FORBIDDEN_MAILBOX_FIELDS = {"password", "password_hash", "passwd", "shadow", "crypt"}


class Results:
    def __init__(self):
        self.passed = 0
        self.failed = 0

    def record(self, name, ok, detail=""):
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {name}" + (f" - {detail}" if detail else ""))
        if ok:
            self.passed += 1
        else:
            self.failed += 1


def request_json(url, key=None, method="GET", timeout=15):
    headers = {"Sec-Fetch-Dest": "script"}
    if key is not None:
        headers["X-API-Key"] = key
    req = urllib.request.Request(url, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8")
        return resp.status, json.loads(body) if body else None


def expect_http_error(url, expected, key=None, method="GET"):
    try:
        request_json(url, key=key, method=method)
        return False, "request succeeded"
    except urllib.error.HTTPError as exc:
        return exc.code == expected, f"HTTP {exc.code}"
    except Exception as exc:
        return False, str(exc)


def first_selector(resource, rows):
    if not rows:
        return ""
    row = rows[0]
    if resource == "domain":
        return row.get("domain", "")
    if resource == "mailbox":
        username = row.get("username", "")
        domain = row.get("domain", "")
        return f"{username}@{domain}" if username and domain else username
    if resource == "alias":
        return row.get("address", "")
    return ""


def mysql_count(table):
    query = f"SELECT COUNT(*) FROM {table}"
    args = [
        "sudo",
        "docker",
        "exec",
        "-e",
        f"SQL_QUERY={query}",
        "mysql-mailcow",
        "sh",
        "-lc",
        'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -N -B -e "$SQL_QUERY" "$MYSQL_DATABASE" 2>/dev/null',
    ]
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "mysql count failed")
    return int(result.stdout.strip())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8081")
    parser.add_argument("--key-file", default="/home/cereal/Mailcow/deploy/api-nginx/.api_key")
    parser.add_argument("--mysql-parity", action="store_true")
    args = parser.parse_args()

    base = args.base.rstrip("/")
    with open(args.key_file, encoding="utf-8") as handle:
        api_key = handle.read().strip()
    if not api_key:
        print("[FAIL] API key file is empty")
        return 1

    results = Results()

    ok, detail = expect_http_error(f"{base}/api/v1/get/domain/all", 401)
    results.record("missing API key rejected", ok, detail)

    ok, detail = expect_http_error(f"{base}/api/v1/get/domain/all", 401, key="invalid")
    results.record("invalid API key rejected", ok, detail)

    resources = {}
    for resource in ("domain", "mailbox", "alias"):
        try:
            status, payload = request_json(f"{base}/api/v1/get/{resource}/all", key=api_key)
            ok = status == 200 and isinstance(payload, list)
            results.record(f"get/{resource}/all returns JSON list", ok, f"count={len(payload) if isinstance(payload, list) else 'not-list'}")
            resources[resource] = payload if isinstance(payload, list) else []
        except Exception as exc:
            results.record(f"get/{resource}/all returns JSON list", False, str(exc))
            resources[resource] = []

    mailbox_fields = set().union(*(set(row) for row in resources.get("mailbox", []))) if resources.get("mailbox") else set()
    leaked = sorted(mailbox_fields.intersection(FORBIDDEN_MAILBOX_FIELDS))
    results.record("mailbox output omits password hashes", not leaked, ",".join(leaked) if leaked else "none")

    for resource, rows in resources.items():
        selector = first_selector(resource, rows)
        if not selector:
            results.record(f"get/{resource}/<selector>", False, "no selector candidate")
            continue
        try:
            status, payload = request_json(f"{base}/api/v1/get/{resource}/{selector}", key=api_key)
            ok = status == 200 and isinstance(payload, list) and len(payload) >= 1
            results.record(f"get/{resource}/<selector>", ok, f"selector={selector} count={len(payload) if isinstance(payload, list) else 'not-list'}")
        except Exception as exc:
            results.record(f"get/{resource}/<selector>", False, str(exc))

    ok, detail = expect_http_error(f"{base}/api/v1/get/domain/all", 405, key=api_key, method="POST")
    results.record("compat endpoint rejects POST", ok, detail)

    if args.mysql_parity:
        table_map = {"domain": "domain", "mailbox": "mailbox", "alias": "alias"}
        for resource, table in table_map.items():
            try:
                expected = mysql_count(table)
                actual = len(resources.get(resource, []))
                results.record(f"{resource} count matches MySQL", actual == expected, f"api={actual} mysql={expected}")
            except Exception as exc:
                results.record(f"{resource} count matches MySQL", False, str(exc))

    print(f"\nSummary: {results.passed} passed, {results.failed} failed")
    return 0 if results.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
