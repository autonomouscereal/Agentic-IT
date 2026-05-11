# Wazuh Bridge - Troubleshooting Guide

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

### Wazuh Connection Failures

**Symptom:** `Connection failed` or timeout on Wazuh REST API calls

| Cause | Fix |
|-------|-----|
| Wazuh container not running | Check container status, restart if needed |
| Wrong port | Verify Wazuh API on port 26500 |
| SSL certificate issues | Scripts use ssl.CERT_NONE for self-signed certs |
| Wazuh still initializing | Wait for Wazuh to fully start (can take 60+ seconds) |

**Diagnosis:**
```bash
curl -k https://localhost:26500/manager/status
# Expected: 401 (auth required) or 200 with valid JWT
```

### Authentication Failures

**Symptom:** `[AUTH FAILED]` or `[FAIL] Wazuh authentication failed`

| Cause | Fix |
|-------|-----|
| Wrong password in .env | Update `.env` with correct credentials |
| .env file not found | Ensure `.env` exists in wazuh-bridge directory |
| .env file has wrong permissions | `chmod 600 .env` |
| JWT token expired | Tokens expire after ~15 minutes; scripts re-auth automatically |

### Wazuh User Creation Failures

**Symptom:** `[FAIL] Create 'username': already exists`

| Cause | Fix |
|-------|-----|
| User already exists in Wazuh | The sync is idempotent; this is expected on re-runs |
| Duplicate username | Wazuh usernames must be unique |

### Sync Bridge Issues

**Symptom:** Sync reports 0 users synced

| Cause | Fix |
|-------|-----|
| First run - no users in wazuh realm | Create users in Keycloak wazuh realm, then run sync |
| Sync state file corrupted | Delete `.sync_state.json` and re-run |
| Keycloak users filtered out | Users with `bridge_test_` prefix are skipped by design |

**Symptom:** Daemon mode doesn't start

| Cause | Fix |
|-------|-----|
| Stale PID file | Delete `.daemon.pid` |

### Wazuh API Specific Issues

**Symptom:** 401 Unauthorized after initial success

Wazuh JWT tokens expire after ~15 minutes. The scripts handle re-authentication automatically, but if testing manually:
```bash
# Re-authenticate
TOKEN=$(curl -sk -u wazuh-wui:YOUR_PASSWORD \
  -X GET "https://localhost:26500/security/user/authenticate?raw=true")
```

**Symptom:** User created but cannot authenticate

The sync creates Wazuh users with random secure passwords. To set a known password:
```bash
curl -sk -H "Authorization: Bearer $TOKEN" \
  -X PUT "https://localhost:26500/security/users/{user_id}/password" \
  -H "Content-Type: application/json" \
  -d '{"password": "<new-password-from-vault>"}'
```

## Debugging

### Enable Verbose Output

Run scripts directly to see detailed output:
```bash
python scripts/keycloak_setup.py
python scripts/wazuh_setup.py
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

**Test Wazuh Auth:**
```bash
curl -k -u wazuh-wui:YOUR_PASSWORD \
  https://localhost:26500/security/user/authenticate?raw=true
```

**List Wazuh Users:**
```bash
TOKEN=$(curl -sk -u wazuh-wui:YOUR_PASSWORD \
  -X GET "https://localhost:26500/security/user/authenticate?raw=true")
curl -sk -H "Authorization: Bearer $TOKEN" \
  "https://localhost:26500/security/users"
```

## Service Independence Verification

To verify graceful degradation:

1. **Stop Keycloak, test Wazuh:**
   ```bash
   docker stop keycloak
   python scripts/wazuh_setup.py
   # Should still connect to Wazuh successfully
   ```

2. **Stop Wazuh, test Keycloak:**
   ```bash
   docker stop wazuh.manager
   python scripts/keycloak_setup.py
   # Should still connect to Keycloak successfully
   ```

## Log Locations

| Component | Log Location |
|-----------|-------------|
| Keycloak Docker | `docker compose logs keycloak` |
| Wazuh Manager | `docker compose logs wazuh.manager` in wazuh_deploy dir |
| Wazuh API logs | `/var/ossec/logs/ossec.log` inside container |
| Sync state | `.sync_state.json` in wazuh-bridge directory |
