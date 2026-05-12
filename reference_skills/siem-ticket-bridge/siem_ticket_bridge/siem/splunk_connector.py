#!/usr/bin/env python3
"""
Splunk HEC connector - implements SIEMConnector for Splunk Enterprise/Cloud.

Uses the HTTP Event Collector (HEC) for submitting and querying alerts.
Register with: from siem_ticket_bridge.siem import register_connector
              register_connector("splunk", SplunkConnector)
"""

import json
import logging
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from .connector import SIEMConnector, make_ssl_ctx, http_post

logger = logging.getLogger("siem_ticket_bridge.siem.splunk")

DEFAULT_CONFIG = {
    "enabled": True,
    "host": "127.0.0.1",
    "port": 8088,
    "hec_token": "",
    "hec_endpoint": "/services/collector",
    "timeout": 10,
    "ca_cert_path": "",
    "search_endpoint": "/services/search/jobs",
    "api_user": "admin",
    "api_password": "",
}


class SplunkConnector(SIEMConnector):
    """Splunk HEC connector for alert submission and query."""

    def __init__(self, config: Dict[str, Any] = None):
        cfg = dict(DEFAULT_CONFIG)
        if config:
            cfg.update(config)
        super().__init__(cfg)

        self.host = cfg["host"]
        self.port = cfg["port"]
        self.hec_token = cfg["hec_token"]
        self.hec_endpoint = cfg.get("hec_endpoint", "/services/collector")
        self.ca_cert_path = cfg.get("ca_cert_path", "")
        self.api_user = cfg.get("api_user", "admin")
        self.api_password = cfg.get("api_password", "")

        self._ssl_ctx = make_ssl_ctx(self.ca_cert_path or None)
        self._base_url = f"https://{self.host}:{self.port}"

    def _check_connectivity(self) -> bool:
        """Test HEC connectivity by sending a ping event."""
        ping = {"event": "bridge_ping", "time": time.time()}
        result = self._hec_post(ping)
        return result.get("code") == 0

    def _hec_post(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Send event via HEC."""
        url = f"{self._base_url}{self.hec_endpoint}/event"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Splunk {self.hec_token}",
        }
        return http_post(url, event, headers, self.timeout, self._ssl_ctx)

    def fetch_alerts(self, since: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """
        Fetch alerts via Splunk search API.

        Note: This requires the api_user/api_password for authenticated search.
        HEC token alone is insufficient for search operations.
        """
        if not self._check_connectivity():
            logger.warning("Splunk HEC not connected")
            return []

        time_range = "earliest=-1h"
        if since:
            time_range = f"earliest={since}"

        search = f'search index=security | head {limit} | sort -_time'
        url = f"{self._base_url}/services/search/jobs"

        import urllib.parse
        import urllib.request
        import base64

        data = urllib.parse.urlencode({
            "search": search,
            "output_mode": "json",
            time_range: "",
        }).encode()

        creds = base64.b64encode(f"{self.api_user}:{self.api_password}".encode()).decode()
        headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Authorization": f"Basic {creds}",
        }

        result = http_post(url, {}, headers, self.timeout, self._ssl_ctx)
        if "error" in result:
            logger.error("Splunk search failed: %s", result)
            return []

        results = result.get("results", [])
        alerts = []
        for r in results:
            alert = {
                "siem_id": r.get("_indextime", ""),
                "timestamp": r.get("_time", ""),
                "rule_id": r.get("alert_id", r.get("signature_id", "")),
                "rule_name": r.get("alert_name", r.get("signature_title", "Splunk Alert")),
                "level": int(r.get("severity", r.get("priority", 0))),
                "source_ip": r.get("src", r.get("src_ip", "unknown")),
                "destination_ip": r.get("dest", r.get("dest_ip", "")),
                "agent_name": r.get("host", "unknown"),
                "log": json.dumps(r),
                "raw": r,
            }
            alerts.append(alert)

        logger.info("Fetched %d alerts from Splunk", len(alerts))
        return alerts
