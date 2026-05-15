#!/usr/bin/env python3
"""
SIEM-to-Ticketing Bridge — main orchestrator.

Polls the SIEM for new alerts, normalizes them, deduplicates,
and creates tickets in the configured ticketing system.

Fully modular: swap SIEM or ticketing backends via config.
"""

import json
import time
import signal
import logging
import logging.handlers
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List, Set

from .config import (
    load_env_file,
    build_siem_config,
    build_ticketing_config,
    build_bridge_config,
    save_json_config,
    load_json_config,
)
from .siem import create_connector as create_siem_connector
from .ticketing import create_connector as create_ticketing_connector

logger = logging.getLogger("siem_ticket_bridge")


class Bridge:
    """Main orchestrator: SIEM alerts -> ticket creation."""

    def __init__(self, siem_config: Dict[str, Any],
                 ticketing_config: Dict[str, Any],
                 bridge_config: Dict[str, Any]):
        self.siem = create_siem_connector(
            siem_config.get("siem_type", "wazuh"),
            siem_config,
        )
        self.ticketing = create_ticketing_connector(
            ticketing_config.get("ticketing_type", "itop"),
            ticketing_config,
        )
        self.poll_interval = bridge_config.get("poll_interval", 60)
        self.batch_size = bridge_config.get("batch_size", 50)
        self.dedup_window = bridge_config.get("dedup_window", 3600)
        self.state_file = bridge_config.get("state_file", "/var/lib/siem-ticket-bridge/state.json")
        self.severity_map_file = bridge_config.get("severity_map_file", "severity_map.json")

        self._running = False
        self._processed_alerts: Set[str] = set()
        self._alert_count = 0
        self._ticket_count = 0
        self._error_count = 0

        # Load state
        self._load_state()

        # Setup signal handlers
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

    def _handle_signal(self, signum, frame):
        """Handle shutdown signals gracefully."""
        logger.info("Received signal %d, shutting down...", signum)
        self._running = False

    def _load_state(self) -> None:
        """Load processed alert IDs from state file."""
        try:
            state = load_json_config(self.state_file)
            self._processed_alerts = set(state.get("processed_alerts", []))
            self._alert_count = state.get("alert_count", 0)
            self._ticket_count = state.get("ticket_count", 0)
            self._error_count = state.get("error_count", 0)
            logger.info("Loaded state: %d processed alerts", len(self._processed_alerts))
        except Exception:
            logger.debug("No state file found, starting fresh")

    def _save_state(self) -> None:
        """Save processed alert IDs to state file."""
        state = {
            "processed_alerts": list(self._processed_alerts)[:10000],
            "alert_count": self._alert_count,
            "ticket_count": self._ticket_count,
            "error_count": self._error_count,
            "last_poll": datetime.now(timezone.utc).isoformat(),
        }
        save_json_config(self.state_file, state)

    def _is_duplicate(self, alert: Dict[str, Any]) -> bool:
        """Check if an alert was already processed within the dedup window."""
        dedup_key = f"{alert.get('rule_id')}:{alert.get('source_ip')}:{alert.get('timestamp', '')[:16]}"
        return dedup_key in self._processed_alerts

    def _mark_processed(self, alert: Dict[str, Any]) -> None:
        """Mark an alert as processed."""
        dedup_key = f"{alert.get('rule_id')}:{alert.get('source_ip')}:{alert.get('timestamp', '')[:16]}"
        self._processed_alerts.add(dedup_key)
        # Prune old entries to prevent unbounded growth
        if len(self._processed_alerts) > 50000:
            self._processed_alerts = set(list(self._processed_alerts)[-25000:])

    def _should_create_ticket(self, alert: Dict[str, Any]) -> bool:
        """Determine if an alert should create a ticket based on severity."""
        level = alert.get("level", 0)
        # Only create tickets for medium+ severity (level >= 4)
        return level >= 4

    def poll_and_create(self) -> Dict[str, Any]:
        """
        Single poll cycle: fetch alerts, deduplicate, create tickets.

        Returns stats dict.
        """
        stats = {"fetched": 0, "new": 0, "tickets_created": 0, "errors": 0, "duplicates": 0}

        # Check connectivity
        siem_ok = self.siem.is_connected()
        ticketing_ok = self.ticketing.is_connected()

        if not siem_ok:
            logger.warning("SIEM not connected, skipping poll")
            return stats

        if not ticketing_ok:
            logger.warning("Ticketing system not connected, skipping poll")
            return stats

        # Fetch alerts
        alerts = self.siem.safe_fetch_alerts(limit=self.batch_size)
        stats["fetched"] = len(alerts)

        for alert in alerts:
            if self._is_duplicate(alert):
                stats["duplicates"] += 1
                continue

            if not self._should_create_ticket(alert):
                self._mark_processed(alert)
                continue

            # Create ticket
            ticket_id = self.ticketing.safe_create_ticket(alert)
            if ticket_id:
                stats["tickets_created"] += 1
                self._ticket_count += 1
                logger.info("Created ticket %s for alert level %d", ticket_id, alert.get("level"))
            else:
                stats["errors"] += 1
                self._error_count += 1

            self._mark_processed(alert)
            self._alert_count += 1

        self._save_state()
        return stats

    def run(self) -> None:
        """Run the bridge in polling mode."""
        self._running = True
        logger.info("Bridge starting: SIEM=%s, Ticketing=%s, Poll=%ds",
                     self.siem.__class__.__name__,
                     self.ticketing.__class__.__name__,
                     self.poll_interval)

        while self._running:
            try:
                stats = self.poll_and_create()
                if stats["fetched"] > 0:
                    logger.info("Poll: fetched=%d new=%d tickets=%d errors=%d dupes=%d",
                                stats["fetched"],
                                stats["fetched"] - stats["duplicates"],
                                stats["tickets_created"],
                                stats["errors"],
                                stats["duplicates"])
            except Exception as e:
                logger.error("Poll cycle error: %s", e)

            # Sleep in small increments for responsive shutdown
            slept = 0
            while slept < self.poll_interval and self._running:
                time.sleep(1)
                slept += 1

        logger.info("Bridge stopped. Total: alerts=%d tickets=%d errors=%d",
                     self._alert_count, self._ticket_count, self._error_count)

    def run_once(self) -> Dict[str, Any]:
        """Run a single poll cycle (for testing)."""
        return self.poll_and_create()

    def status(self) -> Dict[str, Any]:
        """Return current bridge status."""
        return {
            "siem_connected": self.siem.is_connected(),
            "siem_type": self.siem.__class__.__name__,
            "ticketing_connected": self.ticketing.is_connected(),
            "ticketing_type": self.ticketing.__class__.__name__,
            "poll_interval": self.poll_interval,
            "processed_alerts": len(self._processed_alerts),
            "alert_count": self._alert_count,
            "ticket_count": self._ticket_count,
            "error_count": self._error_count,
        }


def setup_logging(level: str = "INFO", log_file: str = None) -> None:
    """Configure logging for the bridge."""
    log_level = getattr(logging, level.upper(), logging.INFO)
    handlers = [logging.StreamHandler()]

    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_file, maxBytes=10 * 1024 * 1024, backupCount=5,
        )
        handlers.append(file_handler)

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        handlers=handlers,
    )


def main():
    """Entry point for the bridge."""
    import argparse

    parser = argparse.ArgumentParser(description="SIEM-to-Ticketing Bridge")
    parser.add_argument("--env-file", default=".env", help="Path to .env config file")
    parser.add_argument("--once", action="store_true", help="Run a single poll and exit")
    parser.add_argument("--status", action="store_true", help="Show status and exit")
    parser.add_argument("--test-connection", action="store_true", help="Test SIEM and ticketing connections")
    args = parser.parse_args()

    # Load config
    load_env_file(args.env_file)
    siem_cfg = build_siem_config()
    ticketing_cfg = build_ticketing_config()
    bridge_cfg = build_bridge_config()

    setup_logging(bridge_cfg.get("log_level", "INFO"), bridge_cfg.get("log_file"))

    bridge = Bridge(siem_cfg, ticketing_cfg, bridge_cfg)

    if args.status:
        print(json.dumps(bridge.status(), indent=2))
        return

    if args.test_connection:
        status = bridge.status()
        print(json.dumps(status, indent=2))
        if status["siem_connected"] and status["ticketing_connected"]:
            print("OK: Both SIEM and ticketing connected")
        else:
            print("FAIL: Check connectivity")
            if not status["siem_connected"]:
                print("  - SIEM not reachable")
            if not status["ticketing_connected"]:
                print("  - Ticketing system not reachable")
        return

    if args.once:
        stats = bridge.run_once()
        print(json.dumps(stats, indent=2))
        return

    bridge.run()


if __name__ == "__main__":
    main()
