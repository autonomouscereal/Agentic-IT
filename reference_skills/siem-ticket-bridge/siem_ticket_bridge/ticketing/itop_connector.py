#!/usr/bin/env python3
"""
iTop ITSM connector — implements TicketingConnector for iTop v3.2.1+.

Creates incidents from SIEM alerts with proper severity mapping,
team assignment, and deduplication.
"""

import json
import logging
import urllib.parse
import urllib.request
import urllib.error
import ssl
from datetime import datetime, timezone
from typing import Dict, Any, Optional

from .connector import TicketingConnector, make_ssl_ctx

logger = logging.getLogger("siem_ticket_bridge.ticketing.itop")

DEFAULT_CONFIG = {
    "enabled": True,
    "host": "127.0.0.1",
    "port": 25432,
    "api_user": "admin",
    "api_password": "",
    "org_id": 1,
    "caller_id": 1,
    "team_id": None,
    "timeout": 10,
    "ca_cert_path": "",
    "scheme": "http",
    "api_path": "/webservices/rest.php",
}

# Map Wazuh alert levels to iTop impact (1-3) and urgency (1-5)
SEVERITY_MAP = {
    "emergency": {"impact": 3, "urgency": 4},
    "critical": {"impact": 3, "urgency": 3},
    "high": {"impact": 2, "urgency": 3},
    "medium": {"impact": 2, "urgency": 2},
    "low": {"impact": 1, "urgency": 1},
    "info": {"impact": 1, "urgency": 1},
}


class ITOPConnector(TicketingConnector):
    """iTop ITSM connector for ticket creation and management."""

    def __init__(self, config: Dict[str, Any] = None):
        cfg = dict(DEFAULT_CONFIG)
        if config:
            cfg.update(config)
        super().__init__(cfg)

        self.host = cfg["host"]
        self.port = cfg["port"]
        self.api_user = cfg["api_user"]
        self.api_password = cfg["api_password"]
        self.org_id = cfg.get("org_id", 1)
        self.caller_id = cfg.get("caller_id", 1)
        self.team_id = cfg.get("team_id")
        self.scheme = cfg.get("scheme", "http")
        self.api_path = cfg.get("api_path", "/webservices/rest.php")
        self.ca_cert_path = cfg.get("ca_cert_path", "")

        self._ssl_ctx = make_ssl_ctx(self.ca_cert_path or None)
        self._base_url = f"{self.scheme}://{self.host}:{self.port}{self.api_path}"

    # ---- Connectivity ----

    def _check_connectivity(self) -> bool:
        """Check credentials via core/check_credentials."""
        result = self._post({"operation": "core/check_credentials"})
        return result.get("code") == 0

    # ---- API ----

    def _post(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Send a POST to the iTop REST API with dual auth."""
        payload["user"] = self.api_user
        payload["password"] = self.api_password

        json_data = json.dumps(payload)
        data = urllib.parse.urlencode({
            "version": "1.4",
            "json_output": "1",
            "json_data": json_data,
        }).encode()

        req = urllib.request.Request(self._base_url, data=data, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")

        # Basic auth header (iTop requires both header and payload auth)
        import base64
        creds = base64.b64encode(f"{self.api_user}:{self.api_password}".encode()).decode()
        req.add_header("Authorization", f"Basic {creds}")

        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=self._ssl_ctx) as resp:
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            logger.error("iTop API HTTP %d", e.code)
            return {"code": e.code, "error": f"HTTP {e.code}"}
        except Exception as e:
            logger.error("iTop API request failed: %s", e)
            return {"code": -1, "error": str(e)}

    # ---- Ticket operations ----

    def create_ticket(self, alert: Dict[str, Any]) -> Optional[str]:
        """
        Create an Incident from a normalized SIEM alert.

        Returns the Incident key (numeric ID) or None on failure.
        """
        level = alert.get("level", 0)
        severity = self._level_to_severity(level)
        sev_map = SEVERITY_MAP.get(severity, {"impact": 1, "urgency": 1})

        rule_name = alert.get("rule_name", "SIEM Alert")
        source_ip = alert.get("source_ip", "unknown")
        timestamp = alert.get("timestamp", datetime.now(timezone.utc).isoformat())
        log = alert.get("log", "")

        title = f"[SIEM] {rule_name} (level {level})"
        description = (
            f"SIEM Alert — Rule: {rule_name}\n"
            f"Rule ID: {alert.get('rule_id', 'N/A')}\n"
            f"Level: {level} ({severity})\n"
            f"Source IP: {source_ip}\n"
            f"Destination IP: {alert.get('destination_ip', 'N/A')}\n"
            f"Agent: {alert.get('agent_name', 'N/A')}\n"
            f"Timestamp: {timestamp}\n"
            f"Raw Log: {log[:500]}"
        )

        fields = {
            "title": title,
            "description": description,
            "impact": sev_map["impact"],
            "urgency": sev_map["urgency"],
            "org_id": self.org_id,
            "caller_id": self.caller_id,
        }
        if self.team_id:
            fields["team_id"] = self.team_id

        payload = {
            "operation": "core/create",
            "class": "Incident",
            "comment": f"Auto-created from SIEM alert rule {alert.get('rule_id', '')}",
            "fields": fields,
        }

        result = self._post(payload)
        if result.get("code", 0) != 0:
            logger.error("iTop create_ticket failed: %s", result)
            return None

        # Extract the created object key
        obj_key = None
        objects = result.get("objects", {})
        for okey, val in objects.items():
            if isinstance(val, dict):
                obj_key = str(val.get("key", "")) or str(val.get("fields", {}).get("key", ""))
                if not obj_key or obj_key == "None" or obj_key == "0":
                    # Try extracting numeric key from "Incident::77" style key
                    parts = okey.split("::")
                    if len(parts) == 2:
                        obj_key = parts[1]
                break

        if obj_key:
            logger.info("Created Incident %s for alert rule %s", obj_key, alert.get("rule_id"))
        else:
            logger.error("Create succeeded but no key returned: %s", result)

        return obj_key

    def update_ticket(self, ticket_id: str, fields: Dict[str, Any]) -> bool:
        """Update an existing Incident."""
        payload = {
            "operation": "core/update",
            "class": "Incident",
            "key": int(ticket_id),
            "comment": "SIEM bridge update",
            "fields": fields,
        }
        result = self._post(payload)
        return result.get("code") == 0

    def get_ticket(self, ticket_id: str) -> Optional[Dict[str, Any]]:
        """Get Incident details."""
        payload = {
            "operation": "core/get",
            "class": "Incident",
            "key": int(ticket_id),
        }
        result = self._post(payload)
        if result.get("code", 0) != 0:
            return None
        objects = result.get("objects", {})
        for key, val in objects.items():
            if isinstance(val, dict):
                return val
        return None

    # ---- Helpers ----

    def _level_to_severity(self, level: int) -> str:
        """Convert Wazuh level (0-15) to severity string."""
        if level >= 13:
            return "emergency"
        if level >= 11:
            return "critical"
        if level >= 7:
            return "high"
        if level >= 4:
            return "medium"
        return "low"
