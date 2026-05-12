# SIEM-to-Ticketing Bridge - Deployment Blueprint

> Fully modular, tool-agnostic integration framework between any SIEM (Wazuh, Splunk) and any ticketing system (iTop, Jira, ServiceNow). Zero hardcoded dependencies.

## Architecture

```
+--------------+     +---------------------+     +--------------+
|   Wazuh SIEM |---->|   Bridge Orchestrator|---->|  iTop ITSM   |
|  (port 26500)|     |  (polling daemon)    |     | (port 25432) |
|  Indexer:920 |     |                      |     |              |
`--------------'     |  - Deduplication     |     `--------------'
                     |  - Severity filter   |
                     |  - State persistence |
                     `---------------------'
```

### Key Design Decisions

- **Abstract Connector Pattern**: `SIEMConnector` and `TicketingConnector` base classes with `NullConnector` fallbacks
- **Factory Pattern**: `create_connector()` factories with pluggable registration via `register_connector()`
- **Null Connectors**: Gracefully handle missing/disconnected systems without crashing
- **Env-Only Config**: All credentials via `.env` file, zero hardcoded secrets
- **Stdlib Only**: Python standard library - no pip dependencies required
- **Deduplication**: Alert dedup with configurable time windows and JSON state persistence

### Severity Mapping

| Wazuh Level | Severity | iTop Impact | iTop Urgency |
|---|---|---|---|
| 13-15 | emergency | 3 | 4 |
| 11-12 | critical | 3 | 3 |
| 7-10 | high | 2 | 3 |
| 4-6 | medium | 2 | 2 |
| 0-3 | low | 1 | 1 |

Tickets only created for level >= 4 (medium and above).

## File Structure

```
siem-ticket-bridge/
|-- siem_ticket_bridge/
|   |-- __init__.py
|   |-- config.py              # Env var loading, config builders
|   |-- bridge.py              # Main orchestrator + CLI
|   |-- siem/
|   |   |-- __init__.py        # SIEM factory + register_connector()
|   |   |-- connector.py       # Abstract SIEMConnector + NullConnector
|   |   |-- wazuh_connector.py # Wazuh v4.14.4 implementation
|   |   `-- splunk_connector.py # Splunk HEC example
|   `-- ticketing/
|       |-- __init__.py        # Ticketing factory + register_connector()
|       |-- connector.py       # Abstract TicketingConnector + NullTicketingConnector
|       `-- itop_connector.py  # iTop v3.2.1 implementation
|-- tests/
|   |-- test_bridge.py         # 40-unit test suite
|   `-- test_ticket_e2e.py     # E2E ticket creation test
|-- deploy/
|   |-- deploy.sh              # One-shot deployment script
|   |-- Dockerfile             # Container deployment
|   |-- docker-compose.yml     # Docker Compose stack
|   `-- systemd/
|       `-- siem-ticket-bridge.service
|-- .env.example               # Template with all env vars
|-- severity_map.json          # Severity definitions + rule overrides
`-- BLUEPRINT.md               # This file
```

## Prerequisites

- Python 3.11+ (stdlib only, no pip needed)
- Wazuh v4.14.4 deployed (Docker or bare metal)
- iTop v3.2.1 deployed (Docker or bare metal)
- Network access from bridge host to both SIEM and ticketing APIs

## Deployment Steps

### 1. Copy Framework to Target Host

```bash
# Deploy directory on AI Server (127.0.0.1)
DEPLOY_DIR="/opt/agentic-it/SOC_TESTING/siem-ticket-bridge"
```

### 2. Create Required Directories

```bash
sudo mkdir -p /var/log/siem-ticket-bridge /var/lib/siem-ticket-bridge
sudo chown $USER:$USER /var/log/siem-ticket-bridge /var/lib/siem-ticket-bridge
```

### 3. Configure .env

```bash
cp .env.example .env
# Edit .env with actual credentials:
#   BRIDGE_SIEM_TYPE=wazuh
#   BRIDGE_SIEM_HOST=127.0.0.1
#   BRIDGE_SIEM_PORT=26500
#   BRIDGE_SIEM_API_USER=<wazuh_api_user>
#   BRIDGE_SIEM_API_PASSWORD=<wazuh_api_password>
#   BRIDGE_SIEM_INDEXER_PORT=26920
#   BRIDGE_SIEM_INDEXER_USER=<indexer_user>
#   BRIDGE_SIEM_INDEXER_PASSWORD=<indexer_password>
#   BRIDGE_TICKETING_TYPE=itop
#   BRIDGE_TICKETING_HOST=127.0.0.1
#   BRIDGE_TICKETING_PORT=25432
#   BRIDGE_TICKETING_API_USER=<itop-api-user>
#   BRIDGE_TICKETING_API_PASSWORD=<itop-api-password>
#   BRIDGE_TICKETING_SCHEME=http
#   BRIDGE_TICKETING_API_PATH=/webservices/rest.php
```

### 4. Test Connectivity

```bash
cd /opt/agentic-it/SOC_TESTING/siem-ticket-bridge
source .env
python3 -m siem_ticket_bridge.bridge --test-connection
# Expected: "OK: Both SIEM and ticketing connected"
```

### 5. Run Test Poll

```bash
python3 -m siem_ticket_bridge.bridge --once
# Expected: JSON with fetched alerts count
```

### 6. Run Unit Tests

```bash
PYTHONPATH=. python3 -m unittest tests.test_bridge -v
# Expected: 40 tests, OK (skipped=3 for live tests)
```

### 7. Install systemd Service (Production)

```bash
# Method A: Use deploy script
bash deploy/deploy.sh

# Method B: Manual
sudo sed 's|{{DEPLOY_DIR}}|/opt/agentic-it/SOC_TESTING/siem-ticket-bridge|g; s|{{LOG_DIR}}|/var/log/siem-ticket-bridge|g; s|{{USER}}|cereal|g' \
    deploy/systemd/siem-ticket-bridge.service > /etc/systemd/system/siem-ticket-bridge.service
sudo systemctl daemon-reload
sudo systemctl enable siem-ticket-bridge
sudo systemctl start siem-ticket-bridge
```

### 8. Alternative: Docker Deployment

```bash
cd deploy
docker-compose up -d
```

## Operational Commands

```bash
# Check status
python3 -m siem_ticket_bridge.bridge --status

# Single poll
python3 -m siem_ticket_bridge.bridge --once

# View logs
journalctl -u siem-ticket-bridge -f
# or
tail -f /var/log/siem-ticket-bridge/bridge.log

# Check state
cat /var/lib/siem-ticket-bridge/state.json
```

## Adding New SIEM/Ticketing Backends

### Add a New SIEM Connector

1. Create `siem_ticket_bridge/siem/my_siem_connector.py` implementing `SIEMConnector`
2. Register it in `siem_ticket_bridge/siem/__init__.py`:
   ```python
   from .my_siem_connector import MySIEMConnector
   register_connector("my_siem", MySIEMConnector)
   ```
3. Set `BRIDGE_SIEM_TYPE=my_siem` in .env

### Add a New Ticketing Connector

1. Create `siem_ticket_bridge/ticketing/my_ticketing_connector.py` implementing `TicketingConnector`
2. Register it in `siem_ticket_bridge/ticketing/__init__.py`:
   ```python
   from .my_ticketing_connector import MyTicketingConnector
   register_connector("my_ticketing", MyTicketingConnector)
   ```
3. Set `BRIDGE_TICKETING_TYPE=my_ticketing` in .env

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `ticketing_connected: false` | iTop API unreachable or wrong credentials | Verify port 25432, check .env creds |
| `siem_connected: false` | Wazuh manager API down | Check `docker ps`, verify port 26500 |
| 0 alerts fetched | No alerts in last hour | Normal for idle systems; check indexer |
| 0 tickets created | All alerts below level 4 | Expected; only medium+ creates tickets |
| `Permission denied: /var/log/` | Log directory missing | `sudo mkdir -p /var/log/siem-ticket-bridge` |
| `Value not allowed [5]` for urgency | iTop urgency max is 4 | Use corrected severity map (urgency capped at 4) |

## Known Bugs Fixed During Development

1. **iTop code check**: iTop API returns `"code": 0` for success (not 200). Fixed `_check_connectivity` and all result checks.
2. **Time window**: `fetch_alerts()` defaulted `since` to current time (always 0 results). Fixed to look back 1 hour.
3. **Missing config keys**: `scheme` and `api_path` were not in `TICKETING_ENV_MAP`. Added with defaults.
4. **Urgency overflow**: iTop max urgency is 4, not 5. Corrected severity map.
5. **Key extraction**: iTop response key extraction failed on certain response structures. Added fallback parsing.
6. **Exception masking**: `_post` returned `{"code": 0, "error": ...}` on exceptions. Changed to `code: -1`.
