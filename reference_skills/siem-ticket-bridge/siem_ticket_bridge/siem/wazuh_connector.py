#!/usr/bin/env python3
"""
Wazuh SIEM connector - implements SIEMConnector for Wazuh v4.14.4+.

Fetches alerts from the Wazuh Indexer (OpenSearch) and supports
syslog UDP forwarding for test events.
"""

import json
import time
import base64
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

from .connector import SIEMConnector, make_ssl_ctx, http_get, http_post

logger = logging.getLogger("siem_ticket_bridge.siem.wazuh")

DEFAULT_CONFIG = {
    "enabled": True,
    "host": "127.0.0.1",
    "port": 26500,
    "api_user": "wazuh-wui",
    "api_password": "",
    "indexer_port": 26920,
    "indexer_user": "admin",
    "indexer_password": "",
    "syslog_port": 26514,
    "syslog_enabled": True,
    "timeout": 10,
    "alert_index": "wazuh-alerts-4.x-*",
    "ca_cert_path": "",
}


class WazuhConnector(SIEMConnector):
    """Wazuh SIEM connector with Indexer query + manager API auth."""

    def __init__(self, config: Dict[str, Any] = None):
        cfg = dict(DEFAULT_CONFIG)
        if config:
            cfg.update(config)
        super().__init__(cfg)

        self.host = cfg["host"]
        self.port = cfg["port"]
        self.api_user = cfg["api_user"]
        self.api_password = cfg["api_password"]

        self.indexer_port = cfg["indexer_port"]
        self.indexer_user = cfg["indexer_user"]
        self.indexer_password = cfg["indexer_password"]

        self.syslog_port = cfg.get("syslog_port", 26514)
        self.syslog_enabled = cfg.get("syslog_enabled", True)
        self.alert_index = cfg.get("alert_index", "wazuh-alerts-4.x-*")
        self.ca_cert_path = cfg.get("ca_cert_path", "")

        self._token: Optional[str] = None
        self._ssl_ctx = make_ssl_ctx(self.ca_cert_path or None)

    # ---- Connectivity ----

    def _check_connectivity(self) -> bool:
        """Check by authenticating to the manager API."""
        return self._get_token() is not None

    def _get_token(self) -> Optional[str]:
        """Authenticate to Wazuh manager API and return JWT token."""
        if self._token:
            return self._token
        url = f"https://{self.host}:{self.port}/security/user/authenticate"
        creds = base64.b64encode(f"{self.api_user}:{self.api_password}".encode()).decode()
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Basic {creds}",
        }
        result = http_post(url, {"run_as": self.api_user}, headers, self.timeout, self._ssl_ctx)
        if result.get("error", 1) == 0:
            self._token = result.get("data", {}).get("token")
            return self._token
        logger.warning("Wazuh API auth failed: %s", result)
        return None

    # ---- Alert fetching ----

    def fetch_alerts(self, since: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Fetch alerts from Wazuh Indexer (OpenSearch).

        Args:
            since: ISO8601 timestamp to fetch alerts after. If None, fetches last hour.
            limit: Max alerts to return.
        """
        if not self._check_connectivity():
            logger.warning("Wazuh connector not connected, cannot fetch alerts")
            return []

        # Build time range query
        if since:
            time_from = since
        else:
            time_from = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S")

        query = {
            "query": {
                "bool": {
                    "must": [
                        {"range": {"@timestamp": {"gte": time_from, "format": "strict_date_optional_time"}}}
                    ]
                }
            },
            "sort": [{"@timestamp": {"order": "desc"}}],
            "size": limit,
        }

        url = f"https://{self.host}:{self.indexer_port}/{self.alert_index}/_search"
        headers = {
            "Content-Type": "application/json",
            "kbn-xsrf": "true",
        }
        # Indexer uses basic auth
        idx_creds = base64.b64encode(
            f"{self.indexer_user}:{self.indexer_password}".encode()
        ).decode()
        headers["Authorization"] = f"Basic {idx_creds}"

        result = http_post(url, query, headers, self.timeout, self._ssl_ctx)
        if "error" in result and isinstance(result["error"], dict):
            logger.error("Wazuh Indexer query failed: %s", result["error"])
            return []

        hits = result.get("hits", {}).get("hits", [])
        alerts = []
        for hit in hits:
            source = hit.get("_source", {})
            alert = self._normalize_alert(source)
            alerts.append(alert)

        logger.info("Fetched %d alerts from Wazuh Indexer", len(alerts))
        return alerts

    def _normalize_alert(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize a raw Wazuh alert to a standard bridge alert dict."""
        rule = raw.get("rule", {})
        agent = raw.get("agent", {})
        full_log = raw.get("data", {}).get("decoder", {}).get("log", raw.get("data", {}).get("log", ""))

        return {
            "siem_id": raw.get("@timestamp", ""),
            "timestamp": raw.get("@timestamp", ""),
            "rule_id": str(rule.get("id", "")),
            "rule_name": rule.get("description", ""),
            "level": int(rule.get("level", 0)),
            "source_ip": raw.get("data", {}).get("src_ip", agent.get("ip", "unknown")),
            "destination_ip": raw.get("data", {}).get("dst_ip", ""),
            "agent_name": agent.get("name", "unknown"),
            "log": full_log,
            "raw": raw,
        }
