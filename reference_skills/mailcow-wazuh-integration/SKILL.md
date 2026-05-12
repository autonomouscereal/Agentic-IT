---
name: mailcow-wazuh-integration
description: >
  Mailcow-Wazuh SIEM integration for real-time alerting and phishing detection on 127.0.0.1.
  Covers Wazuh syslog configuration, custom detection rules (IDs 100100-100108),
  modular SIEM connector architecture (abstract base + Wazuh impl + NullConnector),
  standalone log forwarder with CEF formatting, dual-path forwarding (API + UDP syslog),
  and complete fault tolerance. Use when configuring Wazuh rules, deploying the log forwarder,
  integrating SIEM with Mailcow, or troubleshooting syslog/alert issues.
when_to_use: >
  Wazuh configuration, syslog setup, CEF formatting, SIEM connector,
  Mailcow alerting, phishing detection rules, log forwarder deployment,
  Wazuh rules not loading, syslog messages rejected, fault tolerance.
disable-model-invocation: false
user-invocable: true
---

# Mailcow-Wazuh SIEM Integration - Complete Blueprint

**Version:** 2.0 | **Date:** 2026-04-29
**Server:** 127.0.0.1 (AI Server) | **Wazuh:** v4.14.4 | **Mailcow:** Docker

---

## Overview

This integration connects Mailcow email server events to Wazuh SIEM for real-time alerting, logging, and phishing detection. The architecture is **completely fault-tolerant** - if Wazuh is down, Mailcow keeps running, emails deliver, and no services crash.

### Design Principles
- **Modular SIEM connector** - swap Wazuh for Splunk/ELK by changing one config line
- **Dual-path forwarding** - API + Syslog UDP; if one fails, the other works
- **Standalone forwarder** - no external dependencies, stdlib Python only
- **Zero blast radius** - SIEM failures silently ignored, never propagate upstream

---

## Architecture Diagram

```
+-----------------------------------------------------------------+
|                        Mailcow Server                           |
|                                                                 |
|  +----------+    +------------------+    +------------------+  |
|  | Dovecot  |--->|  Log Forwarder   |--->|  Wazuh Manager   |  |
|  |  Logs    |    |  (standalone)     |    |  (syslog UDP)    |  |
|  `----------'    `------------------'    `------------------'  |
|                            |                       |            |
|  +----------------------+  |    +----------------+ v            |
|  |   Report-Phish       |  |    |  Wazuh API     | Alerts       |
|  |   Backend            |  |    |  (port 26500)  | stored in    |
|  |   (internal_email)   |  |    `----------------' Indexer      |
|  `----------------------'  |              |                     |
|           |                |    +--------- v +                  |
|           v                |    | Wazuh      |                  |
|    Internal SMTP           |    | Dashboard  |                  |
|    (port 25)               |    | (port 26443)|                  |
`-----------------------------------------------------------------'
```

---

## Port Mapping Reference

| Service | Container Port | Host Port | Protocol |
|---------|---------------|-----------|----------|
| Wazuh API | 55000 | **26500** | TCP |
| Wazuh Syslog | 514 | **26514** | UDP |
| Wazuh Agent (secure) | 1514 | **26151** | TCP |
| Wazuh Dashboard | 5601 | **26443** | TCP |
| Wazuh Indexer | 9200 | **26920** | TCP |
| Mailcow SMTP | 25 | **25** | TCP |

---

## Part 1: Wazuh Manager Configuration

### 1A. Syslog Listener Setup

Wazuh must accept syslog UDP messages. Edit `/var/ossec/etc/ossec.conf` inside the container:

```xml
<!-- Syslog listener (REQUIRED for Mailcow integration) -->
<remote>
  <connection>syslog</connection>
  <port>514</port>
  <protocol>udp</protocol>
  <allowed-ips>127.0.0.1</allowed-ips>
  <allowed-ips><trusted-subnet-cidr></allowed-ips>
  <allowed-ips>172.26.0.0/16</allowed-ips>
  <allowed-ips>172.17.0.0/16</allowed-ips>
</remote>

<!-- Secure agent connection (existing, do not remove) -->
<remote>
  <connection>secure</connection>
  <port>1514</port>
  <protocol>tcp</protocol>
  <queue_size>131072</queue_size>
</remote>
```

**CRITICAL NOTES:**
- Each `<allowed-ips>` entry must contain a SINGLE IP or CIDR - no comma-separated lists
- Docker network subnets (`172.26.0.0/16`, `172.17.0.0/16`) must be included because host-to-container traffic comes from the Docker bridge IP, not 127.0.0.1
- `queue_size` is only valid for `secure` connections - do NOT include in syslog block
- Restart `wazuh-remoted` after changes:
  ```bash
  docker exec wazuh_deploy-wazuh.manager-1 /var/ossec/bin/wazuh-control restart wazuh-remoted
  ```

### 1B. Verification

After restart, verify syslog is listening:
```bash
docker logs wazuh_deploy-wazuh.manager-1 2>&1 | grep -i 'syslog\|514'
# Expected output:
# Started (pid: XXXX). Listening on port 514/UDP (syslog).
# Remote syslog allowed from: '127.0.0.1'
# Remote syslog allowed from: '<trusted-subnet-cidr>'
```

---

## Part 2: Wazuh Custom Rules

### 2A. Rules File Location

Rules are deployed directly into the container at:
```
/var/ossec/etc/rules/local_rules.xml
```

**DO NOT** use `<pcre>` or `<pcre2>` elements - they are NOT supported as standalone rule elements in Wazuh 4.14.4. Use `<match>` for string matching instead.

### 2B. Mailcow Rules (IDs 100100-100108)

```xml
<!-- Mailcow SIEM Integration Rules -->
<!-- Rule IDs: 100100-100108 -->

<group name="mailcow,siem,">

  <!-- Base rule for all Mailcow CEF syslog events -->
  <rule id="100100" level="0">
    <match>CEF:0|Mailcow|</match>
    <description>Mailcow: event received</description>
    <group>mailcow,</group>
  </rule>

  <!-- Phishing report alert (HIGH severity) -->
  <rule id="100101" level="12">
    <if_sid>100100</if_sid>
    <match>phishing_report</match>
    <description>Mailcow: Phishing email report submitted</description>
    <group>mailcow,phishing,</group>
  </rule>

  <!-- LMTP delivery success (LOW severity) -->
  <rule id="100102" level="3">
    <if_sid>100100</if_sid>
    <match>delivery_success</match>
    <description>Mailcow: Email delivered to mailbox via LMTP</description>
    <group>mailcow,delivery,</group>
  </rule>

  <!-- LMTP delivery failure (MEDIUM severity) -->
  <rule id="100103" level="8">
    <if_sid>100100</if_sid>
    <match>delivery_failure</match>
    <description>Mailcow: Email delivery failed via LMTP</description>
    <group>mailcow,delivery,failure,</group>
  </rule>

  <!-- Authentication success (LOW severity) -->
  <rule id="100104" level="2">
    <if_sid>100100</if_sid>
    <match>auth_success</match>
    <description>Mailcow: User authentication successful</description>
    <group>mailcow,auth,</group>
  </rule>

  <!-- Authentication failure (HIGH severity) -->
  <rule id="100105" level="10">
    <if_sid>100100</if_sid>
    <match>auth_failure</match>
    <description>Mailcow: User authentication failed</description>
    <group>mailcow,auth,failure,</group>
  </rule>

  <!-- SMTP connection (LOW severity) -->
  <rule id="100106" level="3">
    <if_sid>100100</if_sid>
    <match>smtp_connection</match>
    <description>Mailcow: SMTP connection received</description>
    <group>mailcow,smtp,</group>
  </rule>

  <!-- Generic Mailcow log events (non-CEF format) -->
  <rule id="100107" level="5">
    <match>mailcow-fwd</match>
    <description>Mailcow: log event via forwarder</description>
    <group>mailcow,</group>
  </rule>

  <!-- report-phish logger events -->
  <rule id="100108" level="7">
    <match>report-phish</match>
    <description>Mailcow: Report-Phish alert event</description>
    <group>mailcow,phishing,</group>
  </rule>

</group>
```

### 2C. Deploying Rules to Container

```bash
# Method 1: Copy file into running container
docker cp mailcow_wazuh_rules.xml wazuh_deploy-wazuh.manager-1:/var/ossec/etc/rules/local_rules.xml

# Method 2: Write directly via docker exec
docker exec wazuh_deploy-wazuh.manager-1 bash -c 'cat > /var/ossec/etc/rules/local_rules.xml << EOF
<paste rules here>
EOF'

# Restart Wazuh to load new rules
docker exec wazuh_deploy-wazuh.manager-1 /var/ossec/bin/wazuh-control start
```

### 2D. Rule Severity Levels

| Level | Meaning | Mailcow Events |
|-------|---------|----------------|
| 0 | Base/parent rule | All CEF Mailcow events |
| 2 | Info (normal) | Auth success |
| 3 | Low (routine) | Delivery success, SMTP connection |
| 5 | Medium (notable) | Generic forwarder events |
| 7 | Elevated | Report-phish alerts |
| 8 | High (concerning) | Delivery failures |
| 10 | Critical | Auth failures |
| 12 | Severe | Phishing reports |

---

## Part 3: SIEM Connector Architecture

### 3A. Module Structure

```
report_phish/
|-- __init__.py              # Exports: create_connector, SIEMConnector, WazuhConnector
|-- backends/
|   `-- internal_email.py    # Report-phish backend with SIEM integration
`-- siem/
    |-- __init__.py          # Factory: create_connector(siem_type, config)
    |-- connector.py         # Abstract SIEMConnector base + NullConnector
    `-- wazuh_connector.py   # Wazuh implementation
```

### 3B. Abstract Connector (connector.py)

The `SIEMConnector` base class defines the interface all SIEM backends must implement:

```python
class SIEMConnector(abc.ABC):
    def __init__(self, config: dict):
        self.enabled = config.get("enabled", True)
        self.timeout = config.get("timeout", 5)

    def is_connected(self) -> bool:
        """Check SIEM connectivity."""
        return self._check_connectivity()

    @abc.abstractmethod
    def _check_connectivity(self) -> bool:
        """Override in subclass."""

    @abc.abstractmethod
    def send_alert(self, alert: dict) -> bool:
        """Send a security alert to SIEM."""

    @abc.abstractmethod
    def send_log(self, log_entry: dict) -> bool:
        """Send a log entry to SIEM."""

    # SAFE wrappers - never raise, always return status dict
    def safe_send_alert(self, alert: dict) -> dict:
        try:
            ok = self.send_alert(alert)
            return {"sent": ok, "note": "delivered" if ok else "failed silently"}
        except Exception:
            return {"sent": False, "note": "silently failed"}

    def safe_send_log(self, log_entry: dict) -> dict:
        try:
            ok = self.send_log(log_entry)
            return {"sent": ok, "note": "delivered" if ok else "failed silently"}
        except Exception:
            return {"sent": False, "note": "silently failed"}
```

### 3C. Wazuh Connector (wazuh_connector.py)

```python
DEFAULT_WAZUH_CONFIG = {
    "enabled": True,
    "host": "127.0.0.1",
    "api_port": 26500,
    "api_user": "wazuh-wui",
    "api_password": os.environ.get("WAZUH_API_PASSWORD", ""),
    "syslog_enabled": True,
    "syslog_port": 26514,
    "syslog_format": "cef",
    "timeout": 5,
    "alert_severity": "high",
}
```

**Dual-path forwarding:**
1. **API path** - sends via `POST /security/user/authenticate` for token, then forwards alert
2. **Syslog path** - sends CEF-formatted UDP packets with PRI headers

```python
def send_alert(self, alert: dict) -> bool:
    api_ok = self._send_api_alert(alert)
    syslog_ok = False
    if self.syslog_enabled:
        syslog_ok = self._send_syslog_alert(alert)
    return api_ok or syslog_ok  # Succeeds if EITHER path works
```

**CEF message format with syslog PRI header:**
```
<44>CEF:0|Mailcow|Report-Phish|1.0|phishing_report|Subject Here|8|src=sender@evil.com|dst=recipient@mail.com|reportId=abc-123
```

### 3D. Null Connector

No-op implementation for environments without SIEM:
```python
class NullConnector(SIEMConnector):
    def _check_connectivity(self) -> bool: return False
    def send_alert(self, alert: dict) -> bool: return False
    def send_log(self, log_entry: dict) -> bool: return False
```

### 3E. Factory Pattern

```python
from report_phish import create_connector

# Wazuh mode
conn = create_connector("wazuh")

# No SIEM
conn = create_connector("null")

# Unknown type -> defaults to NullConnector (safe fallback)
conn = create_connector("splunk")  # returns NullConnector
```

---

## Part 4: Standalone Log Forwarder

### 4A. Location and Execution

**Server path:** `/opt/agentic-it/Mailcow/siem_log_forwarder.py`
**Log file:** `/opt/agentic-it/Mailcow/siem_forwarder.log`

```bash
# Wazuh mode (default)
python3 /opt/agentic-it/Mailcow/siem_log_forwarder.py

# Null mode (dry run, no SIEM)
python3 /opt/agentic-it/Mailcow/siem_log_forwarder.py null

# Production (background)
nohup python3 /opt/agentic-it/Mailcow/siem_log_forwarder.py > /opt/agentic-it/Mailcow/siem_forwarder.log 2>&1 &
```

### 4B. What It Monitors

The forwarder tails the Dovecot log file and parses these event types via regex:

| Pattern | Regex | Action Field |
|---------|-------|-------------|
| LMTP delivery | `lmtp\([^)]+\)<[^>]*><[^>]*>: Info: msgid=<[^>]*>: saved mail to (\w+)` | `delivery_success` |
| LMTP error | `lmtp\([^)]+\): (?:Error|Fatal):.*?(Failed|Fatal|Error)` | `delivery_failure` |
| Auth success | `auth.*?OK.*?user=<([^>]+)>` | `auth_success` |
| Auth failure | `auth.*?password failed` | `auth_failure` |
| Master start | `master: Info: Dovecot.*?starting up` | `master_start` |
| Master stop | `master: Warning: Killed with signal` | `master_stop` |

### 4C. CEF Formatting

Each parsed event is formatted as a CEF message with syslog PRI header:

```python
def _format_cef(self, entry):
    action = entry.get("action", "info")
    severity = 12 if "phish" in action else (
        10 if "failure" in action else (
            5 if "error" in action else 3))
    pri = (severity // 2) * 8 + 16  # facility 16 = local0
    return (
        f"<{pri}>CEF:0|Mailcow|Log-Forwarder|1.0|{action}|"
        f"Mailcow {action}|{severity}|"
        f"source=mailcow|eventType={action}"
    )
```

**Example output:**
```
<30>CEF:0|Mailcow|Log-Forwarder|1.0|auth_failure|Mailcow auth_failure|10|source=mailcow|eventType=auth_failure
```

### 4D. Dependencies

**Zero external dependencies.** The forwarder uses only Python stdlib:
- `sys`, `json`, `time`, `signal`, `socket`, `logging`, `re`, `ssl`, `urllib.request`, `urllib.error`, `base64`, `datetime`

---

## Part 5: Report-Phish Backend Integration

### 5A. Configuration

```python
from report_phish import InternalEmailBackend

# Default - Wazuh SIEM enabled
backend = InternalEmailBackend()

# SIEM disabled
backend = InternalEmailBackend({"siem_config": {"enabled": False}})
```

### 5B. Report Flow

```
1. User clicks "Report Phish" button
2. Backend receives email metadata (subject, headers, body)
3. Email is sent via internal SMTP to security-team@mailcow.local
4. SIEM alert is forwarded (independent of email delivery)
5. Result dict returned with status of both paths
```

### 5C. Result Structure

```json
{
  "success": true,
  "message": "Report sent via Mailcow to security-team@mailcow.local",
  "backend": "internal_email",
  "report_id": "siem-test-001",
  "timestamp": 1777452507.3549285,
  "smtp": {
    "host": "127.0.0.1",
    "port": 25,
    "dist_group": "security-team@mailcow.local"
  },
  "siem_alert": {
    "sent": true
  }
}
```

---

## Part 6: Testing and Verification

### 6A. Test Suite

**Location:** `C:\Users\me\report_phish\test_siem.py`

Run with: `python test_siem.py`

| Test | Description |
|------|-------------|
| Connector Factory | Verifies all connector types load correctly |
| Null Connector Safety | No-op connector never raises |
| Wazuh Connectivity | API authentication and agent listing |
| Syslog UDP Path | UDP packet delivery to port 26514 |
| Full Report + SIEM | End-to-end phishing report with SIEM alert |
| Report Without SIEM | Email delivers when SIEM disabled |
| Backend Status | Status endpoint includes SMTP + SIEM fields |

### 6B. Manual Verification

```bash
# Check Wazuh alerts for Mailcow events
docker exec wazuh_deploy-wazuh.manager-1 grep -c 'Mailcow' /var/ossec/logs/alerts/alerts.json

# View alert details
docker exec wazuh_deploy-wazuh.manager-1 grep 'Mailcow' /var/ossec/logs/alerts/alerts.json | \
  python3 -c "import sys,json; [print(json.loads(l).get('rule',{}).get('description','?')) for l in sys.stdin if 'Mailcow' in l]"

# Send test CEF message
python3 -c "
import socket
sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.sendto(b'<14>CEF:0|Mailcow|Log-Forwarder|1.0|phishing_report|Test|12|source=mailcow', ('127.0.0.1', 26514))
sock.close()
print('Sent')
"
```

---

## Part 7: Troubleshooting

### 7A. Wazuh Rules Not Loading

**Error:** `Error reading XML file 'etc/rules/local_rules.xml': XMLERR`

| Cause | Fix |
|-------|-----|
| Unclosed `<` in regex patterns | Use `<match>` instead of `<pcre>` or `<pcre2>` |
| XML special characters in patterns | Escape `<` as `&lt;` or avoid in pattern |
| File not visible in container | Copy directly: `docker cp file.xml container:/path/` |

### 7B. Syslog Messages Rejected

**Error:** `Message from '172.26.0.1' not allowed. Cannot find the ID of the agent.`

| Cause | Fix |
|-------|-----|
| Missing `allowed-ips` for docker subnet | Add `<allowed-ips>172.26.0.0/16</allowed-ips>` |
| Missing `allowed-ips` for host network | Add `<allowed-ips><trusted-subnet-cidr></allowed-ips>` |
| Comma-separated IPs in one tag | Split into separate `<allowed-ips>` elements |

### 7C. Syslog Not Listening

**Error:** `Syslog server disabled` or port 514 not listening

| Cause | Fix |
|-------|-----|
| No `allowed-ips` configured | Wazuh requires at least one allowed IP |
| `queue_size` in syslog block | Only valid for `secure` connections |
| Wrong connection type | Must be `<connection>syslog</connection>` |

### 7D. CEF Messages Not Generating Alerts

| Cause | Fix |
|-------|-----|
| Missing syslog PRI header | Prefix messages with `<PRI>` (e.g., `<14>CEF:0|...`) |
| Event type in wrong CEF field | The 5th CEF field (after version\|product\|version\|signatureID) must match rule patterns |
| Rules use `<pcre2>` instead of `<match>` | Replace with `<match>` for string matching |

### 7E. Common Commands

```bash
# Full Wazuh restart (loads new rules)
docker exec wazuh_deploy-wazuh.manager-1 /var/ossec/bin/wazuh-control start

# Restart remoted only (faster, for network config changes)
docker exec wazuh_deploy-wazuh.manager-1 /var/ossec/bin/wazuh-control restart wazuh-remoted

# Check all process status
docker exec wazuh_deploy-wazuh.manager-1 /var/ossec/bin/wazuh-control status

# View recent logs
docker logs wazuh_deploy-wazuh.manager-1 2>&1 | tail -30

# Verify syslog listener
docker logs wazuh_deploy-wazuh.manager-1 2>&1 | grep '514/UDP'
```

---

## Part 8: File Locations Summary

### Local Development (Windows)
| Path | Purpose |
|------|---------|
| `C:\Users\me\report_phish\siem\connector.py` | Abstract SIEM connector |
| `C:\Users\me\report_phish\siem\wazuh_connector.py` | Wazuh implementation |
| `C:\Users\me\report_phish\siem\__init__.py` | Factory function |
| `C:\Users\me\report_phish\backends\internal_email.py` | Report-phish backend |
| `C:\Users\me\report_phish\test_siem.py` | Test suite |

### Server (127.0.0.1)
| Path | Purpose |
|------|---------|
| `/opt/agentic-it/Mailcow/siem_log_forwarder.py` | Standalone log forwarder |
| `/opt/agentic-it/Mailcow/siem_forwarder.log` | Forwarder log output |
| `/opt/agentic-it/Mailcow/mailcow_wazuh_rules.xml` | Wazuh rules (host copy) |
| `/opt/agentic-it/Mailcow/deploy/logs/dovecot/dovecot.log` | Dovecot log source |

### Inside Wazuh Container
| Path | Purpose |
|------|---------|
| `/var/ossec/etc/ossec.conf` | Wazuh configuration |
| `/var/ossec/etc/rules/local_rules.xml` | Custom rules (loaded at startup) |
| `/var/ossec/logs/alerts/alerts.json` | Generated alerts |

---

## Part 9: Deployment Checklist

- [ ] Wazuh manager running with all core processes
- [ ] Syslog UDP listener active on port 514 (host: 26514)
- [ ] `allowed-ips` configured for 127.0.0.1, <trusted-subnet-cidr>, 172.26.0.0/16, 172.17.0.0/16
- [ ] Mailcow rules deployed to `/var/ossec/etc/rules/local_rules.xml`
- [ ] Rules validated (no XML errors, no pcre/pcre2 elements)
- [ ] Log forwarder running and tailing Dovecot logs
- [ ] Report-phish backend configured with Wazuh connector
- [ ] Test suite passes (7/7 tests)
- [ ] Mailcow alerts visible in `alerts.json`
- [ ] Fault tolerance verified (SIEM disabled -> email still delivers)

---

## Part 10: Wazuh API Authentication

### Credentials
- **Username:** `wazuh-wui` (NOT `wazuh`)
- **Password:** Stored in credential-vault (never hardcoded)
- **Auth endpoint:** `POST /security/user/authenticate` (singular "user")

### Response Format
```json
{
  "error": 0,           // 0 = success in Wazuh 4.x
  "data": {
    "token": "eyJhbG..."
  },
  "data_name": "wazuh-wui"
}
```

### Known API Limitations
- `/agent/decode` endpoint does NOT exist in Wazuh 4.14.4 (returns 404)
- `/alerts` endpoint does NOT exist in Wazuh 4.14.4 (alerts stored in Indexer only)
- Syslog UDP is the PRIMARY working path for event injection
- Token-based auth required for all API calls after initial authentication

---

*This integration was built and tested on 2026-04-29. All components verified end-to-end.*
