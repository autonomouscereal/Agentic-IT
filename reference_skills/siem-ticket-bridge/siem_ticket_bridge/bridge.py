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
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, List

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
        self.max_tickets_per_poll = bridge_config.get("max_tickets_per_poll", 10)
        self.dedup_window = bridge_config.get("dedup_window", 3600)
        self.processed_retention_seconds = bridge_config.get("processed_retention_seconds", 86400)
        self.max_processed_alerts = bridge_config.get("max_processed_alerts", 20000)
        self.correlation_window = bridge_config.get("correlation_window", 300)
        self.state_file = bridge_config.get("state_file", "/var/lib/siem-ticket-bridge/state.json")
        self.severity_map_file = bridge_config.get("severity_map_file", "severity_map.json")
        self.suppression_rules_file = bridge_config.get(
            "suppression_rules_file",
            "/etc/siem-ticket-bridge/suppression_rules.json",
        )

        self._running = False
        self._processed_alerts: Dict[str, str] = {}
        self._alert_count = 0
        self._ticket_count = 0
        self._error_count = 0
        self._suppressed_count = 0
        self._backpressure_count = 0
        self._ticket_correlation_keys: Dict[str, Dict[str, Any]] = {}
        self._last_poll = ""

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
            processed = state.get("processed_alerts", {})
            if isinstance(processed, dict):
                self._processed_alerts = processed
            elif isinstance(processed, list):
                now = datetime.now(timezone.utc).isoformat()
                self._processed_alerts = {str(item): now for item in processed}
            self._alert_count = state.get("alert_count", 0)
            self._ticket_count = state.get("ticket_count", 0)
            self._error_count = state.get("error_count", 0)
            self._suppressed_count = state.get("suppressed_count", 0)
            self._backpressure_count = state.get("backpressure_count", 0)
            self._last_poll = state.get("last_poll", "")
            correlations = state.get("ticket_correlation_keys", {})
            if isinstance(correlations, dict):
                self._ticket_correlation_keys = correlations
            logger.info("Loaded state: %d processed alerts", len(self._processed_alerts))
        except Exception:
            logger.debug("No state file found, starting fresh")

    def _save_state(self) -> None:
        """Save processed alert IDs to state file."""
        self._prune_processed_alerts()
        state = {
            "processed_alerts": self._processed_alerts,
            "alert_count": self._alert_count,
            "ticket_count": self._ticket_count,
            "error_count": self._error_count,
            "suppressed_count": self._suppressed_count,
            "backpressure_count": self._backpressure_count,
            "ticket_correlation_keys": self._ticket_correlation_keys,
            "last_poll": datetime.now(timezone.utc).isoformat(),
        }
        save_json_config(self.state_file, state)
        self._last_poll = state["last_poll"]

    def _dedup_key(self, alert: Dict[str, Any]) -> str:
        return f"{alert.get('rule_id')}:{alert.get('source_ip')}:{alert.get('timestamp', '')[:16]}"

    def _parse_timestamp(self, value: str) -> datetime:
        if not value:
            return datetime.now(timezone.utc)
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed
        except ValueError:
            return datetime.now(timezone.utc)

    def _prune_processed_alerts(self) -> None:
        """Keep dedupe state bounded by age and count."""
        if not self._processed_alerts:
            return
        now = datetime.now(timezone.utc)
        cutoff = now.timestamp() - max(1, int(self.processed_retention_seconds))
        kept = {}
        for key, seen_at in self._processed_alerts.items():
            if self._parse_timestamp(seen_at).timestamp() >= cutoff:
                kept[key] = seen_at
        max_items = max(1, int(self.max_processed_alerts))
        if len(kept) > max_items:
            newest = sorted(kept.items(), key=lambda item: item[1])[-max_items:]
            kept = dict(newest)
        self._processed_alerts = kept

    def _extract_marker(self, alert: Dict[str, Any]) -> str:
        """Extract an explicit test/incident marker from alert text when present."""
        text_parts = [
            alert.get("correlation_key", ""),
            alert.get("log", ""),
            alert.get("rule_name", ""),
        ]
        raw = alert.get("raw", {})
        if isinstance(raw, dict):
            text_parts.append(json.dumps(raw, sort_keys=True, default=str)[:5000])
        text = " ".join(str(part or "") for part in text_parts)
        match = re.search(r"\b(CODEX_[A-Z0-9_]+|E2E[-_][A-Za-z0-9_-]+)\b", text)
        return match.group(1) if match else ""

    def _correlation_key(self, alert: Dict[str, Any]) -> str:
        """Return a cross-rule incident correlation key, or empty string if none applies."""
        explicit = str(alert.get("correlation_key") or "").strip()
        if explicit:
            return f"explicit:{explicit}"
        marker = self._extract_marker(alert)
        if marker:
            return f"marker:{marker}"
        return ""

    def _is_duplicate(self, alert: Dict[str, Any]) -> bool:
        """Check if an alert was already processed within the dedup window."""
        return self._dedup_key(alert) in self._processed_alerts

    def _mark_processed(self, alert: Dict[str, Any]) -> None:
        """Mark an alert as processed."""
        self._processed_alerts[self._dedup_key(alert)] = datetime.now(timezone.utc).isoformat()
        if len(self._processed_alerts) > int(self.max_processed_alerts):
            self._prune_processed_alerts()

    def _load_suppression_rules(self) -> List[Dict[str, Any]]:
        """Load approval-gated false-positive suppression rules."""
        try:
            data = load_json_config(self.suppression_rules_file)
        except Exception:
            return []
        rules = data.get("rules", data) if isinstance(data, dict) else data
        return rules if isinstance(rules, list) else []

    def _alert_text(self, alert: Dict[str, Any]) -> str:
        parts = [
            alert.get("rule_id", ""),
            alert.get("rule_name", ""),
            alert.get("agent_name", ""),
            alert.get("source_ip", ""),
            alert.get("destination_ip", ""),
            alert.get("log", ""),
        ]
        raw = alert.get("raw")
        if isinstance(raw, dict):
            parts.append(json.dumps(raw, sort_keys=True, default=str)[:5000])
        return " ".join(str(part or "") for part in parts).lower()

    def _is_suppressed(self, alert: Dict[str, Any]) -> Dict[str, Any]:
        """Return the precise approved suppression rule that matches this alert."""
        text = self._alert_text(alert)
        now = datetime.now(timezone.utc)
        for rule in self._load_suppression_rules():
            if not isinstance(rule, dict) or not rule.get("enabled", True):
                continue
            if not rule.get("approved_by") or not rule.get("reason"):
                continue
            expires_at = rule.get("expires_at")
            if expires_at and self._parse_timestamp(expires_at) <= now:
                continue
            rule_id = str(rule.get("rule_id") or "").strip()
            if rule_id and rule_id != str(alert.get("rule_id") or ""):
                continue
            agent_name = str(rule.get("agent_name") or "").strip().lower()
            if agent_name and agent_name != str(alert.get("agent_name") or "").strip().lower():
                continue
            contains = rule.get("field_contains") or rule.get("contains") or []
            if isinstance(contains, str):
                contains = [contains]
            terms = [str(item).strip().lower() for item in contains if str(item).strip()]
            if terms and not all(term in text for term in terms):
                continue
            if not rule_id and not terms:
                continue
            return rule
        return {}

    def _existing_correlated_ticket(self, alert: Dict[str, Any]) -> Dict[str, Any]:
        """Return existing ticket metadata for a correlated alert group."""
        key = self._correlation_key(alert)
        if not key:
            return {}
        existing = self._ticket_correlation_keys.get(key)
        return existing if isinstance(existing, dict) else {}

    def _mark_correlated_ticket(self, alert: Dict[str, Any], ticket_id: str) -> None:
        """Remember which ticket owns this alert correlation group."""
        key = self._correlation_key(alert)
        if not key:
            return
        current = self._ticket_correlation_keys.get(key, {})
        rules = set(current.get("rules", [])) if isinstance(current, dict) else set()
        rules.add(str(alert.get("rule_id", "")))
        now = datetime.now(timezone.utc).isoformat()
        self._ticket_correlation_keys[key] = {
            "ticket_id": str(ticket_id),
            "first_seen": current.get("first_seen") if isinstance(current, dict) else now,
            "last_seen": alert.get("timestamp") or now,
            "alert_count": int(current.get("alert_count", 0)) + 1 if isinstance(current, dict) else 1,
            "rules": sorted(rule for rule in rules if rule),
        }
        if len(self._ticket_correlation_keys) > 10000:
            keys = list(self._ticket_correlation_keys)[-5000:]
            self._ticket_correlation_keys = {key: self._ticket_correlation_keys[key] for key in keys}

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
        stats = {
            "fetched": 0,
            "new": 0,
            "tickets_created": 0,
            "errors": 0,
            "duplicates": 0,
            "correlated": 0,
            "suppressed": 0,
            "backpressure_deferred": 0,
        }

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

            suppression = self._is_suppressed(alert)
            if suppression:
                stats["suppressed"] += 1
                self._suppressed_count += 1
                logger.info(
                    "Suppressed alert rule %s by approved rule %s: %s",
                    alert.get("rule_id"),
                    suppression.get("id", "unnamed"),
                    suppression.get("reason"),
                )
                self._mark_processed(alert)
                continue

            if not self._should_create_ticket(alert):
                self._mark_processed(alert)
                continue

            if (
                self.max_tickets_per_poll > 0
                and stats["tickets_created"] >= self.max_tickets_per_poll
            ):
                stats["backpressure_deferred"] += 1
                self._backpressure_count += 1
                logger.warning(
                    "Per-poll ticket cap reached (%d); leaving alert rule %s unprocessed for next poll",
                    self.max_tickets_per_poll,
                    alert.get("rule_id"),
                )
                continue

            existing_ticket = self._existing_correlated_ticket(alert)
            if existing_ticket.get("ticket_id"):
                stats["correlated"] += 1
                logger.info(
                    "Correlated alert rule %s to existing ticket %s",
                    alert.get("rule_id"),
                    existing_ticket.get("ticket_id"),
                )
                self._mark_correlated_ticket(alert, existing_ticket.get("ticket_id"))
                self._mark_processed(alert)
                self._alert_count += 1
                continue

            # Create ticket
            ticket_id = self.ticketing.safe_create_ticket(alert)
            if ticket_id:
                stats["tickets_created"] += 1
                self._ticket_count += 1
                self._mark_correlated_ticket(alert, ticket_id)
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
                    logger.info("Poll: fetched=%d new=%d tickets=%d errors=%d dupes=%d suppressed=%d deferred=%d",
                                stats["fetched"],
                                stats["fetched"] - stats["duplicates"],
                                stats["tickets_created"],
                                stats["errors"],
                                stats["duplicates"],
                                stats["suppressed"],
                                stats["backpressure_deferred"])
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
            "batch_size": self.batch_size,
            "max_tickets_per_poll": self.max_tickets_per_poll,
            "correlation_window": self.correlation_window,
            "processed_alerts": len(self._processed_alerts),
            "processed_retention_seconds": self.processed_retention_seconds,
            "max_processed_alerts": self.max_processed_alerts,
            "ticket_correlation_keys": len(self._ticket_correlation_keys),
            "alert_count": self._alert_count,
            "ticket_count": self._ticket_count,
            "error_count": self._error_count,
            "suppressed_count": self._suppressed_count,
            "backpressure_count": self._backpressure_count,
            "last_poll": self._last_poll,
            "suppression_rules_file": self.suppression_rules_file,
        }


def setup_logging(level: str = "INFO", log_file: str = None,
                  max_bytes: int = 10 * 1024 * 1024, backup_count: int = 5) -> None:
    """Configure logging for the bridge."""
    log_level = getattr(logging, level.upper(), logging.INFO)
    handlers = [logging.StreamHandler()]

    if log_file:
        log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=max(1024 * 1024, int(max_bytes or 10 * 1024 * 1024)),
            backupCount=max(1, int(backup_count or 5)),
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

    setup_logging(
        bridge_cfg.get("log_level", "INFO"),
        bridge_cfg.get("log_file"),
        bridge_cfg.get("log_max_bytes", 10 * 1024 * 1024),
        bridge_cfg.get("log_backup_count", 5),
    )

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
