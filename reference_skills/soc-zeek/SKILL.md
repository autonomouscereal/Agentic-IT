---
name: soc-zeek
description: Zeek network analysis framework management for SOC testing. Use when checking Zeek status, viewing network logs (conn.log, dns.log, http.log), or monitoring captured traffic.
allowed-tools: Read Bash
---

# Zeek Skill - Network Analysis Framework

## Quick Commands

### Check Status
```bash
docker exec zeek-soc pgrep -a zeek || docker ps | grep zeek
```

### View Logs
```bash
docker exec zeek-soc ls /var/log/zeek/
docker exec zeek-soc tail -50 /var/log/zeek/current/*.log 2>/dev/null
```

## Log Types Generated

| Log File | Content |
|----------|---------|
| conn.log | Connection events |
| dns.log | DNS queries/responses |
| http.log | HTTP traffic |
| ssl.log | SSL/TLS handshakes |
| files.log | File transfers |
| dhcp.log | DHCP events |

## API Endpoints (Port 26001)

- `/` - Root endpoint
- `/logs` - Log file access
- `/metrics` - Performance metrics

---

## Wazuh Integration

Zeek JSON logs are forwarded to Wazuh for centralized alerting. Zeek works completely standalone - if Wazuh goes down, Zeek keeps capturing.

### How it Works

1. Zeek produces JSON logs at `/opt/agentic-it/SOC_TESTING/logs/zeek/*.log`
2. Wazuh manager monitors these files via `<localfile>` config (JSON format)
3. Wazuh's built-in JSON decoder extracts all fields (`conn_state`, `id.orig_h`, etc.)
4. Custom rules (100900-100999) match on Zeek-specific fields to generate alerts

### Zeek Rules in Wazuh

| Rule ID | Level | Description |
|---------|-------|-------------|
| 100900 | 0 | Base Zeek rule (matches `"ts":` in raw text) |
| 100903 | 7 | Rejected connections (conn_state: REJ) |
| 100904 | 10 | Port scan detection (5+ rejected in 20s) |
| 100906 | 8 | Self-signed certificates |
| 100907 | 12 | Expired certificates |
| 100909 | 9 | DNS NXDOMAIN responses |
| 100910 | 10 | Revoked certificates |

### If Wazuh is Down

- Zeek continues capturing and writing logs normally
- The log forwarder (if running) buffers and retries with backoff
- No log loss - Wazuh reads from file positions on reconnect

### Testing Zeek -> Wazuh

```bash
# Test a Zeek log against Wazuh rules (run on AI Server)
docker exec wazuh_deploy-wazuh.manager-1 bash -c 'echo "{\"ts\":1714156800,\"uid\":\"CzAbCdEf\",\"id.orig_h\":\"10.0.0.5\",\"id.orig_p\":12345,\"id.resp_h\":\"10.0.0.6\",\"id.resp_p\":80,\"proto\":\"tcp\",\"conn_state\":\"REJ\",\"duration\":0.5,\"orig_bytes\":100,\"resp_bytes\":0}" | /var/ossec/bin/wazuh-logtest'

# Expected: Rule 100903 fires (level 7, "Rejected connection")

# Run full integration tests
cd /opt/agentic-it/SOC_TESTING/log_forwarder && python3 test_integration.py
```
