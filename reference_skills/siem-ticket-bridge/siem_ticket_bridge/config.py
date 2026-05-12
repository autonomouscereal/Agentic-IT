#!/usr/bin/env python3
"""
Configuration management for the SIEM-Ticketing Bridge.

All credentials loaded from environment variables or a .env file.
Zero hardcoded secrets. Supports multiple SIEM and ticketing backends.
"""

import os
import json
import logging
from typing import Dict, Any, Optional
from pathlib import Path

logger = logging.getLogger("siem_ticket_bridge.config")

# Default env var names for each component
ENV_PREFIX = "BRIDGE"

SIEM_ENV_MAP = {
    "siem_type": f"{ENV_PREFIX}_SIEM_TYPE",
    "host": f"{ENV_PREFIX}_SIEM_HOST",
    "port": f"{ENV_PREFIX}_SIEM_PORT",
    "api_user": f"{ENV_PREFIX}_SIEM_API_USER",
    "api_password": f"{ENV_PREFIX}_SIEM_API_PASSWORD",
    "api_token": f"{ENV_PREFIX}_SIEM_API_TOKEN",
    "indexer_port": f"{ENV_PREFIX}_SIEM_INDEXER_PORT",
    "indexer_user": f"{ENV_PREFIX}_SIEM_INDEXER_USER",
    "indexer_password": f"{ENV_PREFIX}_SIEM_INDEXER_PASSWORD",
    "syslog_port": f"{ENV_PREFIX}_SIEM_SYSLOG_PORT",
    "syslog_enabled": f"{ENV_PREFIX}_SIEM_SYSLOG_ENABLED",
    "hec_endpoint": f"{ENV_PREFIX}_SIEM_HEC_ENDPOINT",
    "hec_token": f"{ENV_PREFIX}_SIEM_HEC_TOKEN",
    "timeout": f"{ENV_PREFIX}_SIEM_TIMEOUT",
    "alert_index": f"{ENV_PREFIX}_SIEM_ALERT_INDEX",
    "ca_cert_path": f"{ENV_PREFIX}_SIEM_CA_CERT_PATH",
}

TICKETING_ENV_MAP = {
    "ticketing_type": f"{ENV_PREFIX}_TICKETING_TYPE",
    "host": f"{ENV_PREFIX}_TICKETING_HOST",
    "port": f"{ENV_PREFIX}_TICKETING_PORT",
    "api_user": f"{ENV_PREFIX}_TICKETING_API_USER",
    "api_password": f"{ENV_PREFIX}_TICKETING_API_PASSWORD",
    "api_token": f"{ENV_PREFIX}_TICKETING_API_TOKEN",
    "org_id": f"{ENV_PREFIX}_TICKETING_ORG_ID",
    "caller_id": f"{ENV_PREFIX}_TICKETING_CALLER_ID",
    "team_id": f"{ENV_PREFIX}_TICKETING_TEAM_ID",
    "timeout": f"{ENV_PREFIX}_TICKETING_TIMEOUT",
    "ca_cert_path": f"{ENV_PREFIX}_TICKETING_CA_CERT_PATH",
    "scheme": f"{ENV_PREFIX}_TICKETING_SCHEME",
    "api_path": f"{ENV_PREFIX}_TICKETING_API_PATH",
    "project_key": f"{ENV_PREFIX}_TICKETING_PROJECT_KEY",
    "instance_name": f"{ENV_PREFIX}_TICKETING_INSTANCE_NAME",
}

BRIDGE_ENV_MAP = {
    "poll_interval": f"{ENV_PREFIX}_POLL_INTERVAL",
    "severity_map_file": f"{ENV_PREFIX}_SEVERITY_MAP_FILE",
    "log_level": f"{ENV_PREFIX}_LOG_LEVEL",
    "log_file": f"{ENV_PREFIX}_LOG_FILE",
    "state_file": f"{ENV_PREFIX}_STATE_FILE",
    "enabled": f"{ENV_PREFIX}_ENABLED",
    "batch_size": f"{ENV_PREFIX}_BATCH_SIZE",
    "dedup_window": f"{ENV_PREFIX}_DEDUP_WINDOW",
}


def _env_bool(key: str, default: bool = False) -> bool:
    val = os.environ.get(key, str(default)).lower()
    return val in ("true", "1", "yes", "on")


def _env_int(key: str, default: int = 0) -> int:
    try:
        return int(os.environ.get(key, str(default)))
    except (ValueError, TypeError):
        return default


def _env_str(key: str, default: str = "") -> str:
    return os.environ.get(key, default)


def load_env_file(env_path: str = ".env") -> None:
    """Load key=value pairs from a .env file into os.environ."""
    path = Path(env_path)
    if not path.exists():
        logger.debug("No .env file at %s", env_path)
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip("\"'")
            if key not in os.environ:
                os.environ[key] = value
            logger.debug("Loaded env: %s", key)


def build_siem_config(overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Build SIEM connector config from environment variables."""
    cfg = {
        "enabled": True,
        "siem_type": _env_str(SIEM_ENV_MAP["siem_type"], "wazuh"),
        "host": _env_str(SIEM_ENV_MAP["host"], "127.0.0.1"),
        "port": _env_int(SIEM_ENV_MAP["port"]),
        "api_user": _env_str(SIEM_ENV_MAP["api_user"]),
        "api_password": _env_str(SIEM_ENV_MAP["api_password"]),
        "api_token": _env_str(SIEM_ENV_MAP["api_token"]),
        "indexer_port": _env_int(SIEM_ENV_MAP["indexer_port"]),
        "indexer_user": _env_str(SIEM_ENV_MAP["indexer_user"]),
        "indexer_password": _env_str(SIEM_ENV_MAP["indexer_password"]),
        "syslog_port": _env_int(SIEM_ENV_MAP["syslog_port"]),
        "syslog_enabled": _env_bool(SIEM_ENV_MAP["syslog_enabled"], True),
        "hec_endpoint": _env_str(SIEM_ENV_MAP["hec_endpoint"]),
        "hec_token": _env_str(SIEM_ENV_MAP["hec_token"]),
        "timeout": _env_int(SIEM_ENV_MAP["timeout"], 10),
        "alert_index": _env_str(SIEM_ENV_MAP["alert_index"], "wazuh-alerts-4.x-*"),
        "ca_cert_path": _env_str(SIEM_ENV_MAP["ca_cert_path"]),
    }
    if overrides:
        cfg.update(overrides)
    return cfg


def build_ticketing_config(overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Build ticketing connector config from environment variables."""
    cfg = {
        "enabled": True,
        "ticketing_type": _env_str(TICKETING_ENV_MAP["ticketing_type"], "itop"),
        "host": _env_str(TICKETING_ENV_MAP["host"], "127.0.0.1"),
        "port": _env_int(TICKETING_ENV_MAP["port"], 25432),
        "api_user": _env_str(TICKETING_ENV_MAP["api_user"]),
        "api_password": _env_str(TICKETING_ENV_MAP["api_password"]),
        "api_token": _env_str(TICKETING_ENV_MAP["api_token"]),
        "org_id": _env_int(TICKETING_ENV_MAP["org_id"], 1),
        "caller_id": _env_int(TICKETING_ENV_MAP["caller_id"], 1),
        "team_id": _env_int(TICKETING_ENV_MAP["team_id"]),
        "timeout": _env_int(TICKETING_ENV_MAP["timeout"], 10),
        "ca_cert_path": _env_str(TICKETING_ENV_MAP["ca_cert_path"]),
        "scheme": _env_str(TICKETING_ENV_MAP["scheme"], "http"),
        "api_path": _env_str(TICKETING_ENV_MAP["api_path"], "/webservices/rest.php"),
        "project_key": _env_str(TICKETING_ENV_MAP["project_key"], "SEC"),
        "instance_name": _env_str(TICKETING_ENV_MAP["instance_name"], "itop"),
    }
    if overrides:
        cfg.update(overrides)
    return cfg


def build_bridge_config(overrides: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Build bridge orchestrator config from environment variables."""
    cfg = {
        "enabled": _env_bool(BRIDGE_ENV_MAP["enabled"], True),
        "poll_interval": _env_int(BRIDGE_ENV_MAP["poll_interval"], 60),
        "severity_map_file": _env_str(BRIDGE_ENV_MAP["severity_map_file"], "severity_map.json"),
        "log_level": _env_str(BRIDGE_ENV_MAP["log_level"], "INFO"),
        "log_file": _env_str(BRIDGE_ENV_MAP["log_file"], "/var/log/siem-ticket-bridge/bridge.log"),
        "state_file": _env_str(BRIDGE_ENV_MAP["state_file"], "/var/lib/siem-ticket-bridge/state.json"),
        "batch_size": _env_int(BRIDGE_ENV_MAP["batch_size"], 50),
        "dedup_window": _env_int(BRIDGE_ENV_MAP["dedup_window"], 3600),
    }
    if overrides:
        cfg.update(overrides)
    return cfg


def load_json_config(path: str) -> Dict[str, Any]:
    """Load a JSON config file (for severity maps, rule overrides, etc.)."""
    with open(path) as f:
        return json.load(f)


def save_json_config(path: str, data: Dict[str, Any]) -> None:
    """Save a JSON config file."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
