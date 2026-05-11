---
name: itop-manager
description: Manage the iTop ITSM v3.2.1 instance on AI Server (192.168.50.222) via Docker. Create/update/delete incidents, changes, requests, servers, and CMDB objects through the REST API. Apply workflow stimuli for state transitions including approval chains. Execute the Python client script remotely via SSH.
when_to_use: iTop operations, ITSM ticket management, incident/change/request lifecycle, Docker container management for iTop, REST API calls to iTop, ITIL workflows, approval chains, assignment groups, escalation testing.
allowed-tools: Bash("C:/Users/cereal/.Codex/skills/server-manager/ssh_client.py" "--ai" "--execute" "*"), Read, Edit, Write, Glob, Grep
---

# iTop ITSM Manager

iTop v3.2.1 runs in Docker (`supervisions/itop:3.2.1`) on AI Server. All API calls hit `http://localhost:25432/webservices/rest.php` on the remote host via the SSH client.

Full deployment blueprint (Docker Compose, all troubleshooting issues, recovery procedures) is in [DEPLOYMENT.md](DEPLOYMENT.md).

## Remote Execution

```bash
"C:/Users/cereal/.Codex/skills/server-manager/ssh_client.py" --ai --execute "python3 /home/cereal/SOC_TESTING/itop-deployment/scripts/itop_client.py check"
```

## Quick Operations

| Operation | Command |
|-----------|---------|
| Check auth | `...ssh_client.py" --ai --execute "python3 .../itop_client.py check"` |
| Get object | `...ssh_client.py" --ai --execute "python3 .../itop_client.py get Incident 1"` |
| Create | `...ssh_client.py" --ai --execute "python3 .../itop_client.py create Incident '{\"org_id\":1,\"caller_id\":1,\"title\":\"X\",\"description\":\"Y\",\"impact\":3,\"urgency\":3}'"` |
| Update | `...ssh_client.py" --ai --execute "python3 .../itop_client.py update Incident 1 '{\"title\":\"New title\"}'"` |
| Delete | `...ssh_client.py" --ai --execute "python3 .../itop_client.py delete Incident 1"` |
| Stimulus | `...ssh_client.py" --ai --execute "python3 .../itop_client.py stimulus Incident 1 ev_resolve"` |

Full Docker management commands in [DEPLOYMENT.md](DEPLOYMENT.md).

---

## Critical API Rules

1. **Dual Auth**: Every request needs BOTH Basic Auth header AND `user`/`password` in JSON payload.
2. **`Change` is ABSTRACT**: Never instantiate directly. Use `RoutineChange`, `NormalChange`, or `EmergencyChange`.
3. **Non-existent classes**: `Problem`, `Request`, `ChangeMajor`, `ChangeNormal`, `ChangeEmergency`, `RFC` do not exist. Use `UserRequest` for service requests.
4. **Non-existent operations**: `core/search`, `core/list` do not exist in v1.4. Only `core/get` by key.
5. **Stimulus requires `comment` + `fields`**: `core/apply_stimulus` needs both (even if `fields` is `{}`).
6. **Delete requires `comment`**: `core/delete` needs a comment parameter.
7. **Key extraction**: Nested at `response["objects"]["Class::key"]["fields"]["key"]`, never top-level.
8. **`output_fields` format**: Comma-separated string (`"title,status"`), not an array.
9. **Date format**: `"Y-m-d H:i:s"` for datetime fields (e.g., `"2026-04-29 10:30:00"`).
10. **Changes have no `solution` field**: `ev_implement` on Change classes uses empty fields `{}`. `solution` is an Incident/UserRequest attribute only.

---

## Available Classes

| Class | Description | Required Fields |
|-------|-------------|-----------------|
| `Organization` | Organizations | name |
| `Person` | Users | name |
| `Team` | Groups (assignment targets) | name, org_id |
| `Server` | Server assets | name, status (`production`) |
| `Incident` | ITIL incidents | title, description, impact, urgency, org_id, caller_id |
| `RoutineChange` | Routine changes (no CAB) | title, description, org_id |
| `NormalChange` | Changes with CAB approval | title, description, org_id |
| `EmergencyChange` | Emergency changes | title, description, org_id |
| `UserRequest` | Service requests | title, description, org_id |

---

## Stimulus Reference

| Stimulus | Effect | Required Fields |
|----------|--------|-----------------|
| `ev_validate` | Validate change (new -> validated) | `acceptance_date`, `acceptance_comment` |
| `ev_assign` | Assign to team | none (team_id set at create or via update) |
| `ev_plan` | Plan implementation | `start_date`, `end_date`, `impact`, `fallback` |
| `ev_approve` | CAB approve | `approval_date`, `approval_comment` |
| `ev_implement` | Implement change | none (empty `{}` for Change classes) |
| `ev_finish` | Close change | none |
| `ev_resolve` | Resolve incident/request | `resolution_code`, `solution` |
| `ev_close` | Close resolved item | none |
| `ev_pending` | Set pending (from "assigned" only) | `pending_reason` |
| `ev_reject` | Reject/reopen | Valid only from specific states (not from "resolved") |

---

## State Machine Lifecycles

### Incident
```
new -> ev_assign -> assigned -> ev_resolve -> resolved -> ev_close -> closed 2
                         -> ev_pending -> pending (from assigned)
```
- `ev_resolve` requires `resolution_code` + `solution`

### RoutineChange
```
new -> ev_assign -> assigned -> ev_plan -> plannedscheduled -> ev_implement -> implemented -> ev_finish -> closed
```
- `ev_plan` requires `start_date`, `end_date`, `impact`, `fallback`

### NormalChange (full CAB approval)
```
new -> ev_validate -> validated -> ev_assign -> assigned -> ev_plan -> plannedscheduled -> ev_approve -> approved -> ev_implement -> implemented -> ev_finish -> closed
```
- `ev_validate` requires `acceptance_date`, `acceptance_comment`
- `ev_plan` requires `start_date`, `end_date`, `impact`, `fallback`
- `ev_approve` requires `approval_date`, `approval_comment`

### UserRequest
```
new -> ev_assign -> assigned -> ev_resolve -> resolved -> ev_close -> closed 2
```
- Supports `approver_id` field for approval delegation
- Supports `escalation_flag`, `escalation_reason`, `pending_reason`

---

## Approval Chain Details (Verified)

NormalChange approval fields populate progressively through the lifecycle:

| State | Fields Populated |
|-------|-----------------|
| `new` | `approval_date=''`, `approval_comment=''`, `acceptance_date=''`, `acceptance_comment=''` |
| `validated` | `acceptance_date` and `acceptance_comment` filled |
| `approved` | `approval_date` and `approval_comment` filled |
| `closed` | All approval fields retained for audit |

### UserRequest Approver Assignment
- `approver_id` can be set at creation time (e.g., `"approver_id": 1`)
- `approver_id_friendlyname` returns the approver's display name
- `approver_email` field available but empty by default

### Escalation Fields
Available on Ticket subclasses (Incident, UserRequest):
- `escalation_flag` — set to `"yes"` to flag for escalation
- `escalation_reason` — free-text reason
- `tto_escalation_deadline` — time-to-operate escalation deadline
- `ttr_escalation_deadline` — time-to-respond escalation deadline
- `pending_reason` — set via `ev_pending` stimulus
- `last_pending_date` — auto-populated when pending
- `cumulatedpending` — accumulated pending time

### Assignment Groups
- Create `Team` objects with `name` + `org_id`
- Assign incidents/changes via `team_id` field at creation
- `team_name` field returns the team's display name

---

## REST API Reference

All POST to `/webservices/rest.php` with body: `version=1.4&json_output=1&json_data=<URL_ENCODED_JSON>`

| Operation | Required (plus user/password) |
|-----------|------------------------------|
| `core/check_credentials` | none |
| `core/get` | class, key |
| `core/create` | class, fields, comment |
| `core/update` | class, key, fields, comment |
| `core/delete` | class, key, comment |
| `core/apply_stimulus` | class, key, stimulus, comment, fields |
| `core/get_related` | class, key, link_class |

---

## Environment

| Item | Value |
|------|-------|
| Host | 192.168.50.222 (Debian, Docker) |
| Deploy path | `/home/cereal/SOC_TESTING/itop-deployment` |
| Container | `itop-deployment-itop-1` |
| Port mapping | 25432 -> 80 |
| DB | MariaDB LTS, user `itop`, password (vault key: `itop_mysql`) |
| Config | `./itop/conf:/var/www/html/conf` |
| Credentials | `admin` / (vault key: `itop_web`) |
| `secure_rest_services` | Must be `false` in config |

---

## Known Issues Quick Reference

| Issue | Fix |
|-------|-----|
| UI security warning for writable config | `chmod 0440 /var/www/html/conf/production/config-itop.php` |
| Broken UI asset URLs like `:25432images` | Add trailing slash to `app_root_url` |
| `--use_itop_config` causes 99.9% CPU loop | Never use for fresh installs |
| `UnknownLanguage` error | Use uppercase: `EN US` |
| `secure_rest_services` blocks REST | Set to `false` in `$MySettings` |
| "Cannot instantiate abstract class Change" | Use RoutineChange/NormalChange/EmergencyChange |
| "Missing parameter user/password" | Include in BOTH header and payload |
| "Missing parameter fields" on stimulus | Always include `fields: {}` |
| "Wrong format for date" | Use `"Y-m-d H:i:s"` |
| "Unknown attribute solution from class NormalChange" | Changes don't have `solution` - use empty `{}` |
| "Invalid stimulus on state X" | Check state machine; stimuli are state-dependent |

Full troubleshooting with root causes and fixes: [DEPLOYMENT.md](DEPLOYMENT.md)

### UI Security Warning and Asset URL Fix

If `http://HOST:25432/` shows only the iTop config-file security warning, make
the production config read-only inside the container:

```bash
docker exec itop-deployment-itop-1 sh -lc 'chmod 0440 /var/www/html/conf/production/config-itop.php'
```

If the login page loads but CSS/fonts/images are broken and generated URLs look
like `http://HOST:25432images/...`, update `app_root_url` so it ends with `/`:

```bash
docker exec itop-deployment-itop-1 sh -lc "chmod 0640 /var/www/html/conf/production/config-itop.php && sed -i \"s#'app_root_url' => 'http://192.168.50.222:25432'#'app_root_url' => 'http://192.168.50.222:25432/'#\" /var/www/html/conf/production/config-itop.php && chmod 0440 /var/www/html/conf/production/config-itop.php"
```

Use the environment's real iTop base URL. The lab fix was verified on
2026-05-11: root redirects to `/pages/UI.php`, login returns HTTP 200, and
asset URLs include the slash after `:25432/`.
