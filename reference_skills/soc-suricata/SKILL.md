---
name: soc-suricata
description: Suricata IDS/IPS management for SOC testing with eve.json logging. Use when viewing alerts, checking capture status, analyzing traffic events, or managing the intrusion detection system.
allowed-tools: Read Bash
---

# Suricata Skill - IDS/IPS Management

## Quick Commands

### Check Status
```bash
docker exec suricata-soc pgrep -a suricata || docker ps | grep suricata
```

### View eve.json Logs
```bash
docker exec suricata-soc tail -20 /var/log/suricata/eve.json
```

## Event Types in eve.json

| Type | Description |
|------|-------------|
| alert | Signature match alerts |
| dns | DNS queries/responses |
| http | HTTP traffic |
| tls | TLS handshake data |
| files | File transfer metadata |
| flow | Connection flow data |
| ssh | SSH session data |

## Management API

### suricatasc (Command Socket)
```bash
docker exec -it suricata-soc suricatasc
```

Common commands:
- `version` - Show Suricata version
- `stats` - Get statistics
- `ruleset-reload` - Reload rule sets

## Log Files

| File | Purpose |
|------|---------|
| eve.json | JSON events (primary) |
| fast.log | Alert summaries |
| stats.log | Performance metrics |
| suricata.log | Runtime logs |

---

## Wazuh Integration

Suricata eve.json is forwarded to Wazuh for centralized alerting. Suricata works completely standalone — if Wazuh goes down, Suricata keeps capturing.

### How it Works

1. Suricata produces JSON events at `/home/cereal/SOC_TESTING/logs/suricata/eve.json`
2. Wazuh manager monitors this file via `<localfile>` config (JSON format)
3. Wazuh's built-in JSON decoder extracts all fields (`event_type`, `alert.severity`, `src_ip`, etc.)
4. Enhanced rules (86700+) match on Suricata-specific fields to generate alerts

### Suricata Rules in Wazuh

| Rule ID | Level | Description |
|---------|-------|-------------|
| 86710 | 7 | HIGH severity alerts (severity 4) |
| 86711 | 12 | CRITICAL severity alerts (severity 5) |
| 86712 | 15 | EMERGENCY severity alerts (severity 6) |
| 86720 | 5 | Dropped packets |
| 86721 | 5 | Rejected connections |
| 86730 | 5 | HTTP errors (4xx/5xx) |
| 86740 | 7 | DNS NXDOMAIN |
| 86750 | 7 | Deprecated TLS 1.0 |
| 86751 | 5 | Self-signed TLS certs |

### If Wazuh is Down

- Suricata continues capturing and writing eve.json normally
- The log forwarder (if running) buffers and retries with backoff
- No log loss — Wazuh reads from file positions on reconnect

### Testing Suricata → Wazuh

```bash
# Test a Suricata alert against Wazuh rules (run on AI Server)
docker exec wazuh_deploy-wazuh.manager-1 bash -c 'echo "{\"timestamp\":\"2026-04-27T01:00:00.000000+0000\",\"event_type\":\"alert\",\"src_ip\":\"10.0.0.5\",\"dest_ip\":\"10.0.0.6\",\"alert\":{\"signature\":\"ET TEST Alert\",\"severity\":4}}" | /var/ossec/bin/wazuh-logtest'

# Expected: Rule 86710 fires (level 7, "Suricata: HIGH severity")

# Run full integration tests
cd /home/cereal/SOC_TESTING/log_forwarder && python3 test_integration.py
```
