---
name: soc-bridge
description: Manage the SOC Bridge integration between iTop ITSM and Mailcow email on AI Server (192.168.50.222). Deploy, configure, run the polling daemon, test phishing workflow, and manage ticket notifications. All operations via Server Manager v2 SSH client.
when_to_use: SOC Bridge deployment, iTop-Mailcow integration, ticket notification setup, phishing workflow testing, daemon management, security team setup, ticket state tracking, email notification configuration.
allowed-tools: Bash("python" "ssh_client.py" "*"), Read, Edit, Write, Glob, Grep
---

# SOC Bridge Manager

Modular integration bridge between iTop ITSM and Mailcow email. Deployed at `/home/cereal/SOC_TESTING/soc_bridge/` on AI Server.

Full deployment blueprint in [DEPLOYMENT.md](../../soc_bridge/DEPLOYMENT.md).

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
| Deploy + smoke test | `...ssh_client.py" --server ai --execute "cd /home/cereal/SOC_TESTING/soc_bridge && python3 deploy/deploy.py"` |
| Setup security team | `...ssh_client.py" --server ai --execute "cd /home/cereal/SOC_TESTING/soc_bridge && python3 deploy/setup_security_team.py"` |
| Run all tests | `...ssh_client.py" --server ai --execute "cd /home/cereal/SOC_TESTING/soc_bridge && python3 tests/test_end_to_end.py && python3 tests/test_itop_connector.py && python3 tests/test_mailcow_connector.py"` |
| Start daemon | `...ssh_client.py" --server ai --execute "cd /home/cereal/SOC_TESTING/soc_bridge && python3 daemon.py --config production_config.json"` |
| Single poll | `...ssh_client.py" --server ai --execute "cd /home/cereal/SOC_TESTING/soc_bridge && python3 daemon.py --config production_config.json --poll-once"` |
| Health check | `...ssh_client.py" --server ai --execute "cd /home/cereal/SOC_TESTING/soc_bridge && python3 daemon.py --config production_config.json --check"` |
| Check config | `...ssh_client.py" --server ai --execute "cat /home/cereal/SOC_TESTING/soc_bridge/production_config.json"` |

## Architecture

- **iTop Connector** — REST API v1.4 (`/webservices/rest.php`). Dual auth (Basic Auth header + JSON payload). Requires `version`, `json_output`, `json_data` as separate URL-encoded form fields.
- **Mailcow Connector** — SMTP on port 25. Structured HTML notifications with color-coded badges per event type.
- **Ticket Notification Engine** — Polls iTop for state changes, sends emails. JSON-based state persistence.
- **Phishing Workflow** — Report -> iTop incident (auto-assigned to security team) -> email notification pipeline.
- **Daemon** — Long-running poller with configurable interval. Signal-handled graceful shutdown.

## Critical iTop API Rules

1. **`status` not `state`** — iTop returns `status` field (`new`, `assigned`, `resolved`, `closed`).
2. **Tickets must be assigned before resolving** — `ev_resolve` fails on `new` state. Connector auto-assigns.
3. **Resolution codes are predefined** — Do not pass arbitrary strings. Omit `resolution_code` to use default (`"assistance"`).
4. **Security team key is 65** — Not the default `1`. Must be set in config.
5. **`ev_assign` stimulus required** — Field updates alone don't transition state. Use `ev_assign` stimulus.

## Configuration

Edit `production_config.json` on the server. Key sections:
- `itop` — host, port, credentials, `security_team_id` (must be 65)
- `mailcow` — SMTP settings, notification recipients, per-event toggles
- `daemon` — poll interval, ticket classes, states to skip
- `phishing_workflow` — auto-create, auto-assign, auto-notify flags

## Test Suite

46 total tests across 3 suites:
- `test_itop_connector.py` — 22 tests (config, connector init, live CRUD, lifecycle)
- `test_mailcow_connector.py` — 13 tests (message building, SMTP delivery, all notification types)
- `test_end_to_end.py` — 11 tests (state tracker, phishing pipeline, full lifecycle, poll cycles)

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| "Missing parameter 'version'" | API format issue — verify `_make_request` sends URL-encoded fields |
| "Invalid object Team::1" | Wrong `security_team_id` — run `setup_security_team.py` |
| "No ticket key in API response" | Team ID invalid — verify config has `security_team_id: 65` |
| "Invalid stimulus: ev_resolve" | Ticket not assigned — connector auto-fixes, verify `assign_ticket` uses `ev_assign` |
| Permission denied `/var/lib/soc_bridge` | Old hardcoded path — all paths now use `${BASE_DIR}/data/` |
| Stale `.pyc` cache | Run `find /home/cereal/SOC_TESTING/soc_bridge -type d -name __pycache__ -exec rm -rf {} +` |
