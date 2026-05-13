#!/usr/bin/env python3
"""Emit compact SIEM ticket bridge health JSON for audits and monitors."""

import json
import os
from pathlib import Path
from datetime import datetime, timezone


def size(path):
    try:
        return Path(path).stat().st_size
    except OSError:
        return 0


def load_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def age_seconds(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return max(0, int((datetime.now(timezone.utc) - parsed).total_seconds()))
    except ValueError:
        return None


state_file = os.getenv("BRIDGE_STATE_FILE", "/var/lib/siem-ticket-bridge/state.json")
log_file = os.getenv("BRIDGE_LOG_FILE", "/var/log/siem-ticket-bridge/bridge.log")
error_log = os.getenv("BRIDGE_ERROR_LOG_FILE", "/var/log/siem-ticket-bridge/bridge-error.log")
state = load_json(state_file)

processed = state.get("processed_alerts", {})
if isinstance(processed, list):
    processed_count = len(processed)
elif isinstance(processed, dict):
    processed_count = len(processed)
else:
    processed_count = 0

payload = {
    "status": "ok",
    "checked_at": datetime.now(timezone.utc).isoformat(),
    "last_poll": state.get("last_poll"),
    "last_poll_age_seconds": age_seconds(state.get("last_poll")),
    "processed_alerts": processed_count,
    "ticket_count": state.get("ticket_count", 0),
    "error_count": state.get("error_count", 0),
    "suppressed_count": state.get("suppressed_count", 0),
    "backpressure_count": state.get("backpressure_count", 0),
    "bridge_log_bytes": size(log_file),
    "bridge_error_log_bytes": size(error_log),
    "state_file_bytes": size(state_file),
}

if payload["last_poll_age_seconds"] is None:
    payload["status"] = "unknown"
elif payload["last_poll_age_seconds"] > int(os.getenv("BRIDGE_HEALTH_MAX_POLL_AGE_SECONDS", "300")):
    payload["status"] = "degraded"
if payload["error_count"] and payload["error_count"] > int(os.getenv("BRIDGE_HEALTH_MAX_ERRORS", "25")):
    payload["status"] = "degraded"

print(json.dumps(payload, indent=2, sort_keys=True))
