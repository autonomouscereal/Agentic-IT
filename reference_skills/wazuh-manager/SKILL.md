# Wazuh Manager Skill - SOC SIEM Management

**Version:** 1.0 | **Wazuh Version:** 4.14.4 | **Last Updated:** 2026-04-23

---

## Overview

Manages the Wazuh SIEM deployment on the AI Server (192.168.50.222). Wazuh provides centralized log analysis, threat detection via rules/decoders, file integrity monitoring (FIM), and a web dashboard. Deployed as 3 Docker containers with non-standard ports (26k+).

---

## Architecture

| Container | Image | Purpose | External Ports |
|-----------|-------|---------|----------------|
| wazuh.manager | wazuh/wazuh-manager:4.14.4 | Event analysis, rule engine, agent mgmt | 26151, 26152, 26500, 26514/udp |
| wazuh.indexer | wazuh/wazuh-indexer:4.14.4 | OpenSearch data store | 26920 |
| wazuh.dashboard | wazuh/wazuh-dashboard:4.14.4 | Web UI (HTTPS) | 26443 |

---

## Deployment Location

- **Server:** 192.168.50.222 (AI Server)
- **Directory:** `/home/cereal/SOC_TESTING/wazuh_deploy/`
- **Python venv:** `/home/cereal/SOC_TESTING/wazuh_deploy/.venv/`

---

## Credentials

| Component | Username | Password Source |
|-----------|----------|-----------------|
| Dashboard | admin | Stored in server-manager vault |
| Indexer (OpenSearch) | admin | Stored in server-manager vault |
| Manager REST API | wazuh-wui | Stored in server-manager vault |

---

## Server Selection

All commands use the `--server ai` flag to target the AI Server.

---

## CLI Command Reference

### Container Lifecycle

```bash
# Start all services
python "C:/Users/cereal/.agents/skills/server-manager/ssh_client.py" --server ai --execute "cd /home/cereal/SOC_TESTING/wazuh_deploy && docker compose up -d"

# Stop all services
python "C:/Users/cereal/.agents/skills/server-manager/ssh_client.py" --server ai --execute "cd /home/cereal/SOC_TESTING/wazuh_deploy && docker compose down"

# Restart single container
python "C:/Users/cereal/.agents/skills/server-manager/ssh_client.py" --server ai --execute "cd /home/cereal/SOC_TESTING/wazuh_deploy && docker compose restart wazuh.manager"

# Force recreate after config changes
python "C:/Users/cereal/.agents/skills/server-manager/ssh_client.py" --server ai --execute "cd /home/cereal/SOC_TESTING/wazuh_deploy && docker compose up -d --force-recreate"

# Check container status
python "C:/Users/cereal/.agents/skills/server-manager/ssh_client.py" --server ai --execute "cd /home/cereal/SOC_TESTING/wazuh_deploy && docker compose ps"
```

### Logs

```bash
# Live manager logs
python "C:/Users/cereal/.agents/skills/server-manager/ssh_client.py" --server ai --execute "cd /home/cereal/SOC_TESTING/wazuh_deploy && docker compose logs -f --tail=50 wazuh.manager"

# Live indexer logs
python "C:/Users/cereal/.agents/skills/server-manager/ssh_client.py" --server ai --execute "cd /home/cereal/SOC_TESTING/wazuh_deploy && docker compose logs -f --tail=50 wazuh.indexer"

# Live dashboard logs
python "C:/Users/cereal/.agents/skills/server-manager/ssh_client.py" --server ai --execute "cd /home/cereal/SOC_TESTING/wazuh_deploy && docker compose logs -f --tail=50 wazuh.dashboard"
```

### Run Tests

```bash
# Run full test suite
python "C:/Users/cereal/.agents/skills/server-manager/ssh_client.py" --server ai --execute "cd /home/cereal/SOC_TESTING/wazuh_deploy && source .venv/bin/activate && pytest test_wazuh.py -v"

# Run client diagnostic
python "C:/Users/cereal/.agents/skills/server-manager/ssh_client.py" --server ai --execute "cd /home/cereal/SOC_TESTING/wazuh_deploy && source .venv/bin/activate && python wazuh_client.py"
```

---

## Wazuh Manager REST API

**Base URL:** `https://192.168.50.222:26500`

All endpoints are at the ROOT level. There is NO `/api/v1/` prefix in v4.14.4.

### Authentication Flow

1. GET `/security/user/authenticate?raw=true` with Basic Auth (user: `wazuh-wui`)
2. Response is a raw JWT token string
3. Use `Authorization: Bearer <token>` header for all subsequent calls
4. Tokens expire after ~15 minutes

### Key Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/agents` | List all registered agents |
| GET | `/agents/summary/status` | Agent status summary |
| GET | `/manager/status` | Running processes and their status |
| GET | `/manager/info` | Version, type, max agents |
| PUT | `/manager/restart` | Restart the manager |
| GET | `/rules?limit=10` | List detection rules |
| GET | `/decoders?limit=10` | List log decoders |
| GET | `/alerts` | Query alerts (may fallback to indexer) |
| GET | `/security/users` | List API users |
| POST | `/security/users` | Create API user |
| PUT | `/security/users/{id}/password` | Change user password |

---

## Python Client (wazuh_client.py)

Located at `/home/cereal/SOC_TESTING/wazuh_deploy/wazuh_client.py`.

### WazuhClient Class

```python
from wazuh_client import WazuhClient

wc = WazuhClient()  # Defaults to 192.168.50.222:26500

# Manager queries
wc.manager_status()    # Running processes
wc.manager_info()      # Version, type
wc.restart_manager()   # Restart

# Agent queries
wc.list_agents()              # All agents
wc.list_agents(limit=5)       # Limited
wc.agent_status_summary()     # Active/pending/disconnected counts

# Rules and decoders
wc.list_rules(limit=20)
wc.list_rules(limit=10, search='ssh')
wc.list_decoders(limit=10)

# Alerts
wc.get_alerts(limit=20)
wc.get_alerts(limit=10, search='test-client')

# Indexer
wc.indexer_health()
wc.indexer_cluster_health()
wc.indexer_indices()  # Returns text of all indices
```

### WazuhLogSender Class

```python
from wazuh_client import WazuhLogSender

sender = WazuhLogSender()

# Send test logs via TCP (port 26151)
sender.send_tcp("Test alert: suspicious activity detected")
sender.send_tcp("High severity event", priority=1)  # priority 1 = emerg

# Send test logs via UDP (port 26514)
sender.send_udp("UDP test log message")
```

---

## Indexer (OpenSearch) Direct Access

**URL:** `https://192.168.50.222:26920` | **Auth:** Credentials stored in server-manager vault

```bash
# Cluster health
python "C:/Users/cereal/.agents/skills/server-manager/ssh_client.py" --server ai --execute 'curl -k -u admin:"$WAZUH_INDEXER_PASSWORD" https://127.0.0.1:26920/_cluster/health'

# List indices
python "C:/Users/cereal/.agents/skills/server-manager/ssh_client.py" --server ai --execute 'curl -k -u admin:"$WAZUH_INDEXER_PASSWORD" https://127.0.0.1:26920/_cat/indices?v'

# Search alerts
python "C:/Users/cereal/.agents/skills/server-manager/ssh_client.py" --server ai --execute 'curl -k -u admin:"$WAZUH_INDEXER_PASSWORD" -H "Content-Type: application/json" -d "{\"query\":{\"match_all:{}}, \"size\":10}" https://127.0.0.1:26920/wazuh-alerts-4.x-*/_search'
```

---

## Pointing External Logs to Wazuh

### Syslog Forwarding (rsyslog)

On a remote host, add to `/etc/rsyslog.conf`:
```
*.* @@192.168.50.222:26151
```
Then restart rsyslog: `systemctl restart rsyslog`

### Custom Application Logging

Use the WazuhLogSender class or send syslog-formatted TCP/UDP messages to port 26151 (TCP) or 26514 (UDP).

---

## Certificate Regeneration

If certs are lost or corrupted:
```bash
cd /home/cereal/SOC_TESTING/wazuh_deploy
docker compose down
docker compose -f generate-indexer-certs.yml run --rm generator
docker compose up -d
```

---

## Troubleshooting

| Issue | Diagnosis | Fix |
|-------|-----------|-----|
| Indexer wont start | `docker compose logs wazuh.indexer` | `sysctl -w vm.max_map_count=262144` on host |
| Dashboard connection refused | Indexer still starting | Wait 1-2 minutes |
| API 401 Unauthorized | JWT expired | Re-authenticate via `/security/user/authenticate` |
| Container loop-restarting | Config or cert error | Check `docker compose logs` |
| Logs not appearing | Verify connectivity | `nc -zv 192.168.50.222 26151` from sender host |
| Disk space issues | `docker system df` | `docker volume prune` or clean indexer data |

---

## Zeek + Suricata Integration

Wazuh receives and analyzes JSON logs from Zeek (network analysis) and Suricata (IDS/IPS). Each component is fully modular — Zeek and Suricata work standalone regardless of Wazuh status.

### Architecture

```
Zeek (zeek-soc) ──┐
                  ├─── JSON logs ──┐
Suricata (suricata-soc) ──┘        │
                                   │
                          Two paths to Wazuh:
                          1. <localfile> config (Wazuh reads logs directly)
                          2. log_forwarder.py (TCP forward to port 26151)
                                   │
                          Wazuh Manager (26151 TCP)
                          - Built-in JSON decoder parses both
                          - Custom Zeek rules (100900-100999)
                          - Enhanced Suricata rules (86700+)
                          - Generates alerts → Indexer → Dashboard
```

### What is Monitored

**Zeek rules (100900-100999):**
- `100900` (level 0) — Base Zeek rule, matches `"ts":` in raw log text
- `100903` (level 7) — Rejected connections (conn_state: REJ)
- `100904` (level 10) — Port scan detection (5+ rejected in 20s)
- `100906` (level 8) — Self-signed certificates
- `100907` (level 12) — Expired certificates
- `100909` (level 9) — DNS NXDOMAIN responses
- `100910` (level 10) — Revoked certificates

**Suricata rules (86700+):**
- `86710` (level 7) — HIGH severity alerts
- `86711` (level 12) — CRITICAL severity alerts
- `86712` (level 15) — EMERGENCY severity alerts
- `86720-86721` — Dropped/rejected packets
- `86730` — HTTP errors (4xx/5xx)
- `86740` — DNS NXDOMAIN
- `86750-86751` — Deprecated TLS / self-signed certs

### Log Sources

Wazuh manager config monitors these paths directly:
- `/home/cereal/SOC_TESTING/logs/zeek/*.log` (JSON format)
- `/home/cereal/SOC_TESTING/logs/suricata/eve.json` (JSON format)

### Log Forwarder

A standalone Python process at `/home/cereal/SOC_TESTING/log_forwarder/` tails Zeek and Suricata logs, forwarding via TCP to Wazuh port 26151. Fully optional — Wazuh reads logs directly via `<localfile>` config.

```bash
# Start forwarder
cd /home/cereal/SOC_TESTING/log_forwarder && bash start-forwarder.sh

# Stop forwarder
bash stop-forwarder.sh

# Check status
bash status-forwarder.sh
```

### Modularity Guarantees

1. **Zeek works standalone** — Forwarder is a separate process. Zeek container is untouched.
2. **Suricata works standalone** — Same. Suricata container is untouched.
3. **Wazuh works standalone** — The added configs just add new log sources.
4. **Forwarder is optional** — Wazuh reads logs directly via `<localfile>` config.
5. **No docker compose changes** — Zeek and Suricata compose files are NOT modified.

### Testing

```bash
# Run full integration test suite (18 tests)
cd /home/cereal/SOC_TESTING/log_forwarder && python3 test_integration.py

# Test a Zeek log against Wazuh rules
docker exec wazuh_deploy-wazuh.manager-1 bash -c 'echo "{\"ts\":1714156800,\"uid\":\"CzAbCdEf\",\"id.orig_h\":\"10.0.0.5\",\"id.orig_p\":12345,\"id.resp_h\":\"10.0.0.6\",\"id.resp_p\":80,\"proto\":\"tcp\",\"conn_state\":\"REJ\",\"duration\":0.5,\"orig_bytes\":100,\"resp_bytes\":0}" | /var/ossec/bin/wazuh-logtest'

# Test a Suricata log against Wazuh rules
docker exec wazuh_deploy-wazuh.manager-1 bash -c 'echo "{\"timestamp\":\"2026-04-27T01:00:00.000000+0000\",\"event_type\":\"alert\",\"src_ip\":\"10.0.0.5\",\"dest_ip\":\"10.0.0.6\",\"alert\":{\"signature\":\"ET TEST Alert\",\"severity\":4}}" | /var/ossec/bin/wazuh-logtest'
```

### Key Files

| File | Purpose |
|------|---------|
| `log_forwarder/log_forwarder.py` | Standalone log forwarder |
| `log_forwarder/start-forwarder.sh` | Launch script |
| `log_forwarder/stop-forwarder.sh` | Stop script |
| `log_forwarder/status-forwarder.sh` | Status check |
| `log_forwarder/test_integration.py` | End-to-end tests (18 tests) |
| `wazuh_deploy/config/wazuh_cluster/wazuh_manager.conf` | Manager config with log sources |
| `wazuh_deploy/config/wazuh_custom/rules/zeek_rules.xml` | Zeek alert rules |
| `wazuh_deploy/config/wazuh_custom/rules/enhanced_suricata_rules.xml` | Enhanced Suricata rules |

### Troubleshooting Integration

| Issue | Diagnosis | Fix |
|-------|-----------|-----|
| Rules not loading | `grep "CRITICAL.*zeek_rules" /var/ossec/logs/ossec.log` inside container | Check XML syntax, restart manager |
| Rules not matching | `wazuh-logtest` with sample log | Use `<match>` for raw text, `<field>` requires decoder |
| Logs not reaching Wazuh | Check `<localfile>` entries in manager config | Verify log paths exist, restart manager |
| Forwarder can't connect | `nc -zv 127.0.0.1 26151` | Ensure Wazuh manager is running |
| Wrong field names | Check Phase 2 output of `wazuh-logtest` | Built-in JSON decoder extracts all JSON keys |

---

## File Structure on AI Server

```
/home/cereal/SOC_TESTING/wazuh_deploy/
├── docker-compose.yml            # Compose file (custom ports)
├── generate-indexer-certs.yml    # Cert generator
├── config/                       # Wazuh configuration + SSL certs
│   ├── certs.yml
│   ├── wazuh_cluster/
│   ├── wazuh_dashboard/
│   ├── wazuh_indexer/
│   ├── wazuh_indexer_ssl_certs/
│   └── wazuh_custom/
│       ├── rules/
│       │   ├── zeek_rules.xml
│       │   └── enhanced_suricata_rules.xml
│       └── decoders/
├── .venv/                        # Python virtual environment
├── wazuh_client.py               # API wrapper + log sender
├── test_wazuh.py                 # Pytest suite (9 tests)
└── README.md                     # Quick reference

/home/cereal/SOC_TESTING/log_forwarder/
├── log_forwarder.py              # Standalone log forwarder
├── forwarder_config.env          # Environment config
├── start-forwarder.sh            # Launch script
├── stop-forwarder.sh             # Stop script
├── status-forwarder.sh           # Status check
└── test_integration.py           # End-to-end tests
```
