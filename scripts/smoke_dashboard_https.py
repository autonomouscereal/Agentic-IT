#!/usr/bin/env python3
"""Smoke-test the dashboard HTTPS edge with verification disabled for bootstrap."""
import argparse
import json
import ssl
import urllib.error
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request(base, path, expect):
    ctx = ssl._create_unverified_context()
    req = urllib.request.Request(base.rstrip("/") + path, headers={"Accept": "text/html"})
    opener = urllib.request.build_opener(NoRedirect, urllib.request.HTTPSHandler(context=ctx))
    try:
        with opener.open(req, timeout=30) as response:
            body = response.read().decode("utf-8", errors="replace")
            status = response.status
            headers = dict(response.headers.items())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        status = exc.code
        headers = dict(exc.headers.items())
    if status != expect:
        raise AssertionError(f"{path} returned {status}, expected {expect}: {body[:300]}")
    return {"status": status, "body": body, "headers": headers}


def header_value(headers, name):
    lowered = name.lower()
    for key, value in (headers or {}).items():
        if key.lower() == lowered:
            return value
    return ""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("base", nargs="?", default="https://127.0.0.1:25443")
    args = parser.parse_args()

    edge = request(args.base, "/nginx-health", 200)
    login = request(args.base, "/", 303)
    location = header_value(login["headers"], "Location")
    if not location.startswith("/login"):
        raise AssertionError(f"expected login redirect, got {location}")
    hsts = header_value(login["headers"], "Strict-Transport-Security")
    if "max-age=" not in hsts:
        raise AssertionError("missing HSTS header")
    x_frame_options = header_value(login["headers"], "X-Frame-Options")
    if x_frame_options != "DENY":
        raise AssertionError("missing X-Frame-Options DENY")
    print(json.dumps({
        "status": "passed",
        "base": args.base,
        "edge_health": edge["status"],
        "login_redirect": location,
        "hsts": bool(hsts),
        "x_frame_options": x_frame_options,
    }, indent=2))


if __name__ == "__main__":
    main()
