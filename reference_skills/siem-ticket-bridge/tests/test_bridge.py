#!/usr/bin/env python3
"""
End-to-end test suite for the SIEM-to-Ticketing Bridge.

Tests connectivity, alert fetching, ticket creation, deduplication,
and the full poll cycle. Run with --siem and/or --ticketing flags
to test against live systems.
"""

import json
import sys
import os
import time
import unittest
from unittest import mock
from datetime import datetime, timezone

# Allow running from project root or tests directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from siem_ticket_bridge.siem.connector import SIEMConnector, NullConnector, make_ssl_ctx
from siem_ticket_bridge.siem.wazuh_connector import WazuhConnector
from siem_ticket_bridge.siem import create_connector as create_siem_connector, register_connector
from siem_ticket_bridge.ticketing.connector import TicketingConnector, NullTicketingConnector
from siem_ticket_bridge.ticketing.itop_connector import ITOPConnector
from siem_ticket_bridge.ticketing import create_connector as create_ticketing_connector
from siem_ticket_bridge.bridge import Bridge
from siem_ticket_bridge.config import (
    build_siem_config,
    build_ticketing_config,
    build_bridge_config,
    save_json_config,
    load_json_config,
)


class TestNullConnectors(unittest.TestCase):
    """Test null connectors return safe defaults."""

    def test_null_siem_connectivity(self):
        conn = NullConnector({})
        self.assertFalse(conn._check_connectivity())

    def test_null_siem_fetch(self):
        conn = NullConnector({})
        self.assertEqual(conn.fetch_alerts(), [])

    def test_null_ticketing_connectivity(self):
        conn = NullTicketingConnector({})
        self.assertFalse(conn._check_connectivity())

    def test_null_ticketing_create(self):
        conn = NullTicketingConnector({})
        self.assertIsNone(conn.create_ticket({}))

    def test_null_ticketing_update(self):
        conn = NullTicketingConnector({})
        self.assertFalse(conn.update_ticket("1", {}))

    def test_null_ticketing_get(self):
        conn = NullTicketingConnector({})
        self.assertIsNone(conn.get_ticket("1"))


class TestConnectorFactories(unittest.TestCase):
    """Test factory functions return correct connector types."""

    def test_create_wazuh(self):
        conn = create_siem_connector("wazuh", {})
        self.assertIsInstance(conn, WazuhConnector)

    def test_create_null_siem(self):
        conn = create_siem_connector("null", {})
        self.assertIsInstance(conn, NullConnector)

    def test_create_unknown_siem(self):
        conn = create_siem_connector("unknown", {})
        self.assertIsInstance(conn, NullConnector)

    def test_create_itop(self):
        conn = create_ticketing_connector("itop", {})
        self.assertIsInstance(conn, ITOPConnector)

    def test_create_null_ticketing(self):
        conn = create_ticketing_connector("null", {})
        self.assertIsInstance(conn, NullTicketingConnector)

    def test_create_unknown_ticketing(self):
        conn = create_ticketing_connector("unknown", {})
        self.assertIsInstance(conn, NullTicketingConnector)


class TestConfig(unittest.TestCase):
    """Test configuration loading and building."""

    def test_default_siem_config(self):
        cfg = build_siem_config()
        self.assertIn("siem_type", cfg)
        self.assertIn("host", cfg)
        self.assertTrue(cfg["enabled"])

    def test_default_ticketing_config(self):
        cfg = build_ticketing_config()
        self.assertIn("ticketing_type", cfg)
        self.assertIn("host", cfg)

    def test_default_bridge_config(self):
        cfg = build_bridge_config()
        self.assertEqual(cfg["poll_interval"], 60)
        self.assertEqual(cfg["batch_size"], 50)

    def test_env_var_override(self):
        os.environ["BRIDGE_POLL_INTERVAL"] = "120"
        try:
            cfg = build_bridge_config()
            self.assertEqual(cfg["poll_interval"], 120)
        finally:
            del os.environ["BRIDGE_POLL_INTERVAL"]

    def test_config_override_param(self):
        cfg = build_siem_config(overrides={"siem_type": "splunk"})
        self.assertEqual(cfg["siem_type"], "splunk")

    def test_json_config_save_load(self):
        path = "/tmp/test_bridge_config.json"
        data = {"key": "value", "count": 42}
        save_json_config(path, data)
        loaded = load_json_config(path)
        self.assertEqual(loaded["key"], "value")
        self.assertEqual(loaded["count"], 42)
        os.remove(path)


class TestSeverityMapping(unittest.TestCase):
    """Test Wazuh level to severity mapping."""

    def setUp(self):
        self.itop = ITOPConnector({})

    def test_emergency_level(self):
        self.assertEqual(self.itop._level_to_severity(15), "emergency")

    def test_critical_level(self):
        self.assertEqual(self.itop._level_to_severity(12), "critical")

    def test_high_level(self):
        self.assertEqual(self.itop._level_to_severity(9), "high")

    def test_medium_level(self):
        self.assertEqual(self.itop._level_to_severity(5), "medium")

    def test_low_level(self):
        self.assertEqual(self.itop._level_to_severity(2), "low")

    def test_zero_level(self):
        self.assertEqual(self.itop._level_to_severity(0), "low")


class TestBridgeNull(unittest.TestCase):
    """Test bridge orchestrator with null connectors (no live systems needed)."""

    def setUp(self):
        self.bridge = Bridge(
            siem_config={"siem_type": "null"},
            ticketing_config={"ticketing_type": "null"},
            bridge_config={
                "state_file": "/tmp/test_bridge_state.json",
                "severity_map_file": "severity_map.json",
            },
        )

    def tearDown(self):
        path = "/tmp/test_bridge_state.json"
        if os.path.exists(path):
            os.remove(path)

    def test_status_returns_dict(self):
        status = self.bridge.status()
        self.assertIn("siem_connected", status)
        self.assertIn("ticketing_connected", status)

    def test_null_siem_not_connected(self):
        status = self.bridge.status()
        self.assertFalse(status["siem_connected"])

    def test_poll_returns_stats(self):
        stats = self.bridge.run_once()
        self.assertIn("fetched", stats)
        self.assertIn("tickets_created", stats)

    def test_poll_with_null_returns_zero(self):
        stats = self.bridge.run_once()
        self.assertEqual(stats["fetched"], 0)
        self.assertEqual(stats["tickets_created"], 0)

    def test_state_persistence(self):
        # Directly test state saving (null connectors skip poll, so save manually)
        self.bridge._save_state()
        self.assertTrue(os.path.exists("/tmp/test_bridge_state.json"))


class TestBridgeDedup(unittest.TestCase):
    """Test alert deduplication logic."""

    def setUp(self):
        self.bridge = Bridge(
            siem_config={"siem_type": "null"},
            ticketing_config={"ticketing_type": "null"},
            bridge_config={
                "state_file": "/tmp/test_bridge_dedup.json",
            },
        )

    def tearDown(self):
        path = "/tmp/test_bridge_dedup.json"
        if os.path.exists(path):
            os.remove(path)

    def test_duplicate_detection(self):
        alert = {
            "rule_id": "100100",
            "source_ip": "10.0.0.1",
            "timestamp": "2026-04-29T10:00:00Z",
            "level": 10,
        }
        self.assertFalse(self.bridge._is_duplicate(alert))
        self.bridge._mark_processed(alert)
        self.assertTrue(self.bridge._is_duplicate(alert))

    def test_severity_threshold(self):
        low_alert = {"level": 2}
        high_alert = {"level": 7}
        self.assertFalse(self.bridge._should_create_ticket(low_alert))
        self.assertTrue(self.bridge._should_create_ticket(high_alert))


class TestWazuhConnectorInit(unittest.TestCase):
    """Test Wazuh connector initialization without live connection."""

    def test_default_init(self):
        conn = WazuhConnector({})
        self.assertEqual(conn.host, "127.0.0.1")
        self.assertEqual(conn.port, 26500)

    def test_custom_init(self):
        conn = WazuhConnector({
            "host": "127.0.0.1",
            "port": 26500,
            "indexer_port": 26920,
        })
        self.assertEqual(conn.host, "127.0.0.1")
        self.assertEqual(conn.indexer_port, 26920)

    def test_normalize_alert(self):
        conn = WazuhConnector({})
        raw = {
            "@timestamp": "2026-04-29T10:00:00Z",
            "rule": {"id": 100100, "level": 10, "description": "Test Rule"},
            "agent": {"name": "test-agent", "ip": "10.0.0.1"},
            "data": {"src_ip": "10.0.0.5", "log": "test log"},
        }
        alert = conn._normalize_alert(raw)
        self.assertEqual(alert["rule_id"], "100100")
        self.assertEqual(alert["rule_name"], "Test Rule")
        self.assertEqual(alert["level"], 10)
        self.assertEqual(alert["source_ip"], "10.0.0.5")


class TestITOPConnectorInit(unittest.TestCase):
    """Test iTop connector initialization without live connection."""

    def test_default_init(self):
        conn = ITOPConnector({})
        self.assertEqual(conn.host, "127.0.0.1")
        self.assertEqual(conn.port, 25432)

    def test_custom_init(self):
        conn = ITOPConnector({
            "host": "127.0.0.1",
            "port": 25432,
            "team_id": 5,
        })
        self.assertEqual(conn.team_id, 5)

    def test_severity_map(self):
        conn = ITOPConnector({})
        self.assertEqual(conn._level_to_severity(14), "emergency")
        self.assertEqual(conn._level_to_severity(10), "high")
        self.assertEqual(conn._level_to_severity(3), "low")


# ---- Live tests (run with --live flag) ----

class TestLiveWazuh(unittest.TestCase):
    """Live Wazuh connectivity tests. Skip unless --live passed."""

    @classmethod
    def setUpClass(cls):
        if "--live" not in sys.argv:
            cls.skip = True
        else:
            cls.skip = False
            cls.conn = WazuhConnector({
                "host": "127.0.0.1",
                "port": 26500,
                "indexer_port": 26920,
                "api_user": os.environ.get("BRIDGE_SIEM_API_USER", "wazuh-wui"),
                "api_password": os.environ.get("BRIDGE_SIEM_API_PASSWORD", ""),
                "indexer_user": os.environ.get("BRIDGE_SIEM_INDEXER_USER", "admin"),
                "indexer_password": os.environ.get("BRIDGE_SIEM_INDEXER_PASSWORD", ""),
            })

    def test_connectivity(self):
        if getattr(self, "skip", False):
            self.skipTest("Live tests disabled (pass --live)")
        self.assertTrue(self.conn.is_connected(), "Wazuh should be reachable")

    def test_fetch_alerts(self):
        if getattr(self, "skip", False):
            self.skipTest("Live tests disabled (pass --live)")
        alerts = self.conn.safe_fetch_alerts(limit=5)
        self.assertIsInstance(alerts, list)


class TestLiveITOP(unittest.TestCase):
    """Live iTop connectivity tests. Skip unless --live passed."""

    @classmethod
    def setUpClass(cls):
        if "--live" not in sys.argv:
            cls.skip = True
        else:
            cls.skip = False
            cls.conn = ITOPConnector({
                "host": "127.0.0.1",
                "port": 25432,
                "api_user": os.environ.get("BRIDGE_TICKETING_API_USER", "admin"),
                "api_password": os.environ.get("BRIDGE_TICKETING_API_PASSWORD", ""),
            })

    def test_connectivity(self):
        if getattr(self, "skip", False):
            self.skipTest("Live tests disabled (pass --live)")
        self.assertTrue(self.conn.is_connected(), "iTop should be reachable")


if __name__ == "__main__":
    unittest.main()
