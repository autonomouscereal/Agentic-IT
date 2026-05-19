#!/usr/bin/env python3
"""Shared auth helpers for dashboard smoke and agentic proof scripts."""
import os


def dashboard_auth_headers(user=None, provider=None, content_type=True):
    """Build dashboard auth headers from env without printing secrets."""
    headers = {}
    if content_type:
        headers["Content-Type"] = "application/json"

    trusted_secret = os.getenv("DASHBOARD_TRUSTED_AUTH_SECRET", "")
    service_token = os.getenv("DASHBOARD_SERVICE_TOKEN", "")
    final_user = user or os.getenv("DASHBOARD_SMOKE_USER", "demo_account_1")
    final_provider = provider or os.getenv("DASHBOARD_SMOKE_PROVIDER", "script-proof")

    if trusted_secret:
        headers["X-Auth-Request-User"] = final_user
        headers["X-Auth-Provider"] = final_provider
        headers["X-Dashboard-Auth-Secret"] = trusted_secret
    elif service_token:
        headers["X-Dashboard-Service-User"] = final_provider
        headers["X-Dashboard-Service-Token"] = service_token

    return headers
