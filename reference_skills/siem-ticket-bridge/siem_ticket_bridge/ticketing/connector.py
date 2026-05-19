#!/usr/bin/env python3
"""
Abstract ticketing connector base.

Defines the interface all ticketing backends must implement.
All operations are fault-tolerant - failures return None, never raise.
"""

import abc
import json
import time
import logging
import ssl
import urllib.request
import urllib.error
from typing import Dict, Any, List, Optional

logger = logging.getLogger("siem_ticket_bridge.ticketing")


class TicketingConnector(abc.ABC):
    """Abstract ticketing connector - subclass for each platform (iTop, Jira, ServiceNow, etc.)."""

    def __init__(self, config: Dict[str, Any]):
        self.enabled = config.get("enabled", True)
        self.timeout = config.get("timeout", 10)
        self._connected = False
        self._last_check = 0.0
        self._cache_ttl = 30.0

    @abc.abstractmethod
    def _check_connectivity(self) -> bool:
        """Test if the ticketing system is reachable."""
        ...

    @abc.abstractmethod
    def create_ticket(self, alert: Dict[str, Any]) -> Optional[str]:
        """
        Create a ticket from a normalized SIEM alert.
        Returns the ticket key/ID on success, None on failure.
        """
        ...

    @abc.abstractmethod
    def update_ticket(self, ticket_id: str, fields: Dict[str, Any]) -> bool:
        """Update an existing ticket. Returns True on success."""
        ...

    @abc.abstractmethod
    def get_ticket(self, ticket_id: str) -> Optional[Dict[str, Any]]:
        """Get ticket details. Returns dict or None."""
        ...

    def is_connected(self) -> bool:
        """Check connectivity with caching."""
        now = time.time()
        if now - self._last_check < self._cache_ttl:
            return self._connected
        self._connected = self._check_connectivity()
        self._last_check = now
        return self._connected

    def safe_create_ticket(self, alert: Dict[str, Any]) -> Optional[str]:
        """Create ticket - never raises. Returns ticket ID or None."""
        if not self.enabled:
            return None
        try:
            return self.create_ticket(alert)
        except Exception as e:
            logger.error("create_ticket failed: %s", e)
            return None


class NullTicketingConnector(TicketingConnector):
    """No-op connector - used when no ticketing system is configured."""

    def _check_connectivity(self) -> bool:
        return False

    def create_ticket(self, alert) -> Optional[str]:
        return None

    def update_ticket(self, ticket_id, fields) -> bool:
        return False

    def get_ticket(self, ticket_id) -> Optional[Dict[str, Any]]:
        return None


def make_ssl_ctx(ca_cert: str = None) -> ssl.SSLContext:
    """Create an SSL context with optional CA cert."""
    ctx = ssl.create_default_context()
    if ca_cert:
        ctx.load_verify_locations(ca_cert)
    else:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def http_post_form(url: str, data: Dict[str, str], headers: Dict[str, str],
                   timeout: int, ssl_ctx: ssl.SSLContext) -> Dict[str, Any]:
    """HTTP POST with form-encoded body. Returns parsed JSON or error dict."""
    import urllib.parse
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl_ctx) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}"}
    except Exception as e:
        return {"error": str(e)}
