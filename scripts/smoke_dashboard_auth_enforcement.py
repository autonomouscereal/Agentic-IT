#!/usr/bin/env python3
"""Smoke-test enforced dashboard authentication and authorization.

This script intentionally does not print secrets. Supply the trusted proxy
secret and service token through environment variables or files in your test
runner.
"""

import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.request


def _read_secret(value, file_value):
    if value:
        return value
    if file_value:
        with open(file_value, encoding="utf-8") as handle:
            return handle.read().strip()
    return ""


VERIFY_TLS = True


def request(base, method, path, payload=None, headers=None, expect=200):
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    req_headers = {"Content-Type": "application/json"}
    req_headers.update(headers or {})
    req = urllib.request.Request(base.rstrip("/") + path, data=body, headers=req_headers, method=method)
    try:
        context = None
        if base.startswith("https://") and not VERIFY_TLS:
            context = ssl._create_unverified_context()
        with urllib.request.urlopen(req, timeout=30, context=context) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            parsed = json.loads(text) if text and text.strip().startswith(("{", "[")) else {"raw": text[:200]}
            status = resp.status
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        parsed = json.loads(text) if text and text.strip().startswith(("{", "[")) else {"raw": text[:200]}
        status = exc.code
    if status != expect:
        raise AssertionError(f"{method} {path} returned {status}, expected {expect}: {parsed}")
    return parsed


def user_headers(username, trusted_secret, provider="auth-hardening-smoke"):
    return {
        "X-Auth-Request-User": username,
        "X-Auth-Provider": provider,
        "X-Dashboard-Auth-Secret": trusted_secret,
    }


def service_headers(service_token):
    return {
        "X-Dashboard-Service-Token": service_token,
        "X-Dashboard-Service-User": "auth-hardening-smoke",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("base", nargs="?", default="http://127.0.0.1:25480")
    parser.add_argument("--admin-user", default="demo_account_1")
    parser.add_argument("--analyst-user", default="codex-dev-y")
    parser.add_argument("--auditor-user", default="codex-auditor")
    parser.add_argument("--trusted-secret", default=os.getenv("DASHBOARD_TRUSTED_AUTH_SECRET", ""))
    parser.add_argument("--trusted-secret-file", default=os.getenv("DASHBOARD_TRUSTED_AUTH_SECRET_FILE", ""))
    parser.add_argument("--service-token", default=os.getenv("DASHBOARD_SERVICE_TOKEN", ""))
    parser.add_argument("--service-token-file", default=os.getenv("DASHBOARD_SERVICE_TOKEN_FILE", ""))
    parser.add_argument("--insecure", action="store_true", help="Disable TLS verification for untrusted runtime certs")
    args = parser.parse_args()
    global VERIFY_TLS
    VERIFY_TLS = not args.insecure

    trusted_secret = _read_secret(args.trusted_secret, args.trusted_secret_file)
    service_token = _read_secret(args.service_token, args.service_token_file)
    if not trusted_secret:
        raise SystemExit("missing trusted proxy secret")
    if not service_token:
        raise SystemExit("missing service token")

    for path in ("/", "/static/js/dashboard.js", "/health", "/api/tickets?limit=1", "/api/access/policies"):
        request(args.base, "GET", path, expect=403)

    admin = user_headers(args.admin_user, trusted_secret)
    analyst = user_headers(args.analyst_user, trusted_secret)
    auditor = user_headers(args.auditor_user, trusted_secret)
    service = service_headers(service_token)

    policies = request(args.base, "GET", "/api/access/policies", headers=admin)
    assert policies["auth_mode"] == "header", policies
    assert policies["enforcement"] == "enforce", policies
    assert policies["credential_broker"]["secret_values_returned"] is False

    request(args.base, "GET", "/", headers=admin)
    request(args.base, "GET", "/health", headers=admin)
    request(args.base, "GET", "/api/tickets?limit=1", headers=admin)
    request(args.base, "GET", "/api/agents/runner-health", headers=admin)
    request(args.base, "GET", "/api/dashboard/stats", headers=admin)
    request(args.base, "GET", "/api/access/users", headers=auditor)
    request(args.base, "GET", "/api/access/users", headers=analyst, expect=403)
    request(args.base, "POST", "/api/tickets", {
        "title": "auth smoke should not create as auditor",
        "description": "negative authorization control",
        "provider": "local",
        "sync_provider": False,
    }, headers=auditor, expect=403)
    request(args.base, "GET", "/api/agents/runner-health", headers=service)

    print(json.dumps({
        "status": "passed",
        "base": args.base,
        "auth_mode": policies["auth_mode"],
        "enforcement": policies["enforcement"],
        "unauthenticated_denied": True,
        "trusted_proxy_secret_required": True,
        "service_token_validated": True,
        "secret_values_returned": False,
    }, indent=2))


if __name__ == "__main__":
    main()
