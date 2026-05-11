#!/usr/bin/env python3
"""
Abstract SIEM connector base.

Defines the interface all SIEM backends must implement.
All operations are fault-tolerant — failures return False, never raise.
"""

import abc
import json
import time
import logging
import ssl
import socket
import urllib.request
import urllib.error
from typing import Dict, Any, List, Optional

logger = logging.getLogger("siem_ticket_bridge.siem")


class SIEMConnector(abc.ABC):
    """Abstract SIEM connector — subclass for each platform (Wazuh, Splunk, ELK, etc.)."""

    def __init__(self, config: Dict[str, Any]):
        self.enabled = config.get("enabled", True)
        self.timeout = config.get("timeout", 10)
        self._connected = False
        self._last_check = 0.0
        self._cache_ttl = 30.0

    @abc.abstractmethod
    def _check_connectivity(self) -> bool:
        """Test if the SIEM is reachable."""
        ...

    @abc.abstractmethod
    def fetch_alerts(self, since: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Fetch alerts from the SIEM. Returns list of alert dicts."""
        ...

    def is_connected(self) -> bool:
        """Check SIEM connectivity with caching."""
        now = time.time()
        if now - self._last_check < self._cache_ttl:
            return self._connected
        self._connected = self._check_connectivity()
        self._last_check = now
        return self._connected

    def safe_fetch_alerts(self, since: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        """Fetch alerts — never raises. Returns empty list on failure."""
        if not self.enabled:
            return []
        try:
            return self.fetch_alerts(since=since, limit=limit)
        except Exception as e:
            logger.error("SIEM fetch_alerts failed: %s", e)
            return []


class NullConnector(SIEMConnector):
    """No-op connector — used when no SIEM is configured."""

    def _check_connectivity(self) -> bool:
        return False

    def fetch_alerts(self, since=None, limit=50) -> List[Dict[str, Any]]:
        return []


def make_ssl_ctx(ca_cert: str = None) -> ssl.SSLContext:
    """Create an SSL context with optional CA cert."""
    ctx = ssl.create_default_context()
    if ca_cert:
        ctx.load_verify_locations(ca_cert)
    else:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def http_get(url: str, headers: Dict[str, str], timeout: int, ssl_ctx: ssl.SSLContext) -> Dict[str, Any]:
    """Generic HTTPS GET. Returns parsed JSON or error dict."""
    req = urllib.request.Request(url, method="GET")
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl_ctx) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}"}
    except Exception as e:
        return {"error": str(e)}


def http_post(url: str, body: dict, headers: Dict[str, str], timeout: int, ssl_ctx: ssl.SSLContext) -> Dict[str, Any]:
    """Generic HTTPS POST. Returns parsed JSON or error dict."""
    data = json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method="POST")
    for k, v in headers.items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl_ctx) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}"}
    except Exception as e:
        return {"error": str(e)}


def udp_send(host: str, port: int, message: str, timeout: int = 2) -> bool:
    """Send UDP packet. Returns True if sent without exception."""
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(timeout)
        sock.sendto(message.encode(), (host, port))
        sock.close()
        return True
    except Exception:
        return False
