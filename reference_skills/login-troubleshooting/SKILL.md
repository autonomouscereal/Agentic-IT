---
name: login-troubleshooting
description: >
  Detailed troubleshooting guide for demo_account_1 login failures across all AI Server platforms.
  Documents root cause analysis, diagnostic findings, attempted fixes, and remaining blockers
  for Wazuh, iTop, GitLab, and Keycloak authentication issues. Use when investigating login failures,
  debugging authentication, or fixing credential problems.
---

# Login Troubleshooting â€” Known Issues & Root Causes

**Date:** 2026-05-06
**Affected Account:** `demo_account_1`
**Password:** Stored in credential vault key `demo_account_1`; value rotated 2026-05-11.

---

## Resolution Update - 2026-05-11

`demo_account_1` has been repaired and rotated. The current password is stored only in vault key `demo_account_1`; do not write it to docs, scripts, logs, or shell history.

Verified checks:

| Platform | Verification |
|----------|--------------|
| iTop REST | PASS: `webservices/rest.php` returns `code:0` with `Administrator` + `REST Services User` profiles |
| Wazuh API | PASS: `/security/user/authenticate?raw=true` returns HTTP 200 |
| Wazuh Dashboard backend | PASS: OpenSearch Security `authinfo` recognizes `demo_account_1` |
| GitLab | PASS: Rails `valid_password?` returns true; user active and admin |
| Mailcow | PASS: mailbox exists; password flow delegated to Keycloak/Mailcow bridge |

Fixes applied:
- Rebuilt the iTop demo account as a valid `UserLocal` object. The previous direct SQL row could be counted by OQL but could not be reloaded as an object.
- Added the iTop REST Services profile (`1024`) so REST authentication is not blocked after login.
- Switched Wazuh password/user sync to the native Wazuh API first; direct RBAC SQLite is fallback only.
- Added Wazuh Dashboard internal user sync and securityadmin reload with a temporary `which` shim plus `OPENSEARCH_JAVA_HOME`.
- Removed hardcoded iTop/Mailcow DB passwords from `/home/cereal/multiplatform_user_manager.py`.
- Rotated the demo credential after an old failed iTop debug trace logged the test password; scrubbed the iTop error log pattern to `CheckCredentials("<redacted-demo-password>")`.

## Issue Summary

| Platform | Symptom | Root Cause | Status |
|----------|---------|------------|--------|
| GitLab web login | 422 error on login form | GitLab uses Keycloak OIDC SSO; `keycloak.internal:8443` unreachable | BLOCKED â€” DNS/network |
| Wazuh dashboard | "Invalid credentials" | User NOT in OpenSearch Security internal_users.yml; only in RBAC DB | FIXABLE â€” add to indexer |
| Wazuh API | 401 Invalid credentials | scrypt hash length mismatch (178 vs 162 chars) | FIXABLE â€” regenerate hash |
| iTop | "Incorrect login/password" | Hash correct in DB but login fails; possible cache/bridge issue | INVESTIGATING |
| Keycloak | N/A (IDP, not login target) | Passwords set in all realms | OPERATIONAL |

---

## GitLab â€” 422 Error / Keycloak OIDC Failure

### Symptom
User gets "422 â€” make sure you have access or contact an admin" when trying to log in.
Clicking "Sign in with Keycloak" gives: `Could not authenticate you from OpenIDConnect because "Failed to open tcp connection to keycloak.internal:8443 (connection refused)"`

### Root Cause
GitLab is configured with OmniAuth Keycloak OIDC SSO:
```ruby
gitlab_rails["omniauth_providers"] = [
    { "name" => "openid_connect",
      "label" => "Keycloak",
      "issuer" => "https://keycloak.internal:8443/realms/gitlab",
      "redirect_uri" => "http://192.168.50.222/users/auth/openid_connect/callback" }
]
gitlab_rails["omniauth_enabled"] = true
gitlab_rails["omniauth_allow_single_sign_on"] = true
gitlab_rails["omniauth_block_auto_created_users"] = true
```

**The `keycloak.internal:8443` hostname is unreachable from the GitLab container.** Keycloak has no external port mapping and the internal DNS resolution fails.

### Diagnostic Findings
- `demo_account_1` EXISTS in GitLab DB (User ID: 4, active, confirmed, admin)
- Password validated via Rails console: `valid_password?` returns `true`
- `omniauth_block_auto_created_users = true` means users must pre-exist (they do)
- Keycloak containers are running but have NO external port mappings
- Keycloak nginx reverse proxy has default config (no custom proxy rules)

### Fix Required
1. **Option A (Recommended)**: Fix Keycloak external accessibility
   - Add port mapping for Keycloak (8443 for HTTPS or 8080 for HTTP)
   - Ensure `keycloak.internal` resolves from the GitLab container's network
   - May need to add GitLab to the Keycloak Docker network or fix DNS

2. **Option B**: Disable Keycloak SSO for GitLab, use native login
   - Set `gitlab_rails["omniauth_enabled"] = false`
   - Reconfigure to allow native password login
   - Run `gitlab-ctl reconfigure` inside the container

3. **Option C**: Add hostname resolution
   - Ensure `keycloak.internal` resolves to the Keycloak container IP
   - May need `/etc/hosts` entry or Docker network configuration

---

## Wazuh Dashboard â€” OpenSearch Security Missing User

### Symptom
"Invalid credentials" when trying to log into the Wazuh dashboard UI at https://192.168.50.222:26443

### Root Cause
Wazuh has **TWO separate authentication systems**:
1. **OpenSearch Security** â€” Dashboard UI login (stored in `internal_users.yml` on the indexer)
2. **RBAC Database** â€” API access (stored in SQLite `rbac.db` on the manager)

`demo_account_1` was created in the RBAC DB but **NOT in OpenSearch Security**.

### Architecture
```
User login â†’ Dashboard UI â†’ OpenSearch Security (indexer container)
                                    â†“
                              (SEPARATE from)
API calls â†’ Wazuh API â†’ RBAC SQLite DB (manager container)
```

### Diagnostic Findings
- RBAC DB: user exists, ID=103, hash length=178, `allow_run_as=0`
- OpenSearch Security `internal_users.yml`: user NOT present
- The `internal_users.yml` is at `/usr/share/wazuh-indexer/config/opensearch-security/internal_users.yml`
- Users in this file use bcrypt hashes (`$2y$12$...`)
- The wazuh-wui service account works because it's defined in both systems

### Fix Required
1. Add `demo_account_1` to `internal_users.yml` on the indexer container:
   ```yaml
   demo_account_1:
     hash: "$2y$12$<bcrypt_hash_of_password>"
     reserved: false
     backend_roles:
       - "reading"
     description: "SOC Demo Account"
   ```
2. Generate bcrypt hash (OpenSearch has a hash generation tool at `plugin/tools/hash.sh` or use `python3 -c "import bcrypt; ..."`)
3. Run `securityadmin.sh` to load the updated configuration:
   ```bash
   docker exec wazuh_deploy-wazuh.indexer-1 /usr/share/wazuh-indexer/plugins/opensearch-security/tools/securityadmin.sh \
     -cd /usr/share/wazuh-indexer/plugins/opensearch-security/securityconfig/ \
     -icl -key /usr/share/wazuh-indexer/config/certs/admin-key.pem \
     -cert /usr/share/wazuh-indexer/config/certs/admin.pem \
     -cacert /usr/share/wazuh-indexer/config/certs/root-ca.pem \
     -nhnv -ssl -p 9200 -d /dev/null -p 9200 -cluster all
   ```
4. Also fix the RBAC DB hash (see below)

---

## Wazuh API â€” scrypt Hash Length Mismatch

### Symptom
Wazuh API returns 401 "Invalid credentials" for `demo_account_1` even though the user exists in the RBAC DB.

### Root Cause
The password hash was generated on the host (Python 3.12) with a 16-byte salt, producing a 178-character hash. Wazuh's internal users have 162-character hashes with 8-byte salts.

### Hash Comparison
```
wazuh-wui:    scrypt:32768:8:1$<16 hex chars>$<128 hex chars> = 162 chars
demo_account: scrypt:32768:8:1$<32 hex chars>$<128 hex chars> = 178 chars
```

| Component | wazuh-wui | demo_account_1 |
|-----------|-----------|----------------|
| Params | scrypt:32768:8:1 | scrypt:32768:8:1 |
| Salt (hex) | 16 chars (8 bytes) | 32 chars (16 bytes) |
| DK (hex) | 128 chars (64 bytes) | 128 chars (64 bytes) |
| **Total** | **162** | **178** |

### Additional Complication
The Wazuh manager container runs Python 3.9 with OpenSSL 3.x, which blocks `hashlib.scrypt(n=32768)` with "memory limit exceeded". The framework Python (3.10) has the same issue. **No Python on the container can generate scrypt hashes with n=32768.**

### Wazuh API Connection Behavior
- **HTTP connections**: Immediately closed with 0 bytes response
- **HTTPS connections**: Properly responds (401 for bad creds, 200 for good)
- **API logs**: Only show dashboard requests from 172.26.0.2 â€” our test requests don't appear in logs
- **TLS certs exist**: `/var/ossec/api/configuration/ssl/server.crt` and `server.key`
- **TLS config commented out** in `api.yaml` but certs are present â€” API appears to use TLS anyway

### Fix Required
1. Generate correct scrypt hash on the HOST (Python 3.12 with `maxmem` parameter):
   ```python
   import hashlib, secrets
   salt = secrets.token_bytes(8)  # 8 bytes, NOT 16
   dk = hashlib.scrypt(pw.encode(), salt=salt, n=32768, r=8, p=1, dklen=64, maxmem=67108864)
   hash_str = f"scrypt:32768:8:1${salt.hex()}${dk.hex()}"
   # Result should be exactly 162 characters
   ```
2. Deliver hash to the RBAC DB using `docker cp` (NOT `docker exec` with inline SQL â€” shell `$` expansion corrupts the hash)
3. Alternatively, use the Wazuh API to set the password (requires admin credentials â€” currently unknown)

---

## iTop â€” Hash Correct But Login Fails

### Symptom
"Incorrect login/password" when trying to log in at http://192.168.50.222:25432

### Root Cause (Under Investigation)
- Password hash IS correct: 60 characters, `$2b$12$` prefix (bcrypt)
- iTop uses local form authentication (`allowed_login_types => 'form|external|basic|token'`)
- Config at `/var/www/html/conf/production/config-itop.php`
- App root URL: `http://192.168.50.222:25432`

### Possible Causes
1. **iTop application cache** needs clearing (tried clearing lib cache dirs but those were PHP source, not runtime cache)
2. **Keycloak bridge** may be overwriting the bcrypt hash with phpass format on sync
3. **iTop runtime cache** in a location not yet identified
4. **User status/profile** issue in the database

### Diagnostic Commands
```bash
# Check hash
docker exec -i itop-deployment-db-1 mariadb -uitop -p"<from container MYSQL_PASSWORD>" itop -e \
  "SELECT pu.login, length(pul.password_hash) as len, substr(pul.password_hash, 1, 15) as prefix \
   FROM priv_user pu JOIN priv_user_local pul ON pul.id = pu.id \
   WHERE pu.login = 'demo_account_1';"

# Expected output: demo_account_1 | 60 | $2b$12$...
```

### Fix Required
1. Find and clear iTop runtime cache (not lib cache)
2. Check if Keycloak bridge sync is overwriting the password hash
3. Verify user status and profile assignment in DB
4. Test login via iTop REST API if available

---

## Keycloak â€” Internal Connectivity Issues

### Symptom
Services that need to connect to Keycloak (GitLab OIDC) get "connection refused" for `keycloak.internal:8443`

### Root Cause
- Keycloak containers have NO external port mappings
- Keycloak nginx reverse proxy has default config (no custom proxy to Keycloak)
- Internal hostname `keycloak.internal` may not resolve from all Docker networks
- Keycloak runs on internal port 8080 (HTTP) â€” port 8443 (HTTPS) may not be configured

### Keycloak Realms
All 5 realms configured: `master`, `itop`, `wazuh`, `mailcow`, `gitlab`
`demo_account_1` exists in `itop`, `wazuh`, and `gitlab` realms with passwords set.

### Fix Required
1. Verify Keycloak is listening on 8443 (or reconfigure GitLab to use 8080)
2. Ensure Docker network connectivity between GitLab and Keycloak
3. Fix DNS resolution for `keycloak.internal` across networks
4. Check Keycloak nginx reverse proxy configuration

---

## Shell Expansion Bug (Critical Pattern)

### Problem
When passing password hashes through `docker exec` commands, the `$` characters in hashes are interpreted as shell variable expansion:
- bcrypt: `$2b$12$...` â†’ shell tries to expand `2b`, `12`, etc.
- scrypt: `scrypt:32768:8:1$...` â†’ shell expands after the `$`

### Solution Pattern
**NEVER pass hashes with `$` through `docker exec` inline.** Use `docker cp` instead:

```bash
# WRONG â€” hash gets corrupted
docker exec container mysql -e "UPDATE users SET password='$2b$12$...' WHERE id=1"

# CORRECT â€” write to file, copy, execute
echo "UPDATE users SET password='\$2b\$12\$...' WHERE id=1;" > /tmp/fix.sql
docker cp /tmp/fix.sql container:/tmp/fix.sql
docker exec container bash -c "mysql < /tmp/fix.sql"
```

### Affected Operations
- Wazuh password hash delivery (scrypt)
- iTop password hash delivery (bcrypt)
- Any future password operations that involve `$` in the hash

---

## Temp Scripts on AI Server (Cleanup Needed)

The following temporary scripts are scattered in `/home/cereal/` and should be cleaned up:
- `fix_wazuh.py`, `fix_wazuh2.py` â€” Wazuh fix attempts
- `fix_itop.py`, `fix_itop_final.py` â€” iTop fix attempts
- `fix_all.py` â€” Combined fix script
- `login_check.py`, `deep_check.py`, `test_logins.py`, `final_tests.py` â€” Diagnostic scripts
- `wazuh_verify.py`, `wazuh_api_test.py` â€” Wazuh verification
- `gitlab_check.rb`, `gitlab_create.rb`, `gitlab_admin.rb` â€” GitLab scripts
- `temp_*.py` â€” Various temp scripts

---

## Priority Fix Order (Recommended)

1. **Keycloak external accessibility** â€” Blocks GitLab SSO and any SSO-dependent service
2. **Wazuh OpenSearch Security user creation** â€” Dashboard login fix
3. **Wazuh RBAC hash regeneration** â€” API login fix (8-byte salt)
4. **iTop cache/bridge investigation** â€” Login fix
5. **Temp script cleanup** â€” Housekeeping

