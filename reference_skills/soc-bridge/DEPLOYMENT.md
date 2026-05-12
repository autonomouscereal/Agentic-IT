# SOC Bridge - Deployment Blueprint

Modular integration bridge between iTop ITSM and Mailcow email with automatic ticket notifications, phishing workflow, and polling daemon. Designed to be tool-agnostic: swap iTop for Jira/ServiceNow, Mailcow for any SMTP, or Wazuh for Splunk via configuration only.

## Architecture

```
+-------------+     REST API      +-------------+     SMTP       +-------------+
|    iTop     | <-------------+  |  SOC Bridge  | <----------+   |   Mailcow   |
|   ITSM      |  +----------+  |  (Python)     |  +--------+  |   |   Email    |
|  :25432     |  | Connector|  |               |  | Conn.  |  |   |  :25       |
+-------------+  +----------+  +---------------+  +--------+  +---+-------------+
                           |            |                  |
                     +----------+  +----------+           |
                     | Connector|  | Workflow |           |
                     |  SIEM   |  | Engine   |           |
                     | (null/  |  |          |           |
                     |  wazuh) |  +----------+           |
                     +----------+                        |
```

### Components

| Component | File | Purpose |
|-----------|------|---------|
| Config Loader | `config.py` | JSON config with `${ENV_VAR}` interpolation |
| iTop Connector | `connectors/itop_connector.py` | REST API v1.4 — CRUD, stimuli, polling |
| Mailcow Connector | `connectors/mailcow_connector.py` | SMTP email delivery with HTML notifications |
| Ticket Notifications | `workflows/ticket_notifications.py` | Polls iTop, detects state changes, sends emails |
| Phishing Workflow | `workflows/phishing_workflow.py` | Phishing report -> ticket -> email pipeline |
| Daemon | `daemon.py` | Long-running poller with graceful shutdown |
| CLI | `cli.py` | Status, ticket creation, phishing, email testing |

### Modularity

All connectors accept a config dict — no hardcoded credentials or endpoints. Swap any component by:
1. Implementing the same interface (config dict in, results out)
2. Updating `default_config.json` with the new connector's settings
3. No code changes required in workflows or daemon

## Prerequisites

- iTop ITSM v3.2.1+ running on target host (REST API at `/webservices/rest.php`)
- Mailcow running on target host (SMTP on port 25)
- Python 3.8+ (stdlib only — no pip dependencies required)
- Server Manager v2 for deployment (`ssh_client.py`)

## Configuration

See `default_config.json` for the full template. Key sections:

### iTop Section
```json
"itop": {
    "host": "127.0.0.1",
    "port": 25432,
    "username": "admin",
    "password": "${ITOP_PASSWORD}",  # vault key: itop_web
    "api_endpoint": "/webservices/rest.php",
    "api_version": "1.4",
    "security_team_id": 65,
    "default_org_id": 1,
    "default_caller_id": 1
}
```

**Critical**: `security_team_id` must match an actual Team key in iTop. Run `deploy/setup_security_team.py` to create one if needed.

### Mailcow Section
```json
"mailcow": {
    "smtp_host": "127.0.0.1",
    "smtp_port": 25,
    "use_tls": false,
    "from_email": "soc-bridge@mailcow.local",
    "notification_recipients": ["security-team@mailcow.local"],
    "notify_on_create": true,
    "notify_on_assign": true,
    "notify_on_escalate": true,
    "notify_on_resolve": true,
    "notify_on_close": true
}
```

### Daemon Section
```json
"daemon": {
    "poll_interval_seconds": 60,
    "max_tickets_per_poll": 50,
    "ticket_classes_to_watch": ["Incident", "UserRequest"],
    "states_to_skip": ["closed", "closed 2"]
}
```

## Deployment Steps

### 1. Deploy Package to Server

```bash
cd ~/.agents/skills/server-manager
# Upload entire package directory
python ssh_client.py --server ai --upload "C:/Users/cereal/soc_bridge/" "/home/cereal/SOC_TESTING/soc_bridge/"
```

### 2. Run Security Team Setup

```bash
python ssh_client.py --server ai --execute "cd /home/cereal/SOC_TESTING/soc_bridge && python3 deploy/setup_security_team.py"
```

This creates a "Security Team" in iTop if one doesn't exist, and updates `production_config.json` with the correct team key.

### 3. Run Deployment Script

```bash
python ssh_client.py --server ai --execute "cd /home/cereal/SOC_TESTING/soc_bridge && python3 deploy/deploy.py"
```

This performs:
1. Creates `data/`, `data/state/`, `data/logs/` directories
2. Writes `production_config.json`
3. Verifies all Python modules import
4. Tests iTop and Mailcow connectivity
5. Runs phishing workflow smoke test (creates ticket + sends email)

### 4. Verify Tests

```bash
# Run all test suites
cd /home/cereal/SOC_TESTING/soc_bridge
python3 tests/test_itop_connector.py     # 22 tests
python3 tests/test_mailcow_connector.py  # 13 tests
python3 tests/test_end_to_end.py         # 11 tests
```

## Running the Daemon

```bash
# Full daemon mode (polls every 60s by default)
cd /home/cereal/SOC_TESTING/soc_bridge
python3 daemon.py --config production_config.json

# Single poll cycle
python3 daemon.py --config production_config.json --poll-once

# Health check
python3 daemon.py --config production_config.json --check
```

## iTop API Details

### Critical API Format
iTop REST API requires `version`, `json_output`, and `json_data` as separate URL-encoded form fields:
```
POST /webservices/rest.php
Content-Type: application/x-www-form-urlencoded

version=1.4&json_output=1&json_data={"operation":"core/get","class":"Incident","key":1}
```

### Ticket Lifecycle States
iTop uses `status` field (not `state`):
- `new` -> `assigned` -> `resolved` -> `closed`

### Stimuli
- `ev_assign` — transitions `new` -> `assigned` (requires `team_id` field)
- `ev_resolve` — transitions `assigned` -> `resolved` (requires `solution` field)
- `ev_close` — transitions `resolved` -> `closed`

**Tickets must be assigned before they can be resolved.** The connector handles this automatically.

### Resolution Codes
iTop uses predefined resolution codes. The default is `"assistance"`. Do not pass arbitrary strings — omit `resolution_code` to use the default.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| "Missing parameter 'version'" | API format wrong | Ensure `version` is URL-encoded, not in JSON body |
| "Invalid object Team::1" | Wrong security_team_id | Run `setup_security_team.py` |
| "No ticket key in API response" | Team ID invalid | Verify `security_team_id` matches actual Team key |
| "Invalid stimulus: ev_resolve" | Ticket not assigned | Connector auto-assigns now; verify `assign_ticket` uses `ev_assign` |
| "Value not allowed [Resolved]" | Bad resolution_code | Omit resolution_code or use valid iTop enum value |
| Permission denied `/var/lib/soc_bridge` | Hardcoded system path | All paths now use `${BASE_DIR}/data/` |
| State always N/A | iTop returns `status` not `state` | Fixed in all code paths |

## File Structure

```
soc_bridge/
__init__.py                  # Package marker
config.py                    # Config loader with env var interpolation
default_config.json          # Configuration template
cli.py                       # CLI interface
daemon.py                    # Polling daemon
connectors/
    __init__.py
    itop_connector.py        # iTop REST API connector
    mailcow_connector.py     # Mailcow SMTP connector
workflows/
    __init__.py
    ticket_notifications.py  # Change detection + email engine
    phishing_workflow.py     # Phishing report pipeline
deploy/
    deploy.py                # Full deployment + smoke test
    deploy.sh                # Shell deployment wrapper
    setup_security_team.py   # Create security team in iTop
tests/
    __init__.py
    test_itop_connector.py   # 22 connector tests
    test_mailcow_connector.py # 13 connector tests
    test_end_to_end.py       # 11 integration tests
```
