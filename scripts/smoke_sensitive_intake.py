#!/usr/bin/env python3
"""Smoke test the Sensitive Intake Broker without printing raw submitted values."""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request


def request(base, method, path, payload=None, token="", expect_error=False):
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
        if expect_error:
            try:
                parsed = json.loads(body)
            except Exception:
                parsed = {"raw": body}
            return {"http_status": exc.code, **parsed}
        raise SystemExit(f"{method} {path} failed HTTP {exc.code}: {body}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("base_url", nargs="?", default=os.getenv("DASHBOARD_URL", "http://127.0.0.1:25480"))
    parser.add_argument("--token", default=os.getenv("DASHBOARD_SERVICE_TOKEN", ""))
    args = parser.parse_args()

    marker = f"sensitive-smoke-{int(time.time())}"
    synthetic_ssn = "123-45-6789"
    synthetic_password = "SyntheticSecret123"
    synthetic_token = "sk-or-v1-abc123456789abc123"
    synthetic_card = "4111 1111 1111 1111"
    leak_values = [synthetic_ssn, synthetic_password, synthetic_token, synthetic_card]

    created = request(args.base_url, "POST", "/api/sensitive-intake/request", {
        "purpose": f"{marker} secure onboarding fields; never store {synthetic_ssn}",
        "requested_by": "smoke-sensitive-intake",
        "requester_name": "Demo Requester",
        "channel": "smoke",
        "fields": [
            {"key": "legal_name", "type": "freeform_sensitive", "label": "Full legal name", "required": True},
            {"key": "dob", "type": "dob", "label": "Date of birth", "required": True},
            {"key": "ssn", "type": "ssn", "label": "SSN", "required": True},
            {"key": "initial_password", "type": "credential", "label": "Initial password", "required": True},
            {"key": "api_token", "type": "token", "label": "API token", "required": False},
            {"key": "payment_card", "type": "financial", "label": "Payment card", "required": False},
        ],
        "metadata": {"marker": marker, "raw_values_logged": False, "redaction_probe": f"token: {synthetic_token}"},
    }, token=args.token)
    request_ref = created.get("request_ref")
    form_url = created.get("form_url")
    if not request_ref or not form_url:
        raise SystemExit(f"request missing ref/url: {created}")
    token = form_url.rstrip("/").split("/")[-1]

    public_form = request(args.base_url, "GET", f"/api/sensitive-intake/form/{token}")
    if public_form.get("raw_values_returned") is not False:
        raise SystemExit("public form did not explicitly suppress raw values")
    first_combined = json.dumps({"created": created, "public_form": public_form}, default=str)
    for value in leak_values:
        if value in first_combined:
            raise SystemExit("raw sensitive value leaked into request/form metadata")

    missing_submit = request(args.base_url, "POST", f"/api/sensitive-intake/submit/{token}", {
        "submitted_by": "smoke-user",
        "values": {
            "legal_name": "Synthetic Person",
            "ssn": synthetic_ssn,
        },
    }, expect_error=True)
    if missing_submit.get("http_status") != 400 or "missing_required_fields" not in json.dumps(missing_submit):
        raise SystemExit(f"missing required fields did not fail closed: {missing_submit}")

    submitted = request(args.base_url, "POST", f"/api/sensitive-intake/submit/{token}", {
        "submitted_by": "smoke-user",
        "values": {
            "legal_name": "Synthetic Person",
            "dob": "01/01/1990",
            "ssn": synthetic_ssn,
            "initial_password": synthetic_password,
            "api_token": synthetic_token,
            "payment_card": synthetic_card,
        },
    })
    second_submit = request(args.base_url, "POST", f"/api/sensitive-intake/submit/{token}", {
        "submitted_by": "smoke-user",
        "values": {
            "legal_name": "Replacement Person",
            "dob": "02/02/1991",
            "ssn": "987-65-4321",
            "initial_password": "ReplacementSecret123",
        },
    }, expect_error=True)
    if second_submit.get("http_status") != 400 or "form_not_accepting_submissions" not in json.dumps(second_submit):
        raise SystemExit(f"submitted form accepted a second submission: {second_submit}")
    detail = request(args.base_url, "GET", f"/api/sensitive-intake/requests/{request_ref}", token=args.token)

    combined = json.dumps({"created": created, "submitted": submitted, "detail": detail}, default=str)
    for value in leak_values + ["987-65-4321", "ReplacementSecret123"]:
        if value in combined:
            raise SystemExit("raw sensitive value leaked into API response")
    if "siv_" not in combined:
        raise SystemExit("no sensitive value reference returned")
    events = [item.get("event_type") or item.get("action") for item in detail.get("events", [])]
    for expected in ("sensitive_form_requested", "sensitive_form_submit_rejected", "sensitive_form_submitted"):
        if expected not in events:
            raise SystemExit(f"missing audit event {expected}: {events}")

    print(json.dumps({
        "status": "passed",
        "marker": marker,
        "request_ref": request_ref,
        "form_url": form_url,
        "submitted_refs": [item.get("value_ref") for item in submitted.get("fields_submitted", [])],
        "events": events,
        "second_submit_blocked": True,
        "raw_values_returned": False,
    }, indent=2))


if __name__ == "__main__":
    main()
