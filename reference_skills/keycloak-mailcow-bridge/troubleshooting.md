# Troubleshooting - Keycloak-Mailcow Bridge

## Deployment Architecture Issues

### 1. Mailcow HTTP API Returns 302/404

**Cause:** Custom Mailcow deployment has no nginx web server. Port 80 is occupied by GitLab's nginx.

**Diagnosis:**
```bash
curl -v http://localhost/api/v1/get/info/server
# Returns 302 redirect or connection refused
```

**Solution:** All Mailcow communication uses direct MySQL via `docker exec mysql-mailcow`. The scripts are pre-configured for this. No HTTP API key needed.

### 2. IMAP Authentication Fails Despite Correct Password

**Cause:** Multiple possible root causes:

#### A. Missing mail home directory
```bash
# Check if directory exists
docker exec dovecot-mailcow ls -la /var/vmail/mailcow.local/{username}/
# Fix: create it
docker exec dovecot-mailcow mkdir -p /var/vmail/mailcow.local/{username}
docker exec dovecot-mailcow chown vmail:vmail /var/vmail/mailcow.local/{username}
```

#### B. Plaintext password in mailbox table
Dovecot expects `{SSHA512}` prefixed passwords. Check:
```bash
docker exec mysql-mailcow mysql -uroot -p -e \
  "SELECT username, LEFT(password, 10) FROM mailcow.mailbox WHERE username = 'user'"
```
If password doesn't start with `{SSHA512}`, hash it:
```python
import hashlib, base64, secrets
salt = secrets.token_bytes(16)
h = hashlib.sha512(password.encode() + salt).digest()
hashed = "{SSHA512}" + base64.b64encode(h + salt).decode()
```

#### C. Full email as username in mailbox table
Dovecot splits login `user@domain.com` into `%n=user` and `%d=domain.com`. If `username` column stores `user@domain.com`, the query `WHERE username = 'user'` never matches. Fix:
```sql
UPDATE mailbox SET username = 'user' WHERE username = 'user@domain.com';
```

### 3. Shared Mailbox Quotas at 10TB

**Cause:** `create_mailbox()` in older code passed quota in bytes, then multiplied by `1024*1024` again.

**Fix:**
```sql
UPDATE mailbox SET quota = 10737418240 WHERE username IN ('security-shared', 'soc-shared');
-- 10GB = 10 * 1024 * 1024 * 1024 = 10737418240
```

### 4. Sync Engine Reports No Changes But Mailboxes Missing

**Cause:** Sync state file (`.sync_state.json`) tracks what's been synced. If mailboxes were manually deleted, the sync engine thinks they're still provisioned.

**Fix:** Delete the entry from `.sync_state.json` or remove the file entirely to force a full resync.

### 5. Keycloak 26.x Silently Drops Custom Attributes

**Cause:** Keycloak 26.x requires custom attributes to be declared in the realm's user profile configuration. PUT returns 204 but the attribute never persists.

**Impact:** `mailcow_template` attribute cannot be set on users via the standard API.

**Workaround:** The sync engine tracks state in `.sync_state.json` instead of relying on Keycloak user attributes. This is the tested and working approach.

### 6. SQL Parsing Errors (`KeyError: 'username'`)

**Cause:** MySQL query results use `-N` flag which suppresses column headers, causing the first data row to be interpreted as column names.

**Fix:** Ensure `_run_sql()` uses `-B` flag (batch mode with headers) without `-N`. The scripts are pre-fixed.

## Keycloak Issues

### 7. Keycloak Login Fails

**Diagnosis:**
```bash
# Test admin login
curl -X POST http://localhost:8080/realms/master/protocol/openid-connect/token \
  -d "grant_type=password" \
  -d "username=admin" \
  -d "password=$KEYCLOAK_ADMIN_PASSWORD" \
  -d "client_id=admin-cli"
```

**Common causes:**
- Wrong admin password in `.env`
- Keycloak container not running
- Port 8080 blocked

### 8. OIDC Client Not Found

**Cause:** The `mailcow-oidc` client wasn't created during setup.

**Fix:** Run `python3 scripts/keycloak_setup.py` to create it idempotently.

## Mailcow MySQL Issues

### 9. Cannot Connect to MySQL Container

**Diagnosis:**
```bash
docker exec mysql-mailcow mysql -uroot -p"$MYSQL_PASSWORD" -e "SELECT 1" mailcow
```

**Common causes:**
- Container name differs from `mysql-mailcow`
- MySQL password changed from default
- Container not running

### 10. Mailbox Table Schema Differs

**Diagnosis:**
```bash
docker exec mysql-mailcow mysql -uroot -p -e "DESCRIBE mailcow.mailbox"
```

**Expected columns:** `username`, `domain`, `password`, `quota`, `email_access`, `active`, `attributes`, `mailbox_path_prefix`

If columns differ (e.g., missing `attributes` JSON column), the sync engine's `create_mailbox()` may fail. Adjust the INSERT statement to match your schema.

## Debugging Commands

### Check Dovecot Auth Configuration

```bash
docker exec dovecot-mailcow cat /etc/dovecot/dovecot.conf
docker exec dovecot-mailcow cat /etc/dovecot/sql/passwd.sql
```

### Check Mailbox Status

```bash
docker exec mysql-mailcow mysql -uroot -p -e \
  "SELECT username, domain, active, quota FROM mailcow.mailbox"
```

### Check Sync State

```bash
cat .sync_state.json | python3 -m json.tool
```

### Test IMAP Authentication

```python
import imaplib
imap = imaplib.IMAP4("localhost", 143)
status, _ = imap.login("user@mailcow.local", "password")
print(status)  # Should print "OK"
imap.logout()
```

### Service Independence Verification

```bash
# Stop Keycloak - Mailcow should still work for local users
docker stop keycloak

# Stop Mailcow MySQL - Keycloak should still work
docker stop mysql-mailcow

# Restart services
docker start keycloak
docker start mysql-mailcow
```

## Log Locations

| Service | Log Command |
|---|---|
| Keycloak | `docker logs keycloak` |
| Dovecot | `docker logs dovecot-mailcow` |
| Postfix | `docker logs postfix-mailcow` |
| MySQL | `docker logs mysql-mailcow` |
| SOGo | `docker logs sogo-mailcow` |
| PHP-FPM | `docker logs php-fpm-mailcow` |
