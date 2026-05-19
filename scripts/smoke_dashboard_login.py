#!/usr/bin/env python3
"""Smoke-test first-party dashboard login without printing credentials."""
import argparse
import http.cookiejar
import json
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(opener, base, method, path, payload=None, headers=None, expect=200):
    data = None
    final_headers = dict(headers or {})
    if payload is not None:
        if final_headers.get("Content-Type") == "application/x-www-form-urlencoded":
            data = urllib.parse.urlencode(payload).encode("utf-8")
        else:
            final_headers.setdefault("Content-Type", "application/json")
            data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(base.rstrip("/") + path, data=data, headers=final_headers, method=method)
    try:
        with opener.open(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            status = resp.status
            location = resp.headers.get("Location")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        status = exc.code
        location = exc.headers.get("Location")
    if status != expect:
        raise AssertionError(f"{method} {path} returned {status}, expected {expect}: {body[:300]}")
    return {"status": status, "body": body, "location": location}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("base", nargs="?", default="http://127.0.0.1:25480")
    parser.add_argument("--username", default=os.getenv("DASHBOARD_LOGIN_USER", "demo_account_1"))
    parser.add_argument("--password", default=os.getenv("DASHBOARD_LOGIN_PASSWORD", ""))
    parser.add_argument("--password-file", default=os.getenv("DASHBOARD_LOGIN_PASSWORD_FILE", ""))
    parser.add_argument("--insecure", action="store_true", help="Disable TLS verification for untrusted runtime certs")
    args = parser.parse_args()

    password = args.password
    if not password and args.password_file:
        with open(args.password_file, encoding="utf-8") as handle:
            password = handle.read().strip()
    if not password:
        raise SystemExit("missing password")

    handlers = [NoRedirect, urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar())]
    if args.insecure:
        handlers.append(urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))
    no_redirect = urllib.request.build_opener(*handlers)
    root = request(no_redirect, args.base, "GET", "/", headers={"Accept": "text/html"}, expect=303)
    assert root["location"].startswith("/login"), root

    bad = request(no_redirect, args.base, "POST", "/api/auth/login", {
        "username": args.username,
        "password": "definitely-not-the-password",
        "next": "/",
    }, {"Content-Type": "application/x-www-form-urlencoded", "Accept": "text/html"}, expect=303)
    assert bad["location"].startswith("/login?error=1"), bad

    jar = http.cookiejar.CookieJar()
    handlers = [NoRedirect, urllib.request.HTTPCookieProcessor(jar)]
    if args.insecure:
        handlers.append(urllib.request.HTTPSHandler(context=ssl._create_unverified_context()))
    opener = urllib.request.build_opener(*handlers)
    good = request(opener, args.base, "POST", "/api/auth/login", {
        "username": args.username,
        "password": password,
        "next": "/",
    }, {"Content-Type": "application/x-www-form-urlencoded", "Accept": "text/html"}, expect=303)
    assert good["location"] == "/", good
    assert any(cookie.name == "dashboard_session" for cookie in jar), "missing dashboard_session cookie"

    me = request(opener, args.base, "GET", "/api/access/me", headers={"Accept": "application/json"}, expect=200)
    parsed = json.loads(me["body"])
    assert parsed["identity"]["username"] == args.username, parsed
    print(json.dumps({
        "status": "passed",
        "base": args.base,
        "username": args.username,
        "unauthenticated_redirect": root["location"],
        "bad_credentials_redirect": bad["location"],
        "session_cookie": True,
        "roles": parsed.get("roles", []),
    }, indent=2))


if __name__ == "__main__":
    main()
