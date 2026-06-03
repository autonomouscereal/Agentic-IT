#!/usr/bin/env python3
"""Smoke test the Sensitive Intake Broker without printing raw submitted values."""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request


def request(base, method, path, payload=None, token=""):
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"}
    if token:
        headers["X-Dashboard-Service-Token"] = token
    req = urllib.request.Request(base.rstrip("/") + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            raw = res.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise SystemExit(f"{method} {path} failed HTTP {exc.code}: {body}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url", nargs="?", default=os.getenv("DASHBOARD_URL", "http://127.0.0.1:25480"))
    parser.add_argument("--token", default=os.getenv("DASHBOARD_SERVICE_TOKEN", ""))
    args = parser.parse_args()

    marker = f"sensitive-smoke-{int(time.time())}"
    synthetic_ssn = "123-45-6789"
    synthetic_password = "SyntheticSecret123"

    created = request(args.base_url, "POST", "/api/sensitive-intake/request", {
        "purpose": f"{marker} secure onboarding fields",
        "requested_by": "smoke-sensitive-intake",
        "requester_name": "Demo Requester",
        "channel": "smoke",
        "fields": [
            {"key": "ssn", "type": "ssn", "label": "SSN", "required": True},
            {"key": "initial_password", "type": "credential", "label": "Initial password", "required": True},
        ],
        "metadata": {"marker": marker, "raw_values_logged": False},
    }, token=args.token)
    request_ref = created.get("request_ref")
    form_url = created.get("form_url")
    if not request_ref or not form_url:
        raise SystemExit(f"request missing ref/url: {created}")
    token = form_url.rstrip("/").split("/")[-1]

    public_form = request(args.base_url, "GET", f"/api/sensitive-intake/form/{token}")
    if public_form.get("raw_values_returned") is not False:
        raise SystemExit("public form did not explicitly suppress raw values")

    submitted = request(args.base_url, "POST", f"/api/sensitive-intake/submit/{token}", {
        "submitted_by": "smoke-user",
        "values": {
            "ssn": synthetic_ssn,
            "initial_password": synthetic_password,
        },
    })
    detail = request(args.base_url, "GET", f"/api/sensitive-intake/requests/{request_ref}", token=args.token)

    combined = json.dumps({"created": created, "submitted": submitted, "detail": detail}, default=str)
    if synthetic_ssn in combined or synthetic_password in combined:
        raise SystemExit("raw sensitive value leaked into API response")
    if "siv_" not in combined:
        raise SystemExit("no sensitive value reference returned")

    print(json.dumps({
        "status": "passed",
        "marker": marker,
        "request_ref": request_ref,
        "form_url": form_url,
        "submitted_refs": [item.get("value_ref") for item in submitted.get("fields_submitted", [])],
        "raw_values_returned": False,
    }, indent=2))


if __name__ == "__main__":
    main()
