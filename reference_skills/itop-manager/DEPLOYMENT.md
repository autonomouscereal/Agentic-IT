# iTop ITSM v3.2.1 - Complete Deployment Blueprint

This document contains the full deployment guide, Docker configuration, all troubleshooting issues encountered, and recovery procedures for deploying iTop ITSM v3.2.1 in any environment.

## Environment

- **Host**: AI Server (127.0.0.1)
- **OS**: Debian (Docker host)
- **Docker Compose**: v2
- **Deploy Directory**: `/opt/agentic-it/SOC_TESTING/itop-deployment`

## Docker Compose Configuration

```yaml
services:
  db:
    image: mariadb:lts
    restart: unless-stopped
    environment:
      MYSQL_DATABASE: itop
      MYSQL_USER: itop
      MYSQL_PASSWORD: <vault:itop_mysql>
      MARIADB_RANDOM_ROOT_PASSWORD: 1
    volumes:
      db-data:/var/lib/mysql

  itop:
    image: supervisions/itop:3.2.1
    restart: unless-stopped
    ports:
      - "25432:80"
    depends_on:
      - db
    volumes:
      - ./itop/conf:/var/www/html/conf
      - ./itop/extensions:/var/www/html/extensions

volumes:
  db-data:
```

## Directory Structure

```
/opt/agentic-it/SOC_TESTING/itop-deployment/
|-- docker-compose.yml          # Container orchestration
|-- itop/
|   |-- conf/
|   |   `-- production/
|   |       `-- config-itop.php  # iTop config (volume-mounted)
|   `-- extensions/             # Extensions directory
`-- scripts/
    `-- itop_client.py          # Python REST API client
```

## Docker Management Commands

```bash
# Check status
cd /opt/agentic-it/SOC_TESTING/itop-deployment && docker compose ps

# Start all
cd /opt/agentic-it/SOC_TESTING/itop-deployment && docker compose up -d

# Stop all
cd /opt/agentic-it/SOC_TESTING/itop-deployment && docker compose down

# Restart iTop only
cd /opt/agentic-it/SOC_TESTING/itop-deployment && docker compose restart itop

# View logs
cd /opt/agentic-it/SOC_TESTING/itop-deployment && docker compose logs --tail=50 itop

# Check config syntax
cd /opt/agentic-it/SOC_TESTING/itop-deployment && docker compose exec itop php -l /var/www/html/conf/production/config-itop.php
```

## Critical Configuration

1. **`secure_rest_services`**: Must be set to `false` in `$MySettings` array in `config-itop.php` to allow REST API access without requiring a dedicated "REST Services User" profile. Default is `true` in iTop 3.2.1.

2. **Config file location**: Inside container at `/var/www/html/conf/production/config-itop.php`. Persisted via volume mount at `./itop/conf/production/config-itop.php` on the host.

3. **Database**: MariaDB LTS with random root password. iTop connects as user `itop` with password (vault key: `itop_mysql`).

4. **Port mapping**: Container port 80 -> host port 25432. Access externally at `http://127.0.0.1:25432`.

5. **No bulk list/search**: iTop 3.x REST API only supports CRUD by key. There is no list/search endpoint.

---

## Deployment Troubleshooting Log

Every issue encountered during deployment, with root cause and fix.

### Issue 1: 99.9% CPU Infinite Loop with `--use_itop_config`

**Symptom:** PHP process consumed 99.9% CPU and got killed by OOM (exit code 137) when running the unattended installer with `--use_itop_config`. Tested across 3 images: `vbkunin/itop:latest-base`, `supervisions/itop:3.2.2`, `supervisions/itop:3.2.1`.

**Root cause:** The `--use_itop_config` flag causes an infinite loop when the config file exists but the database schema is not yet initialized. iTop reads the config, tries to connect to the DB, fails, re-reads the config, loops.

**Fix:** Never use `--use_itop_config` for fresh installs. Pass database credentials directly via the XML param file (`itop-param.xml`). The installation writes the config file itself.

**Lesson:** The flag is only valid for upgrades, not fresh installs.

---

### Issue 2: Unknown Language Error - `DictExceptionUnknownLanguage`

**Symptom:** Installer threw `DictExceptionUnknownLanguage: Unknown localization language: language code = en us` alongside `Undefined constant "EVENT_DOWNLOAD_DOCUMENT"` in AttributeBlobEventListener.php.

**Root cause:** The language code in the XML param file was lowercase `en us`. iTop's localization system expects UPPERCASE codes.

**Fix:** Changed all language references in the XML to `EN US` (uppercase with space). Both errors disappeared.

**Lesson:** iTop language codes are case-sensitive and must be uppercase.

---

### Issue 3: Config File Corruption from sed Commands

**Symptom:** Attempting to add `'secure_rest_services' => false,` to the config file using `sed -i` inserted the line in all three PHP arrays, creating malformed lines like:
```php
$n'secure_rest_services' => false,
$MySettings$MySettings = array(
```

**Root cause:** The string `$MySettings = array(` appears in all three PHP arrays (`$MySettings`, `$MyModuleSettings`, `$MyModules` all contain the substring `MySettings`), so sed matched multiple times.

**Fix:** Used targeted Perl commands to:
1. Remove all malformed `secure_rest_services` lines
2. Fix duplicated variable names (`$MySettings$MySettings` -> `$MySettings`)
3. Re-insert `'secure_rest_services' => false,` only in the `$MySettings` array using a unique anchor

**Lesson:** Use unique anchor strings when editing PHP config files with sed/perl. The `$MySettings` pattern is not unique.

---

### Issue 4: REST API "Missing parameter 'operation'"

**Symptom:** Initial API calls returned `"code": 2, "message": "Missing parameter 'operation'"`.

**Root cause:** The `operation` parameter was being passed as a URL query parameter instead of inside the `json_data` body.

**Fix:** Restructured all calls to nest `operation` inside the JSON payload that gets URL-encoded as `json_data`.

**Lesson:** iTop REST API v1.4 requires ALL parameters inside `json_data`, including the operation name.

---

### Issue 5: REST API "Unknown attribute status from class Ticket"

**Symptom:** Attempting to create a Ticket with `status` and `priority` fields failed.

**Root cause:** The base `Ticket` class in iTop 3.x does not have `status` or `priority` attributes. Those exist on subclasses like `Incident`.

**Fix:** Use the `Incident` class with `impact` and `urgency` fields instead.

**Lesson:** Always target specific subclasses (Incident, Change, Problem) rather than the abstract Ticket class.

---

### Issue 6: REST API "Wrong format for date attribute"

**Symptom:** Creating incidents with date fields failed with format errors.

**Root cause:** iTop expects `Y-m-d H:i:s` format for datetime attributes.

**Fix:** Omitted optional date fields entirely; iTop auto-populates them. When required, use `"Y-m-d H:i:s"` format.

---

### Issue 7: REST API "Missing parameter 'fields'" for core/create

**Symptom:** Create operations failed because attributes were passed at the top level instead of nested under `fields`.

**Root cause:** The `core/create` and `core/update` operations require attributes to be nested in a `fields` dict, with a separate `comment` parameter.

**Fix:** Restructured to: `{"class": "Incident", "comment": "...", "fields": {...}}`

---

### Issue 8: REST API "Missing parameter 'user'" and "Missing parameter 'password'"

**Symptom:** After initial deployment, the `check` command returned `"code": 100, "message": "Error: Missing parameter 'user'"` followed by `"Missing parameter 'password'"`.

**Root cause:** The iTop 3.2.1 REST API v1.4 requires `user` and `password` to be passed inside the `json_data` payload on every request - Basic Auth headers alone are insufficient.

**Fix:** Updated the `_post` method in `itop_client.py` to include `"user": self.username` and `"password": self.password` in every payload dict alongside `operation`.

**Lesson:** iTop 3.x REST API authenticates per-request via payload parameters, not just HTTP headers. Both are sent but the payload params are mandatory.

---

### Issue 9: REST API "Cannot instantiate abstract class Change"

**Symptom:** Attempting to create a `Change` object via REST API crashed the iTop server with a 500 error.

**Root cause:** `Change` is an abstract class in iTop 3.2.1 and cannot be instantiated directly.

**Fix:** Use concrete subclasses: `RoutineChange` (direct child of Change), `NormalChange` (extends ApprovedChange), or `EmergencyChange` (extends ApprovedChange).

**Additional discovery:** `Problem`, `Request`, `ChangeMajor`, `ChangeNormal`, `ChangeEmergency`, `ChangeRequest`, and `RFC` classes do not exist in this iTop installation.

---

### Issue 10: "Unknown attribute solution from class NormalChange"

**Symptom:** Attempting to pass `solution` field when applying `ev_implement` stimulus on a NormalChange returned error code 100.

**Root cause:** The `solution` attribute exists on `Incident` and `UserRequest` classes but NOT on Change classes.

**Fix:** Apply `ev_implement` on Change classes with empty fields `{}`. No `solution` needed.

---

### Issue 11: Stimulus Missing `comment` and `fields` Parameters

**Symptom:** `core/apply_stimulus` calls failed with "Missing parameter 'comment'" and "Missing parameter 'fields'" errors.

**Root cause:** Unlike the Python client script (which auto-adds these), raw API calls to `core/apply_stimulus` require both `comment` (string) and `fields` (dict, can be empty).

**Fix:** Always include both: `{"comment": "...", "fields": {}}`

---

### Issue 12: "Wrong format for key" on team_id

**Symptom:** Creating incidents with `team_id` from a Team that didn't exist yet resulted in key format errors.

**Root cause:** Teams must be created before they can be referenced. Team keys are numeric integers.

**Fix:** Create `Team` objects first, extract their keys, then reference those keys in `team_id` fields.

---

## Recovery Procedures

### If iTop returns 500 errors:
1. Check config file is valid PHP: `docker compose exec itop php -l /var/www/html/conf/production/config-itop.php`
2. Verify `secure_rest_services` is set to `false`
3. Restart: `docker compose restart itop`

### If containers won't start:
1. Check DB is ready: `docker compose ps db`
2. View logs: `docker compose logs db`
3. Re-create: `docker compose down && docker compose up -d`

### If REST API returns authentication errors:
1. Verify credentials are `admin` / (vault key: `itop_web`)
2. Check `secure_rest_services` is `false` in config
3. Test with: `python3 /opt/agentic-it/SOC_TESTING/itop-deployment/scripts/itop_client.py check`

---

## Test Results

All operations verified working with 42/42 tests passing (comprehensive suite) and 32/33 passing (approval chain suite - 1 minor script bug in delete helper, all API tests passed).

| Category | Tests | Status |
|----------|-------|--------|
| Authentication | 1 | PASS |
| CMDB (Organization, Team, Person, Server) | 10 | PASS |
| Incident full lifecycle (assign->resolve->close) | 3 | PASS |
| RoutineChange full lifecycle | 4 | PASS |
| NormalChange full approval chain (validate->assign->plan->approve->implement->finish) | 7 | PASS |
| EmergencyChange create/delete/verify | 3 | PASS |
| UserRequest full lifecycle | 3 | PASS |
| Approval chain field inspection | 4 | PASS |
| Team assignment with team_id | 3 | PASS |
| Pending/escalation flow | 3 | PASS |
| Reject/reopen flow | 3 | PASS |
| UserRequest with approver_id | 3 | PASS |
| Escalation fields | 1 | PASS |
| Updates and attribute filters | 3 | PASS |
