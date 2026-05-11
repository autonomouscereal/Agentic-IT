# IAM Bridge - Troubleshooting Guide

## Common Issues

### Keycloak Connection Failures

**Symptom:** `Connection failed: [Errno 111] Connection refused`

| Cause | Fix |
|-------|-----|
| Keycloak not running | `docker compose up -d` in keycloak-manager directory |
| Wrong port | Verify Keycloak on port 8080, management on 9000 |
| Firewall blocking | Check ports 8080 and 9000 are open |

**Diagnosis:**
```bash
curl http://localhost:9000/health
# Expected: {"status": "UP"}
```

### iTop Connection Failures

**Symptom:** `Connection failed` or timeout on iTop REST API calls

| Cause | Fix |
|-------|-----|
| iTop container not running | Check container status, restart if needed |
| Wrong port | Verify iTop on port 25432 |
| iTop still initializing | Wait for iTop to fully start (can take 30+ seconds) |

**Diagnosis:**
```bash
curl http://localhost:25432/index.php
# Expected: 200 OK with iTop login page
```

### Authentication Failures

**Symptom:** `[FAIL] iTop authentication failed` or `[AUTH FAILED]`

| Cause | Fix |
|-------|-----|
| Wrong password in .env | Update `.env` with correct credentials |
| .env file not found | Ensure `.env` exists in iam-bridge directory |
| .env file has wrong permissions | `chmod 600 .env` |

### OIDC Token Request Fails

**Symptom:** `test_oidc_token_request` fails in test suite

| Cause | Fix |
|-------|-----|
| `BRIDGE_CLIENT_SECRET` not set | Run `bridge_deploy.py --full` to generate it |
| Client not configured | Run `keycloak_setup.py` to create the OIDC client |
| Service accounts disabled | Ensure `serviceAccountsEnabled: true` on the client |

### iTop Extension Issues

**Symptom:** `combodo-hybridauth` or `combodo-saml` shown as NOT installed

These extensions **must be installed manually** via the iTop UI:
1. Log into iTop as admin
2. Navigate to Admin > Extensions > Install
3. Install from iTop Store or upload the `.itop-pack` file
4. After installation, add the OIDC config to `config-itop.php`

**OIDC Config for config-itop.php:**
The `itop_setup.py` script generates the config snippet and saves it to `.oidc_config.json`. Add this to your `$databases_params` in `config-itop.php`.

### Sync Bridge Issues

**Symptom:** Sync reports 0 users synced

| Cause | Fix |
|-------|-----|
| First run - no users to sync | Create users in Keycloak, then run sync again |
| Sync state file corrupted | Delete `.sync_state.json` and re-run |
| Keycloak users filtered out | Users with `bridge_test_` prefix are skipped by design |

**Symptom:** Daemon mode doesn't start

| Cause | Fix |
|-------|-----|
| Stale PID file | Delete `.daemon.pid` |
| Port conflict | Check if another daemon instance is running |

### iTop API Specific Issues

**Symptom:** `explode(): Argument #2 ($string) must be of type string, array given`

This occurs when passing `output_fields` with OQL queries. The fix is already applied in the scripts - avoid using `attrs` parameter with OQL keys.

**Symptom:** `Null not allowed` for Person creation

iTop Person class requires: `name`, `first_name`, `email`, `org_id`. Do NOT include `last_name` (not a valid field).

**Symptom:** `At least one profile must be assigned` for UserLocal

UserLocal creation requires `profile_list: [{"profileid": "<id>"}]`. The scripts handle this automatically.

## Debugging

### Enable Verbose Output

Run scripts directly to see detailed output:
```bash
python scripts/keycloak_setup.py
python scripts/itop_setup.py
python scripts/sync_bridge.py --sync
```

### Check Sync State

```bash
python scripts/sync_bridge.py --status
```

### Check Deployment Status

```bash
python scripts/bridge_deploy.py --status
```

### Manual API Testing

**Test Keycloak Auth:**
```bash
curl -X POST http://localhost:8080/realms/master/protocol/openid-connect/token \
  -d "username=admin&password=<pw>&grant_type=password&client_id=admin-cli"
```

**Test iTop Auth:**
```bash
curl -X POST http://localhost:25432/webservices/rest.php \
  -u admin:<pw> \
  -d "version=1.4&json_output=1&json_data={\"operation\":\"core/check_credentials\"}"
```

## Service Independence Verification

To verify graceful degradation:

1. **Stop Keycloak, test iTop:**
   ```bash
   docker stop keycloak
   python scripts/itop_setup.py
   # Should still connect to iTop successfully
   ```

2. **Stop iTop, test Keycloak:**
   ```bash
   docker stop itop
   python scripts/keycloak_setup.py
   # Should still connect to Keycloak successfully
   ```

## Log Locations

| Component | Log Location |
|-----------|-------------|
| Keycloak Docker | `docker compose logs keycloak` |
| iTop Docker | `docker compose logs itop` |
| Sync Bridge daemon | `/var/log/iam-bridge/` (if configured) |
| Sync state | `.sync_state.json` in iam-bridge directory |
