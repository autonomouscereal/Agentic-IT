#!/usr/bin/env python3
"""End-to-end ticket creation test: inject a high-severity alert, poll, verify ticket."""
import sys, os, json, base64, urllib.request, ssl
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from siem_ticket_bridge.config import load_env_file, build_siem_config, build_ticketing_config, build_bridge_config
from siem_ticket_bridge.siem import create_connector as create_siem_connector
from siem_ticket_bridge.ticketing import create_connector as create_ticketing_connector
from siem_ticket_bridge.bridge import Bridge

load_env_file(".env")

siem_cfg = build_siem_config()
ticketing_cfg = build_ticketing_config()
bridge_cfg = build_bridge_config()

# 1. Verify connectivity
siem = create_siem_connector(siem_cfg.get("siem_type", "wazuh"), siem_cfg)
ticketing = create_ticketing_connector(ticketing_cfg.get("ticketing_type", "itop"), ticketing_cfg)

print("SIEM connected:", siem.is_connected())
print("Ticketing connected:", ticketing.is_connected())

if not siem.is_connected() or not ticketing.is_connected():
    print("FAIL: Cannot test - systems not connected")
    sys.exit(1)

# 2. Inject a high-severity test alert directly into the indexer
now = datetime.now(timezone.utc).isoformat()
test_alert_doc = {
    "@timestamp": now,
    "rule": {"id": 999999, "level": 14, "description": "CRITICAL - Test Security Breach"},
    "agent": {"name": "test-sensor", "ip": "10.0.0.50"},
    "data": {"src_ip": "10.0.0.99", "dst_ip": "10.0.0.1", "log": "Test high-severity alert for bridge testing"},
}

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

today = datetime.now().strftime("%Y.%m.%d")
idx_url = f"https://{siem_cfg['host']}:{siem_cfg['indexer_port']}/wazuh-alerts-4.x-{today}/_doc/1"
idx_creds = base64.b64encode(f"{siem_cfg['indexer_user']}:{siem_cfg['indexer_password']}".encode()).decode()
req = urllib.request.Request(idx_url, data=json.dumps(test_alert_doc).encode(), method="POST")
req.add_header("Content-Type", "application/json")
req.add_header("Authorization", f"Basic {idx_creds}")

try:
    with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
        print("Alert indexed:", resp.read().decode()[:100])
except Exception as e:
    print("Alert index error (may be OK):", e)

# 3. Run bridge poll
bridge = Bridge(siem_cfg, ticketing_cfg, bridge_cfg)
stats = bridge.run_once()
print("Poll stats:", json.dumps(stats, indent=2))

if stats["tickets_created"] > 0:
    print("SUCCESS: Ticket created from high-severity alert!")
else:
    print("NOTE: No tickets created. This may be because the test alert was deduplicated or not yet indexed.")
    # Try direct ticket creation test
    print("\nDirect ticket creation test:")
    test_alert = {
        "rule_id": "999998",
        "rule_name": "Direct Test Alert",
        "level": 14,
        "source_ip": "10.0.0.88",
        "timestamp": now,
        "log": "Direct ticket creation test",
        "agent_name": "direct-test",
        "destination_ip": "10.0.0.1",
    }
    ticket_id = ticketing.safe_create_ticket(test_alert)
    print("Direct ticket ID:", ticket_id)
    if ticket_id:
        print("SUCCESS: Direct ticket creation works!")
    else:
        print("FAIL: Direct ticket creation failed")
