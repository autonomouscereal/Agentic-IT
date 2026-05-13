---
name: siem-ticket-bridge
description: Manage the SIEM-to-Ticketing Bridge integration between Wazuh SIEM and iTop ITSM on AI Server (192.168.50.222). Deploy, configure, test, and manage the fully modular polling daemon that auto-creates iTop incidents from Wazuh alerts. All operations via Server Manager v2 SSH client.
when_to_use: SIEM-to-ticketing integration, Wazuh-to-iTop bridge, automatic ticket creation from security alerts, alert polling daemon, severity mapping, alert deduplication, systemd service management, Docker deployment, adding new SIEM or ticketing backends.
allowed-tools: Bash(python *) Bash(ssh_client.py *) Read, Edit, Write, Glob, Grep
---

# SIEM-to-Ticketing Bridge Manager

Fully modular, tool-agnostic integration framework between any SIEM (Wazuh, Splunk) and any ticketing system (iTop, Jira, ServiceNow). Zero hardcoded dependencies. Deployed at `/home/cereal/SOC_TESTING/siem-ticket-bridge/` on AI Server.

Full deployment blueprint in [BLUEPRINT.md](./BLUEPRINT.md).

## SSH Client

All remote operations use Server Manager v2:
```bash
python "C:/Users/cereal/.agents/skills/server-manager/ssh_client.py" --server ai --execute "command"
```

Upload files:
```bash
python "C:/Users/cereal/.agents/skills/server-manager/ssh_client.py" --server ai --upload "local/path" "remote/path"
```

## Quick Operations

| Operation | Command |
|-----------|---------|
| Test connectivity | `...ssh_client.py" --server ai --execute "cd /home/cereal/SOC_TESTING/siem-ticket-bridge && source .env && python3 -m siem_ticket_bridge.bridge --test-connection"` |
| Single poll | `...ssh_client.py" --server ai --execute "cd /home/cereal/SOC_TESTING/siem-ticket-bridge && source .env && python3 -m siem_ticket_bridge.bridge --once"` |
| Check status | `...ssh_client.py" --server ai --execute "cd /home/cereal/SOC_TESTING/siem-ticket-bridge && source .env && python3 -m siem_ticket_bridge.bridge --status"` |
| Run unit tests | `...ssh_client.py" --server ai --execute "cd /home/cereal/SOC_TESTING/siem-ticket-bridge && PYTHONPATH=. python3 -m unittest tests.test_bridge -v"` |
| Run E2E test | `...ssh_client.py" --server ai --execute "cd /home/cereal/SOC_TESTING/siem-ticket-bridge && PYTHONPATH=. python3 tests/test_ticket_e2e.py"` |
| Start daemon | `...ssh_client.py" --server ai --execute "cd /home/cereal/SOC_TESTING/siem-ticket-bridge && source .env && python3 -m siem_ticket_bridge.bridge"` |
| View logs | `...ssh_client.py" --server ai --execute "tail -50 /var/log/siem-ticket-bridge/bridge.log"` |
| Check state | `...ssh_client.py" --server ai --execute "cat /var/lib/siem-ticket-bridge/state.json"` |
| systemd status | `...ssh_client.py" --server ai --execute "systemctl status siem-ticket-bridge"` |
| Start systemd service | `...ssh_client.py" --server ai --execute "sudo systemctl start siem-ticket-bridge"` |
| Docker deploy | `...ssh_client.py" --server ai --execute "cd /home/cereal/SOC_TESTING/siem-ticket-bridge/deploy && docker-compose up -d"` |

## Architecture

```
Wazuh SIEM (port 26500/26920) ──> Bridge Orchestrator (polling daemon) ──> iTop ITSM (port 25432)
```

- **Abstract Connector Pattern**: `SIEMConnector` and `TicketingConnector` base classes with `NullConnector` fallbacks
- **Factory Pattern**: `create_connector()` factories with pluggable registration via `register_connector()`
- **Null Connectors**: Gracefully handle missing/disconnected systems without crashing
- **Env-Only Config**: All credentials via `.env` file, zero hardcoded secrets
- **Stdlib Only**: Python standard library — no pip dependencies
- **Deduplication + Correlation**: Exact alert dedup plus cross-rule incident correlation with configurable time windows and JSON state persistence. Explicit `correlation_key` values and markers such as `CODEX_*` collapse related alerts into one ticket.
- **Backpressure Controls**: `BRIDGE_BATCH_SIZE` limits Wazuh fetch size and
  `BRIDGE_MAX_TICKETS_PER_POLL` limits ticket creation bursts. Deferred alerts
  are not marked processed, so later polls can pick them up after capacity clears.
- **False-Positive Suppression Rules**: `BRIDGE_SUPPRESSION_RULES_FILE` points
  to approved precise suppression rules. Rules must have `approved_by`,
  `reason`, and exact match criteria such as `rule_id` plus `field_contains`;
  disabled/example rules do nothing.
- **Log Retention**: `BRIDGE_LOG_MAX_BYTES` and `BRIDGE_LOG_BACKUP_COUNT`
  configure the Python rotating handler. The deploy assets also install
  `/etc/logrotate.d/siem-ticket-bridge` for system-level log retention.

### Severity Mapping

| Wazuh Level | Severity | iTop Impact | iTop Urgency |
|---|---|---|---|
| 13-15 | emergency | 3 | 4 |
| 11-12 | critical | 3 | 3 |
| 7-10 | high | 2 | 3 |
| 4-6 | medium | 2 | 2 |
| 0-3 | low | 1 | 1 |

Tickets only created for level >= 4 (medium and above).

## Directory Structure

```
siem-ticket-bridge/
├── siem_ticket_bridge/
│   ├── config.py              # Env var loading, config builders
│   ├── bridge.py              # Main orchestrator + CLI
│   ├── siem/
│   │   ├── connector.py       # Abstract SIEMConnector + NullConnector
│   │   ├── wazuh_connector.py # Wazuh v4.14.4 implementation
│   │   └── splunk_connector.py # Splunk HEC example
│   └── ticketing/
│       ├── connector.py       # Abstract TicketingConnector + NullTicketingConnector
│       └── itop_connector.py  # iTop v3.2.1 implementation
├── tests/
│   ├── test_bridge.py         # 40-unit test suite
│   └── test_ticket_e2e.py     # E2E ticket creation test
├── deploy/
│   ├── deploy.sh              # One-shot deployment script
│   ├── Dockerfile             # Container deployment
│   ├── docker-compose.yml     # Docker Compose stack
│   └── systemd/
│       └── siem-ticket-bridge.service
├── .env                       # Live credentials
├── .env.example               # Template with all env vars
├── severity_map.json          # Severity definitions + rule overrides
└── BLUEPRINT.md               # Deployment blueprint
```

## Critical iTop API Rules

1. **`code: 0` means success** — iTop returns `"code": 0` for success (NOT 200). All result checks must compare against `0`.
2. **Max urgency is 4** — iTop rejects urgency values > 4. Severity map must cap at 4.
3. **Dual authentication required** — Both Basic Auth header AND payload credentials (`user` + `password` fields in JSON).
4. **Object key extraction** — Response key may be in `val["key"]`, `val["fields"]["key"]`, or parseable from `"Incident::77"` style top-level key.
5. **Exception handler must NOT return `code: 0`** — Use `code: -1` for errors.

## Critical Wazuh Indexer Rules

1. **Time window defaults to 1 hour back** — `fetch_alerts()` must default `since` to `now - 1 hour`, NOT `now` (otherwise 0 results).
2. **Indexer uses separate credentials** — Manager API (port 26500) and Indexer (port 26920) have different auth.
3. **Index naming** — Uses `wazuh-alerts-4.x-{YYYY.MM.DD}` pattern with daily rollover.

## Configuration

All via `.env` file on server. Key prefixes:
- `BRIDGE_SIEM_*` — Wazuh host, ports, API/indexer credentials
- `BRIDGE_TICKETING_*` — iTop host, port, credentials, scheme, API path
- `BRIDGE_*` — poll interval, log level, state file, dedup window, correlation window
- `BRIDGE_CORRELATION_WINDOW` — default `300` seconds; related cross-rule alerts with an explicit marker/correlation key are attached to the first ticket instead of creating duplicate tickets
- `BRIDGE_MAX_TICKETS_PER_POLL` — default `10`; prevents iTop/dashboard ticket floods during alert bursts
- `BRIDGE_PROCESSED_RETENTION_SECONDS` — default `86400`; age limit for dedupe keys
- `BRIDGE_MAX_PROCESSED_ALERTS` — default `20000`; count limit for dedupe keys
- `BRIDGE_SUPPRESSION_RULES_FILE` — approved precise false-positive suppression rules

## Adding New Backends

### New SIEM Connector
1. Create `siem_ticket_bridge/siem/my_connector.py` implementing `SIEMConnector`
2. Register in `siem_ticket_bridge/siem/__init__.py`: `register_connector("my", MyConnector)`
3. Set `BRIDGE_SIEM_TYPE=my` in .env

### New Ticketing Connector
1. Create `siem_ticket_bridge/ticketing/my_connector.py` implementing `TicketingConnector`
2. Register in `siem_ticket_bridge/ticketing/__init__.py`: `register_connector("my", MyConnector)`
3. Set `BRIDGE_TICKETING_TYPE=my` in .env

## Health, Rotation, and False Positives

Reference health check:

```bash
cd /home/cereal/SOC_TESTING/siem-ticket-bridge
source .env
python3 deploy/check_bridge_health.py
```

False-positive handling:

1. Prove benign context from ticket evidence, rule metadata, and telemetry.
2. Write a ticket note with rule id, exact benign pattern, checked evidence,
   residual risk, and why no containment is required.
3. Propose suppression only through a change request with exact match criteria,
   expiry/review date, rollback, and tests that malicious variants still alert.
4. Never blanket-suppress a phishing, EDR, or SIEM rule.

Verified 2026-05-13: deterministic false-positive smoke created ticket `429`,
change `124`, postmortem `63`, and workflow `59`; fresh Sysmon marker created
iTop Incident `275`, dashboard ticket `431`, auto-assigned agent `151`, and
resolved both dashboard and iTop after classification.

## Test Suite

40 total tests in `test_bridge.py` (37 pass + 3 live tests skipped by default):
- Config loading/env parsing
- SIEM connector init and null connector
- Ticketing connector init and null connector
- Bridge orchestrator, deduplication, severity mapping
- State persistence and CLI arguments

Plus E2E test in `test_ticket_e2e.py` (live alert injection + ticket creation).

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ticketing_connected: false` | iTop API unreachable or wrong creds | Verify port 25432, check .env creds |
| `siem_connected: false` | Wazuh manager API down | Check `docker ps`, verify port 26500 |
| 0 alerts fetched | No alerts in last hour | Normal for idle systems |
| 0 tickets created | All alerts below level 4 | Expected; only medium+ creates tickets |
| `Permission denied: /var/log/` | Log directory missing | `sudo mkdir -p /var/log/siem-ticket-bridge` |
| `Value not allowed [5]` | Urgency overflow | Verify severity map caps at 4 |
| Stale `.pyc` cache | Old cached bytecode | `find . -type d -name __pycache__ -exec rm -rf {} +` |
