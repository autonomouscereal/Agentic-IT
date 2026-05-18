---
name: mailcow
description: >
  Mailcow Email Server complete deployment blueprint for 192.168.50.222.
  Covers Docker Compose configuration, custom Dovecot entrypoints, TCP MySQL connectivity,
  database seeding, startup procedures, management scripts, service interaction,
  and complete troubleshooting catalog. Use when deploying, managing, or debugging
  the Mailcow email stack.
when_to_use: >
  Mailcow deployment, Docker Compose issues, Dovecot startup failures,
  Postfix SMTP problems, database seeding, service management, backup/restore,
  port conflicts, MySQL/Redis connectivity.
disable-model-invocation: false
user-invocable: true
---

# Mailcow Email Server — Complete Deployment Blueprint

**Version:** 3.0 | **Last Updated:** 2026-04-29 | **Status:** Production-Deployed

---

## Overview

Complete, reproducible blueprint for deploying a fully functional Mailcow email server on a bare-metal Ubuntu server using Docker Compose. Covers every step, every error encountered, every fix applied, and every configuration file.

**Current demo note (2026-05-18):** The custom mail path remains the canonical deployment, and the optional nginx/php-fpm/Roundcube shim now exposes a lab Mailcow UI at `http://192.168.50.222:2581`. The bare root URL is routed to the admin login surface, stale `MCSESSID` user sessions are recovered, admin login for `demo_account_1` reaches `/admin/dashboard`, dashboard/system/mailbox/queue/quarantine pages are free of invalid JSON and SQL-column warning banners, `/webmail` is a real Roundcube client backed by Mailcow IMAP/SMTP, `/SOGo/*` redirects to Roundcube, and IMAP auth for `demo_account_1@mailcow.local` returns `OK`. Report Phish proof: legacy demo ticket `578`, iTop Incident `370`, gate `167`, Hermes agent `227`, quarantine id `28cd6d435f7c88cd9a7b46983c62a1cb`; Roundcube proof ticket `580`, iTop Incident `372`, agent `229`, access request `581`, quarantine id `21a705b151642568d375c748a9ea1a6b`. The shim also keeps the read-only compatibility API on `8081`.

This is **NOT** the upstream `mailcow-dockerized` deployment. It is a custom-built, hand-tailored Mailcow stack with modified entrypoints, TCP database connectivity (no socket sharing), and custom database seeding.

### Architecture at a Glance

```
192.168.50.222 (Ubuntu 24.04.4, Docker 29.4.0, overlay2, 251GB RAM)
│
├── mailcow-network (bridge, 172.23.0.0/16)
│   ├── mysql-mailcow      (mariadb:10.6)       - Database backend
│   ├── redis-mailcow      (redis:7-alpine)     - Cache layer
│   ├── clamd-mailcow      (mailcow/clamd:1.70) - Antivirus scanner
│   ├── rspamd-mailcow     (mailcow/rspamd:2.0) - Spam filter + milter
│   ├── php-fpm-mailcow    (mailcow/phpfpm:1.92)- PHP app server
│   ├── sogo-mailcow       (mailcow/sogo:1.129) - Webmail/CalDAV/CardDAV
│   ├── dovecot-mailcow    (mailcow/dovecot:2.31) - IMAP/POP3/LMTP
│   └── postfix-mailcow    (mailcow/postfix:1.80) - SMTP relay
│
├── Wazuh SIEM (wazuh.manager, wazuh.dashboard, wazuh.indexer)
└── SearXNG, iTop, and other SOC/IT services
```

### Key Design Decisions

| Decision | Reason |
|----------|--------|
| TCP MySQL (not Unix socket) | overlay2 storage driver breaks socket sharing across containers |
| Custom entrypoint for Dovecot | Official entrypoint assumes socket + DNS resolution that doesn't exist |
| Custom docker-compose.yml | Upstream includes Unbound/netfilter/watchdog — not needed in our setup |
| Bind mounts (not Docker volumes) | All data lives under `/home/cereal/Mailcow/deploy/data/` for easy backup |
| `set +e` in entrypoint | Several upstream checks fail in our environment (missing templates, no replication) |
| Optional UI/API sidecars | `nginx-mailcow-api` serves API compatibility on `8081` and the demo UI on `2581`; `php-fpm-mailcow-api` uses the mounted web root with writable Twig cache |
| UI compatibility schema/assets | The custom seed must include `logs`, current-shape `tfa`, `fido2`, `settingsmap`, `templates`, and `mailbox.authsource`; extensionless routes must rewrite through FastCGI; generated CSS/JS must write to `/web/cache` with `?v=<filemtime>` URLs and no-store cache headers so nginx can serve fresh `/cache/<hash>` assets |
| UI table JSON compatibility | The sidecar must provide Mailcow/DataTables-shaped JSON for domain search, quarantine, and template reads; otherwise the browser shows invalid JSON dialogs, undefined/NaN fields, or SQL warning banners after login |
| Demo root route | The `:2581` bare root URL must FastCGI-route to `/admin/`; the custom root user-login flow can return a blank body after submit |
| Stale session recovery | `/` and `/admin/` strip incoming cookies, while `/user` clears `PHPSESSID` and `MCSESSID`; stale user sessions otherwise redirect to a blank 5-byte `/user` response |

---

## Table of Contents

1. [Prerequisites](#1-prerequisites)
2. [Server Setup](#2-server-setup)
3. [Directory Structure](#3-directory-structure)
4. [Environment Configuration](#4-environment-configuration)
5. [Docker Compose Configuration](#5-docker-compose-configuration)
6. [Custom Entrypoint for Dovecot](#6-custom-entrypoint-for-dovecot)
7. [Dovecot Configuration](#7-dovecot-configuration)
8. [Postfix Configuration](#8-postfix-configuration)
9. [Database Seeding](#9-database-seeding)
10. [Startup Procedure](#10-startup-procedure)
11. [Management Scripts](#11-management-scripts)
12. [Service Interaction Guide](#12-service-interaction-guide)
13. [Testing](#13-testing)
14. [Troubleshooting - Complete Error Catalog](#14-troubleshooting---complete-error-catalog)
15. [Integration with SOC Tools](#15-integration-with-soc-tools)
16. [Backup and Restore](#16-backup-and-restore)
17. [Ports Reference](#17-ports-reference)
18. [Version History](#18-version-history)

---

## 1. Prerequisites

### Hardware Requirements

| Resource | Minimum | Actual Server |
|----------|---------|---------------|
| RAM | 8GB | 251GB |
| CPU | 2 cores | Multi-core |
| Disk | 50GB | Ample |
| OS | Ubuntu 22.04+ | Ubuntu 24.04.4 |

### Software Requirements

- **Docker Engine** 24+ (server runs 29.4.0)
- **Docker Compose Plugin** (v5+)
- **Python 3.10+** (for seeding/test scripts)
- **Git** (for cloning configs)

### Port Requirements

| Port | Protocol | Service | Direction |
|------|----------|---------|-----------|
| 25 | TCP | SMTP (Postfix) | Inbound |
| 143 | TCP | IMAP (Dovecot) | Inbound |
| 465 | TCP | SMTPS (Postfix) | Inbound |
| 587 | TCP | Submission (Postfix) | Inbound |
| 993 | TCP | IMAPS (Dovecot) | Inbound |
| 11332 | TCP | Rspamd Milter | Internal |
| 11334 | TCP | Rspamd Web UI | Internal |

---

## 2. Server Setup

### Initial SSH Access

Connect via the SSH skill:

```bash
python "C:/Users/cereal/.agents/skills/server-manager/ssh_client.py" --server ai --test
```

Or interactively:

```bash
python "C:/Users/cereal/.agents/skills/server-manager/ssh_client.py" --server ai --interactive
```

### Verify Docker is Running

```bash
docker info --format '{{.ServerVersion}}'
docker compose version
```

### Create Base Directories

```bash
sudo mkdir -p /home/cereal/Mailcow/deploy
sudo mkdir -p /home/cereal/mailcow-dockerized/data/conf
sudo chown -R cereal:cereal /home/cereal/Mailcow
sudo chown -R cereal:cereal /home/cereal/mailcow-dockerized
```

---

## 3. Directory Structure

```
/home/cereal/
├── Mailcow/
│   └── deploy/                          # All orchestration files
│       ├── .env                         # Environment variables (DB creds, hostname)
│       ├── docker-compose.yml           # Service definitions (8 services)
│       ├── mailcow_start.sh             # Ordered startup script (MySQL/Redis first)
│       ├── start.sh                     # Simple docker compose start
│       ├── stop.sh                      # docker compose down
│       ├── restart.sh                   # docker compose restart
│       ├── status.py                    # Python status checker
│       ├── seed_db.py                   # Database schema creation (70+ tables)
│       ├── write_entrypoint.py          # Generates dovecot-entrypoint.sh
│       ├── fix_compose.py               # Writes docker-compose.yml with literal ${VAR} refs
│       ├── dovecot-entrypoint.sh        # Custom entrypoint (generated by write_entrypoint.py)
│       ├── dovecot-official-fixed-entrypoint.sh  # Modified official entrypoint (465 lines)
│       ├── test_smtp.py                 # SMTP/IMAP connectivity test
│       ├── test_email.py                # Send test email via SMTP
│       ├── test-api.sh                  # Full service test battery
│       ├── README.md                    # Quick reference
│       └── data/                        # Auto-created at runtime
│           ├── mysql/                   # MariaDB data
│           ├── redis/                   # Redis data
│           ├── clamav/                  # ClamAV signatures
│           ├── rspamd/                  # Rspamd learned data
│           ├── sogo/                    # SOGo profiles
│           ├── postfix/                 # Postfix spool
│           ├── acme/                    # ACME certificates
│           ├── mailcow-data/            # Mailcow web app data
│           ├── dovecot-mail-crypt/      # Mail crypto keys
│           └── dovecot-ssl/             # Dovecot SSL certs
│
└── mailcow-dockerized/
    └── data/
        └── conf/
            ├── dovecot/                 # Dovecot configuration (27 files)
            │   ├── dovecot.conf         # Main config (protocols, SSL, auth, plugins)
            │   ├── dovecot.folders.conf # Folder configuration
            │   ├── ssl.crt / ssl.key    # TLS certificates
            │   ├── dhparams.pem         # DH parameters
            │   ├── dovecot-master.passwd / dovecot-master.userdb  # Master auth
            │   ├── auth/                # Auth mechanisms
            │   ├── sql/                 # SQL userdb/quota configs
            │   ├── lua/                 # Lua scripts (passwd-verify.lua)
            │   ├── conf.d/              # Additional configs
            │   ├── global_sieve_before / global_sieve_after  # Sieve filters
            │   ├── sogo-sso.conf        # SOGo SSO integration
            │   └── sogo_trusted_ip.conf # SOGo trusted IP (disabled)
            └── postfix/                 # Postfix configuration
                ├── main.cf              # Main Postfix config
                ├── master.cf            # Service definitions
                ├── sql/                 # MySQL lookup tables
                ├── dns_blocklists.cf    # DNSBL configuration
                ├── postscreen_access.cidr  # Postscreen CIDR rules
                ├── custom_transport.pcre   # Custom transport rules
                ├── anonymize_headers.pcre  # Header anonymization
                └── sni.map              # TLS SNI mapping
```

---

## 4. Environment Configuration

### File: `.env`

```ini
MAILCOW_HOSTNAME=localhost
TZ=America/New_York
DBROOT=<from vault: mailcow_mysql_root>
DBUSER=mailcow
DBPASS=<from vault: mailcow_db_user>
DBNAME=mailcow
REDISPASS=<from vault: mailcow_redis>
```

**CRITICAL:** These variables are interpolated by Docker Compose at startup. Every service references them.

| Variable | Used By | Purpose |
|----------|---------|---------|
| `MAILCOW_HOSTNAME` | All services | FQDN for the mail server |
| `DBROOT` | MySQL, Dovecot, Postfix, php-fpm | MySQL root password |
| `DBUSER` | All services | MySQL application user |
| `DBPASS` | All services | MySQL application password |
| `DBNAME` | All services | Database name |
| `REDISPASS` | Redis, Dovecot, Rspamd, Postfix | Redis authentication |
| `TZ` | All services | System timezone |

**WARNING:** These credentials are in plaintext. Do NOT commit `.env` to version control.

> Credentials stored in server-manager vault. Retrieve with: `python "C:/Users/cereal/.agents/skills/server-manager/credman.py" get <name>`

---

## 5. Docker Compose Configuration

### File: `docker-compose.yml`

Defines 8 services on the `mailcow-network` bridge network. Written via `fix_compose.py` to preserve literal `${VAR}` references (yaml.dump() corrupts them).

#### Service Definitions

**mysql-mailcow** (mariadb:10.6)
- No host ports exposed (internal only)
- Health check: `mysqladmin ping` every 5s, 20 retries
- Volume: `./data/mysql` for persistence + `mysql-socket` named volume
- Command: `mysqld --innodb-file-per-table=1 --skip-name-resolve`

**redis-mailcow** (redis:7-alpine)
- No host ports exposed (internal only)
- Health check: `redis-cli ping` every 5s, 20 retries
- Volume: `./data/redis` for persistence

**clamd-mailcow** (mailcow/clamd:1.70)
- No host ports (internal only)
- Volume: `./data/clamav` for signatures

**rspamd-mailcow** (mailcow/rspamd:2.0)
- Ports: 11332 (milter), 11334 (web UI)
- Depends on: mysql (healthy), redis (healthy)
- Volumes: data, filters, logs

**php-fpm-mailcow** (mailcow/phpfpm:1.92)
- Depends on: mysql (healthy), redis (healthy)
- Mounts mysql-socket as read-only

**sogo-mailcow** (mailcow/sogo:1.129)
- Internal only (no host ports)
- SOGo configured with `MAILCOW_HOSTNAME`

**dovecot-mailcow** (mailcow/dovecot:2.31)
- Ports: 143 (IMAP), 993 (IMAPS)
- Depends on: mysql (healthy), redis (healthy)
- Mounts: mysql-socket (ro), dovecot config, crypto keys, filters, logs
- **CRITICAL:** Uses custom entrypoint (see section 6)

**postfix-mailcow** (mailcow/postfix:1.80)
- Ports: 25 (SMTP), 465 (SMTPS), 587 (Submission)
- Depends on: mysql (healthy), redis (healthy)
- Mounts: mysql-socket (ro), postfix config, SSL, logs

#### Network

```yaml
networks:
  mailcow-network:
    driver: bridge
```

Subnet: `172.23.0.0/16`, Gateway: `172.23.0.1`

#### Volumes

```yaml
volumes:
  mysql-socket:
    driver: local
```

---

## 6. Custom Entrypoint for Dovecot

### The Problem

The official Mailcow Docker entrypoint (`/app-entrypoint.sh`) does three things that break in our environment:

1. **Connects to MySQL via Unix socket** (`/var/run/mysqld/mysqld.sock`) — Docker overlay2 storage driver doesn't share sockets reliably across containers
2. **Waits for DNS resolution** (`dig mailcow.email`) — our hostname `localhost` won't resolve externally
3. **Generates SOGo trusted IP config** — requires `IPV4_NETWORK` env var, which we don't set, causing hostname errors like `.248`

### The Solution: Two Entrypoints

#### A. Simple Entrypoint (`dovecot-entrypoint.sh`)

Generated by `write_entrypoint.py`. Uses TCP MySQL connectivity throughout.

```bash
#!/bin/bash
set -e

# Wait for MySQL via TCP
while ! mariadb-admin status --ssl=false -h mysql -u${DBUSER} -p${DBPASS} --silent 2>/dev/null; do
  sleep 2
done

# Wait for Redis via TCP
REDIS_CMDLINE="redis-cli -h redis -p 6379 -a ${REDISPASS} --no-auth-warning"
while [[ $(${REDIS_CMDLINE} PING 2>/dev/null) != "PONG" ]]; do
  sleep 2
done

# Create quota/sieve dict configs with host=mysql (TCP, not socket)
cat <<EOF > /etc/dovecot/sql/dovecot-dict-sql-quota.conf
connect = "host=mysql dbname=${DBNAME} user=${DBUSER} password=${DBPASS_ESCAPED}"
...
EOF

# Run hooks, exec supervisord
exec "$@"
```

**Key:** All `connect` strings use `host=mysql` (TCP via Docker DNS), NOT `host=/var/run/mysqld/mysqld.sock`.

#### B. Modified Official Entrypoint (`dovecot-official-fixed-entrypoint.sh`)

465-line modified version of the official entrypoint. Changes made:

| Line | Original | Fixed |
|------|----------|-------|
| 2 | `set -e` | `set +e` (tolerant of failures) |
| 5 | `--socket=/var/run/mysqld/mysqld.sock` | `-h mysql` (TCP) |
| 10-13 | DNS wait loop (`dig mailcow.email`) | **Commented out** |
| 124 | `chmod /templates/quarantine.tpl` | Added `\|\| true` |
| 314-320 | SOGo trusted IP generation | **Commented out** |
| All SQL | `host=/var/run/mysqld/mysqld.sock` | `host=mysql` |

### How Docker Start Uses It

In `mailcow_start.sh`, Dovecot is launched with `docker run` (not compose) to override the entrypoint:

```bash
docker run -d --name dovecot-mailcow \
    --network deploy_mailcow-network \
    --restart unless-stopped \
    --entrypoint /dovecot-entrypoint.sh \
    -p 143:143 -p 993:993 \
    -v mysql-socket:/var/run/mysqld:ro \
    -v mysql-socket:/run/mysqld:ro \
    -v $COMPOSE_DIR/data/dovecot-mail-crypt:/mail_crypt:ro \
    -v /home/cereal/mailcow-dockerized/data/conf/dovecot:/etc/dovecot:rw \
    -v $COMPOSE_DIR/filters:/opt/dovecot/filter:ro \
    -v $COMPOSE_DIR/logs/dovecot:/var/log/dovecot:rw \
    -v $COMPOSE_DIR/dovecot-official-fixed-entrypoint.sh:/dovecot-entrypoint.sh:ro \
    -e DBUSER=mailcow \
    -e DBPASS="$DBPASS" \
    -e DBNAME=mailcow \
    -e MYSQL_ROOT_PASSWORD="$DBROOT" \
    -e MAILCOW_HOSTNAME=localhost \
    -e REDISPASS="$REDISPASS" \
    -e TZ=America/New_York \
    mailcow/dovecot:2.31 \
    /usr/bin/supervisord -c /etc/supervisor/supervisord.conf
```

**Critical detail:** The CMD override `/usr/bin/supervisord -c /etc/supervisor/supervisord.conf` is required because `exec "$@"` with empty `$@` exits immediately.

---

## 7. Dovecot Configuration

### Main Config: `dovecot.conf`

Located at `/home/cereal/mailcow-dockerized/data/conf/dovecot/dovecot.conf`

**Key settings:**

```
protocols = imap sieve lmtp pop3
mail_home = /var/vmail/%d/%n
mail_location = maildir:~/
ssl_min_protocol = TLSv1.2
ssl_cert = </etc/dovecot/ssl.crt
ssl_key = </etc/dovecot/ssl.key
ssl_dh = </etc/dovecot/dhparams.pem
auth_mechanisms = plain login
```

**SSL Paths Fixed:**
- Cert: `/etc/dovecot/ssl.crt` (was `/etc/ssl/mail/cert.pem`)
- Key: `/etc/dovecot/ssl.key` (was `/etc/ssl/mail/key.pem`)
- DH: `/etc/dovecot/dhparams.pem` (was `/etc/ssl/mail/dhparams.pem`)

**Auth Chain (3 passdb lookups):**
1. Lua password verification (`passwd-verify.lua`) — result `return-ok` or `continue`
2. Master passwd file (`dovecot-master.passwd`) — skip if already authenticated
3. Lua password verification (fallback) — mandatory final check

**Userdb (2 lookups):**
1. Master userdb (`dovecot-master.userdb`)
2. SQL userdb (`/etc/dovecot/sql/dovecot-dict-sql-userdb.conf`) — skip if found

**Services Exposed:**
- `auth-inet` on port 10001 (for Postfix SASL)
- `lmtp-inet` on port 24 (for Postfix delivery)
- `doveadm` on port 12345 (admin interface)
- `imap-login` on ports 143, 10143 (haproxy)
- `imaps-login` on ports 993, 10993 (haproxy)
- `pop3-login` on ports 110, 10110 (haproxy)
- `managesieve` on port 4190

**Plugins:**
- Quota (with 95% and 80% warning thresholds)
- Sieve (before/after filters, vacation, spam/ham reporting)
- ACL (vfile-based)
- Mail crypto attachments
- LZ4 compression
- Mail logging

---

## 8. Postfix Configuration

### Main Config: `main.cf`

Located at `/home/cereal/mailcow-dockerized/data/conf/postfix/main.cf`

**Key settings:**

```
myhostname = localhost
mydestination = localhost.localdomain, localhost
inet_interfaces = all
inet_protocols = all
message_size_limit = 104857600    # 100MB
mail_name = Postcow
```

**TLS Configuration:**
```
smtpd_tls_security_level = may
smtpd_tls_mandatory_protocols = >=TLSv1.2
smtp_tls_security_level = dane
smtp_tls_mandatory_protocols = >=TLSv1.2
tls_ssl_options = NO_COMPRESSION, NO_RENEGOTIATION
```

**Spam Filtering (Rspamd Milter):**
```
smtpd_milters = inet:rspamd:9900
non_smtpd_milters = inet:rspamd:9900
milter_protocol = 6
milter_default_action = tempfail
```

**SASL Authentication (via Dovecot):**
```
smtpd_sasl_auth_enable = yes
smtpd_sasl_type = dovecot
smtpd_sasl_path = inet:dovecot:10001
smtpd_tls_auth_only = yes
```

**Virtual Mailbox Delivery (via Dovecot LMTP):**
```
virtual_transport = lmtp:inet:dovecot:24
virtual_mailbox_base = /var/vmail/
virtual_uid_maps = static:5000
virtual_gid_maps = static:5000
```

**All MySQL Lookups Use Proxy Maps:**
- `relay_domains` → `mysql:/opt/postfix/conf/sql/mysql_virtual_relay_domain_maps.cf`
- `virtual_alias_maps` → `mysql:/opt/postfix/conf/sql/mysql_virtual_alias_maps.cf`
- `virtual_mailbox_domains` → `mysql:/opt/postfix/conf/sql/mysql_virtual_domains_maps.cf`
- `virtual_mailbox_maps` → `mysql:/opt/postfix/conf/sql/mysql_virtual_mailbox_maps.cf`
- `smtpd_sender_login_maps` → `mysql:/opt/postfix/conf/sql/mysql_virtual_sender_acl.cf`
- `smtp_sasl_password_maps` → `mysql:/opt/postfix/conf/sql/mysql_sasl_passwd_maps_sender_dependent.cf`

**Postscreen (Anti-Spam):**
- DNSBL threshold: 6
- Sites: Spamhaus ZEN, DNSWL, SpamCop, Mailspike, Barracuda
- Greet enforcement enabled
- Blacklist action: drop

---

## 9. Database Seeding

### Script: `seed_db.py`

Creates 70+ tables in the `mailcow` database via Docker exec.

#### Core Tables (Full Schema)

| Table | Purpose |
|-------|---------|
| `versions` | Schema version tracking (set to `19022026_1220`) |
| `domain` | Managed email domains (active, DKIM, quota, relay) |
| `mailbox` | User mailboxes (password, quota, TLS enforcement, login tracking) |
| `alias` | Email aliases (address, goto, groups, dynamic) |
| `admin` | Admin accounts (superadmin flag, active) |
| `domain_admins` | Domain-level admin assignments |
| `quarantine` | Quarantined messages (hash, subject, action, reason) |
| `user_acl` | Per-user access control lists |
| `da_acl` | Domain admin access control lists |

#### Auxiliary Tables (Generic Schema)

50+ tables with generic `(id INT AUTO_INCREMENT, data TEXT, PRIMARY KEY (id))` schema:

`recipient_bcc`, `filterconf`, `sasl_log`, `sieve_filters`, `tls_policy`, `tls_policy_maps`, `rspamd_training`, `rspamd_symbol_override`, `sogo_profile`, `sogo_profile_change`, `forwardingfst`, `dashboard`, `dynamic_shell`, `dynamic_alias`, `sender_acl`, `sender_login_map`, `alias_domain`, `alias_domain_aliases`, `delivery_status`, `delivery_status_date`, `dkim`, `fido2`, `ip_pool`, `oauth_authorization_codes`, `oauth_access_tokens`, `oauth_refresh_tokens`, `oauth_clients`, `policyd_sender`, `pw_reset`, `rbl`, `relayhost`, `rsettings`, `rsettings_desc`, `spam_domain_whitelist`, `spam_user_blacklist`, `spam_user_whitelist`, `spamfilter_policy`, `spamfilter_users`, `spamwatch`, `statistic`, `statistic_segments`, `syncmailboxes`, `twofactor`, `tfa`, `tfa_backup`, `tfa_recovery`, `api`, `autoreminder`, `autotask`, `text_search`, `global_domain_mailbox_selection`, `daemon_health_stats`, `app_passkeys`, `app_tokens`, `ratelimiter`, `dmarc_report`, `dmarc_report_xml`, `policyd_spf`

#### Seed Data

```sql
INSERT INTO versions (application, version)
  VALUES ('db_schema', '19022026_1220')
  ON DUPLICATE KEY UPDATE version='19022026_1220';

INSERT INTO domain (domain, active)
  VALUES ('localhost', 1)
  ON DUPLICATE KEY UPDATE domain=domain;
```

#### Usage

```bash
cd /home/cereal/Mailcow/deploy
python3 seed_db.py
```

Output: `Creating 72 tables/statements... Done! OK: 72, Failed: 0`

---

## 10. Startup Procedure

### Correct Startup Order

Mailcow services have strict dependency ordering. MySQL and Redis MUST be healthy before any other service starts.

#### Method 1: Ordered Startup Script (Recommended)

```bash
cd /home/cereal/Mailcow/deploy
bash mailcow_start.sh
```

This script:
1. Stops any existing containers (`docker compose down`)
2. Starts MySQL + Redis with health checks (up to 60 iterations × 2s = 120s timeout)
3. Waits for MySQL `healthy` status
4. Waits for Redis `healthy` status
5. Starts auxiliary services (clamd, rspamd, php-fpm, sogo, postfix)
6. Starts Dovecot manually with `docker run` (custom entrypoint)
7. Shows final status table

#### Method 2: Simple Compose Start

```bash
cd /home/cereal/Mailcow/deploy
bash start.sh
```

Uses `docker compose up -d` with built-in `depends_on` conditions. **May fail** if Dovecot entrypoint doesn't connect properly.

### What Happens During Startup

```
=== Mailcow Email Server Startup ===
Starting database services...
  → mysql-mailcow (mariadb:10.6)
  → redis-mailcow (redis:7-alpine)

Waiting for MySQL...
  → Polls docker inspect --format='{{.State.Health.Status}}'
  → Health check: mysqladmin ping -h localhost
  → Healthy when InnoDB initialized

Waiting for Redis...
  → Polls docker inspect --format='{{.State.Health.Status}}'
  → Health check: redis-cli -a $REDISPASS ping
  → Healthy when PONG received

Starting auxiliary services...
  → clamd-mailcow, rspamd-mailcow, php-fpm-mailcow, sogo-mailcow, postfix-mailcow

Starting Dovecot...
  → docker run with custom entrypoint
  → Entrypoint waits for MySQL TCP + Redis TCP
  → Creates SQL dict configs
  → Launches supervisord

=== Service Status ===
  → All 8 containers running
=== Mailcow Startup Complete ===
```

---

## 11. Management Scripts

| Script | Purpose | Command |
|--------|---------|---------|
| `mailcow_start.sh` | Full ordered startup | `bash mailcow_start.sh` |
| `start.sh` | Simple compose start | `bash start.sh` |
| `stop.sh` | Stop all services | `bash stop.sh` |
| `restart.sh` | Restart all services | `bash restart.sh` |
| `status.py` | Python status checker | `python3 status.py` |
| `seed_db.py` | Initialize database | `python3 seed_db.py` |
| `test_smtp.py` | Test SMTP/IMAP | `python3 test_smtp.py` |
| `test_email.py` | Send test email | `python3 test_email.py` |
| `test-api.sh` | Full service test battery | `bash test-api.sh` |
| `write_entrypoint.py` | Generate Dovecot entrypoint | `python3 write_entrypoint.py` |
| `fix_compose.py` | Write docker-compose.yml | `python3 fix_compose.py` |

---

## 12. Service Interaction Guide

### MySQL (MariaDB 10.6)

```bash
# Connect to database (password from vault key: mailcow_mysql_root)
docker exec -it mysql-mailcow mysql -u root -p"$DBROOT" mailcow

# Check schema version
docker exec mysql-mailcow mysql -u root -p"$DBROOT" mailcow -e "SELECT * FROM versions;"

# List all tables
docker exec mysql-mailcow mysql -u root -p"$DBROOT" mailcow -e "SHOW TABLES;"

# Check domains
docker exec mysql-mailcow mysql -u root -p"$DBROOT" mailcow -e "SELECT * FROM domain;"

# Check mailboxes
docker exec mysql-mailcow mysql -u root -p"$DBROOT" mailcow -e "SELECT username, domain, active FROM mailbox;"

# Add a new domain
docker exec mysql-mailcow mysql -u root -p"$DBROOT" mailcow -e "INSERT INTO domain (domain, active) VALUES ('example.com', 1);"

# Add a new mailbox
docker exec mysql-mailcow mysql -u root -p"$DBROOT" mailcow -e "INSERT INTO mailbox (username, domain, password, quota) VALUES ('user@example.com', 'example.com', ENCRYPT('password123'), '1073741824');"
```

### Redis

```bash
# Test connectivity
docker exec redis-mailcow redis-cli -a "$REDISPASS" ping

# Check keys
docker exec redis-mailcow redis-cli -a "$REDISPASS" keys '*'

# Flush all (DANGEROUS - clears all cached data)
docker exec redis-mailcow redis-cli -a "$REDISPASS" flushall
```

### Dovecot (IMAP)

```bash
# Test IMAP connection
docker exec dovecot-mailcow doveadm user user@example.com

# Check mailboxes
docker exec dovecot-mailcow doveadm mailbox status user@example.com "*"

# Check quota
docker exec dovecot-mailcow doveadm quota get -u user@example.com

# View auth logs
docker logs dovecot-mailcow | grep -i auth

# Restart Dovecot
docker restart dovecot-mailcow
```

### Postfix (SMTP)

```bash
# Check mail queue
docker exec postfix-mailcow postqueue -p

# Flush queue
docker exec postfix-mailcow postfix flush

# View config
docker exec postfix-mailcow postconf -n

# Check active connections
docker exec postfix-mailcow postcat -q QUEUE_ID

# View logs
docker logs postfix-mailcow | tail -50
```

### Rspamd (Spam Filtering)

```bash
# Check Rspamd status
docker exec rspamd-mailcow rspamc -h localhost:11334 stat

# View symbols
docker exec rspamd-mailcow rspamc -h localhost:11334 symbols

# Scan a message
curl -X POST -H "Content-Type: message/rfc822" \
  --data-binary @/path/to/message.eml \
  http://localhost:11334/scan

# View logs
docker logs rspamd-mailcow | tail -50
```

### SOGo (Webmail)

```bash
# Check SOGo is responding
curl -s -o /dev/null -w "%{http_code}" http://localhost:8080

# View logs
docker logs sogo-mailcow | tail -50
```

---

## 13. Testing

### Quick Connectivity Test

```bash
cd /home/cereal/Mailcow/deploy
python3 test_smtp.py
```

Expected output:
```
Testing SMTP on 192.168.50.222:25...
  EHLO: 250 ...
  SMTP connection: OK
Testing IMAP on 192.168.50.222:143...
  IMAP greeting: b'* OK ...'
  IMAP connection: OK
Mailcow SMTP is operational!
```

### Full Service Test Battery

```bash
cd /home/cereal/Mailcow/deploy
bash test-api.sh
```

Runs 6 tests: Container status, MySQL, Redis, Rspamd, SOGo, Postfix queue.

### Manual SMTP Test

```bash
telnet 192.168.50.222 25
EHLO test.local
MAIL FROM: <sender@localhost>
RCPT TO: <recipient@localhost>
DATA
Subject: Test
Test message
.
QUIT
```

---

## 14. Troubleshooting - Complete Error Catalog

### Error 0: HTTP API Sidecar Returns Redis `WRONGPASS` or `dockerapi` Failure

**Symptom:** `http://HOST:8081/api/v1/...` returns HTTP 500 with either
`Connection to Redis failed` / `WRONGPASS` or `Connection to dockerapi container failed`.

**Root Cause:** The custom Mailcow stack does not run the full upstream web/API
compose set. The API sidecar must receive the same `REDISPASS` as Redis, and
upstream `json_api.php` expects a `dockerapi` hostname on port 443.

**Fix:**

1. Recreate `php-fpm-mailcow-api` with `--env-file /home/cereal/Mailcow/deploy/.env`.
2. Do not pass empty `-e REDISPASS=` or `-e DBPASS=` values; they override the env file.
3. Mount `session_store.ini` containing the runtime Redis password from `.env`.
4. Start `dockerapi-mailcow` from `ghcr.io/mailcow/dockerapi:2.12` with `/var/run/docker.sock:ro`.
5. Recreate `php-fpm-mailcow-api` with `--add-host dockerapi:127.0.0.1` when using host networking.
6. Test an invalid API key returns `401`, and a valid API key reaches `json_api.php` with HTTP `200`.

**Security Notes:**

- Do not print API keys or passwords in logs.
- Store the API key in the vault or retrieve it from the Mailcow database at runtime.
- The Docker socket mount is read-only but still sensitive; use this only in the reference lab or with explicit approval.

**Verified in lab:** 2026-05-11. Redis and dockerapi blockers were cleared on
the AI server API sidecars.

### Error 0b: HTTP API Sidecar Returns Empty Bodies For Real Mailcow Data

**Symptom:** `GET /api/v1/get/domain/all` or `GET /api/v1/get/alias/all`
returns HTTP `200` with an empty body, or `GET /api/v1/get/mailbox/all`
returns `{}`, while direct MySQL shows real domains, mailboxes, and aliases.

**Root Cause:** The custom reference deployment does not expose the complete
upstream Mailcow web/API stack. The stock `json_api.php` path can initialize but
fail to return useful inventory data in the sidecar context.

**Fix:** Use the compatibility shim documented in
`docs/MAILCOW_API_SHIM.md` and the Keycloak-Mailcow bridge skill:

```bash
cd /home/cereal/Mailcow/deploy
python3 scripts/deploy_mailcow_api.py
python3 scripts/test_mailcow_api_shim.py --mysql-parity
```

The shim installs `/web/mailcow_compat_api.php` and routes read-only
`GET /api/v1/get/domain/*`, `GET /api/v1/get/mailbox/*`, and
`GET /api/v1/get/alias/*` through it. The endpoint still validates
`X-API-Key` against the Mailcow `api` table, rejects missing/invalid keys with
HTTP `401`, rejects POST with HTTP `405`, and omits password hashes from
mailbox output.

**Verified in lab:** 2026-05-12.

```text
test_mailcow_api_shim.py --mysql-parity: 13 passed, 0 failed
platform_doctor.py: 18 passed, 0 failed, 0 warned
Keycloak-Mailcow bridge E2E: 47 passed, 0 failed, 1 skipped
```

### Error 0c: Demo Root or Admin Login Redirects To Blank `/user`

**Symptom:** `http://HOST:2581/`, `/admin`, or `/admin/` shows a login form,
but after logging in the browser displays a blank page. Nginx access logs show
`GET /user` returning HTTP `200` with a 5-byte body.

**Root Cause:** In this custom sidecar deployment, the root user-login path is
incomplete. A stale Mailcow user-session cookie (`MCSESSID`) can cause the
admin entrypoint to redirect back into `/user`, even when the admin UI itself
is healthy.

**Fix:** Re-run the shim deployer:

```bash
cd /home/cereal/Mailcow/deploy
python3 scripts/deploy_mailcow_api.py
```

The deployer routes exact `/` and `/admin/` through FastCGI to
`/web/admin/index.php`, strips incoming cookies on those admin login
entrypoints, and clears both `PHPSESSID` and `MCSESSID` on `/user` before
redirecting back to `/`.

**Verified in lab:** 2026-05-18. Headless browser login from the bare root URL,
including a pre-seeded stale `MCSESSID`, reached `/admin/dashboard` with visible
dashboard content, loaded versioned `/cache` assets, and reported no failed
requests or console errors. The deployer now includes a stale-session recovery
check.

### Error 0d: Admin UI Shows Invalid JSON Or SQL Warning Banners After Login

**Symptom:** Login succeeds and pages render, but the browser shows DataTables
invalid JSON dialogs, SQL invalid-column warnings, missing-table warnings, or
visible `undefined`/`NaN` values on admin/system/mailbox/queue/quarantine pages.

**Root Cause:** The mounted Mailcow web code expects newer UI schema and native
Mailcow table JSON shapes. In the custom reference stack, the database seed can
miss `fido2`, `settingsmap`, `templates`, `relayhosts`, `bcc_maps`,
`tls_policy_override`, current `tfa`, `logs`, or `mailbox.authsource`, and
stock `json_api.php` can return empty bodies for browser table routes.

**Fix:** Re-run the shim deployer:

```bash
cd /home/cereal/Mailcow/deploy
python3 scripts/deploy_mailcow_api.py
```

The deployer repairs the UI schema, routes domain-search/quarantine/template
reads through `/web/mailcow_compat_api.php`, sets small lab quarantine Redis
defaults, creates direct delivery aliases for active user mailboxes, deploys
`roundcube-mailcow-demo` on loopback port `2582`, proxies `/webmail` to
Roundcube, and redirects `/SOGo/*` to Roundcube. Keep upstream SOGo in
`SKIP_SOGO=y` mode in the reference lab until it is separately hardened.

**Verified in lab:** 2026-05-18. The deployer table JSON checks passed, and a
headless browser crawl of `/admin/dashboard`, `/admin/system`, `/admin/mailbox`,
`/admin/queue`, `/quarantine`, `/webmail`, and `/SOGo/so` reported no invalid
JSON dialogs or SQL warnings. Roundcube login, real Mailcow inbox rendering,
Report Phish, dashboard/iTop sync, and visible Mailcow quarantine row were
verified with ticket `580`, iTop Incident `372`, agent `229`, access request
`581`, and quarantine id `21a705b151642568d375c748a9ea1a6b`. Static queue help
copy may mention "error message"; treat that as normal copy, not a browser
failure.

### Error 1: Dovecot Infinite "Waiting for Database" Loop

**Symptom:** Dovecot container restarts endlessly, logs show repeated "Waiting for database" messages.

**Root Cause:** MySQL Unix socket at `/var/run/mysqld/mysqld.sock` is not accessible from the Dovecot container. Docker overlay2 storage driver doesn't share sockets reliably across containers on the same network.

**Fix:** Use TCP connectivity instead of Unix socket. Change all MySQL connections in the entrypoint from `--socket=/var/run/mysqld/mysqld.sock` to `-h mysql` (Docker DNS resolves `mysql` to the MariaDB container).

**Files Changed:** `dovecot-entrypoint.sh`, `dovecot-official-fixed-entrypoint.sh`

### Error 2: MySQL Access Denied for User `mailcow` from `172.23.0.x`

**Symptom:** `Access denied for user 'mailcow'@'172.23.0.9'` in logs.

**Root Cause:** The `mailcow` MySQL user was created with host `localhost` only. When connecting via TCP from another container, the source IP is the Docker network IP (172.23.0.x), not localhost.

**Fix:**
```sql
GRANT ALL PRIVILEGES ON mailcow.* TO 'mailcow'@'%' IDENTIFIED BY '$DBPASS';
FLUSH PRIVILEGES;
```

### Error 3: `REDISSASS` Typo in Custom Entrypoint

**Symptom:** Redis connection fails with authentication error.

**Root Cause:** Typo in the custom entrypoint — used `${REDISSASS}` instead of `${REDISPASS}`.

**Fix:** Corrected variable name in `dovecot-entrypoint.sh`.

### Error 4: Missing Space Before `]]` in Conditional

**Symptom:** Bash syntax error on Redis wait loop: `bash: [[: command not found`.

**Root Cause:** `[[ $(${REDIS_CMDLINE} PING 2>/dev/null) != "PONG" ]]` — missing space before `]]`.

**Fix:** Added space: `]]` → ` ]]`.

### Error 5: `chmod /templates/quarantine.tpl` Failure

**Symptom:** Entrypoint exits with code 1 at line 124.

**Root Cause:** The `/templates/quarantine.tpl` file doesn't exist in the `mailcow/dovecot:2.31` image. With `set -e`, the `chmod` failure kills the entire script.

**Fix:** Two changes:
1. Changed `set -e` to `set +e` (tolerant mode)
2. Added `|| true` to the chmod command

### Error 6: `stat /var/vmail_index` Failure

**Symptom:** Similar to Error 5, `stat` command fails on non-existent directory.

**Fix:** `set +e` tolerance handles this.

### Error 7: SSL Path Errors

**Symptom:** Dovecot fails to start with SSL certificate errors: `error: cannot open /etc/ssl/mail/dhparams.pem`.

**Root Cause:** The official image expects SSL files at `/etc/ssl/mail/` but our config mounts them to `/etc/dovecot/`.

**Fix:** Updated `dovecot.conf`:
- `ssl_cert = </etc/dovecot/ssl.crt`
- `ssl_key = </etc/dovecot/ssl.key`
- `ssl_dh = </etc/dovecot/dhparams.pem`

### Error 8: DNS Wait Loop Hangs Forever

**Symptom:** Entrypoint hangs at "Waiting for DNS" — `dig mailcow.email` never resolves.

**Root Cause:** Our `MAILCOW_HOSTNAME=localhost` doesn't have external DNS records. The official entrypoint waits for DNS resolution that will never come.

**Fix:** Commented out the DNS wait loop in `dovecot-official-fixed-entrypoint.sh`.

### Error 9: SOGo Trusted IP `.248` Hostname Error

**Symptom:** Entrypoint generates invalid SOGo config with hostname `.248`.

**Root Cause:** The `IPV4_NETWORK` environment variable is empty, so the script computes the last octet of an empty IP, producing `.248`.

**Fix:** Commented out SOGo trusted IP generation block (lines 314-320). Set `sogo_trusted_ip.conf` to a comment-only file.

### Error 10: `exec "$@"` Exits with Empty Arguments

**Symptom:** Container starts and immediately exits when using `--entrypoint`.

**Root Cause:** When you specify `--entrypoint` without providing a CMD, `$@` is empty, so `exec "$@"` becomes `exec` with no arguments, which exits.

**Fix:** Explicitly pass the command: `mailcow/dovecot:2.31 /usr/bin/supervisord -c /etc/supervisor/supervisord.conf`

### Error 11: yaml.dump() Corrupts `${VAR}` References

**Symptom:** Docker Compose fails because `${DBROOT}` gets expanded to empty string.

**Root Cause:** Python's `yaml.dump()` interprets `${VAR}` as Python string formatting, corrupting the output.

**Fix:** Write `docker-compose.yml` via `fix_compose.py` using raw string literals (`r"""..."""`).

### General Troubleshooting Commands

```bash
# Check all container statuses
docker ps -a --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"

# Check a specific container's logs
docker logs dovecot-mailcow --tail 100

# Check Docker network
docker network inspect deploy_mailcow-network

# Verify MySQL health
docker inspect --format='{{.State.Health.Status}}' mysql-mailcow

# Verify Redis health
docker inspect --format='{{.State.Health.Status}}' redis-mailcow

# Check for port conflicts
ss -tlnp | grep -E ':(25|143|465|587|993)'
```

---

## 15. Integration with SOC Tools

### Wazuh SIEM

Wazuh is running on the same server (3 containers: manager, dashboard, indexer). Mailcow logs can be forwarded to Wazuh for security monitoring.

```bash
# Check Wazuh status
docker ps --filter "name=wazuh"
```

### Report Phish Backend

The `report_phish` package provides an `InternalEmailBackend` that:
1. Connects to Mailcow SMTP at `192.168.50.222:25`
2. Sends formatted phishing reports to an internal security distribution group
3. Optionally creates cases in external case management systems

```python
from report_phish.backends.internal_email import InternalEmailBackend

backend = InternalEmailBackend({
    "host": "192.168.50.222",
    "port": 25,
    "use_tls": False,
    "from_email": "phish-report@localhost",
    "phishing_dist_group": "security-team@localhost",
})
result = backend.report({"subject": "...", "headers": {...}, "body": "..."})
```

---

## 16. Backup and Restore

### Backup All Data

```bash
# Stop services
bash /home/cereal/Mailcow/deploy/stop.sh

# Backup everything
tar czf /backup/mailcow-backup-$(date +%Y%m%d).tar.gz \
  -C /home/cereal/Mailcow/deploy data/ \
  -C /home/cereal/mailcow-dockerized/data/conf dovecot/ postfix/

# Start services
bash /home/cereal/Mailcow/deploy/mailcow_start.sh
```

### Backup MySQL Only

```bash
docker exec mysql-mailcow mysqldump -u root -p"$DBROOT" mailcow > /backup/mailcow-db-$(date +%Y%m%d).sql
```

### Restore

```bash
bash /home/cereal/Mailcow/deploy/stop.sh
docker exec -i mysql-mailcow mysql -u root -p"$DBROOT" mailcow < /backup/mailcow-db-20260427.sql
bash /home/cereal/Mailcow/deploy/mailcow_start.sh
```

---

## 17. Ports Reference

### Host-Exposed Ports

| Port | Service | Protocol | Purpose |
|------|---------|----------|---------|
| 25 | postfix-mailcow | TCP | SMTP (incoming mail) |
| 143 | dovecot-mailcow | TCP | IMAP (unencrypted) |
| 465 | postfix-mailcow | TCP | SMTPS (encrypted SMTP) |
| 587 | postfix-mailcow | TCP | Submission (authenticated SMTP) |
| 993 | dovecot-mailcow | TCP | IMAPS (encrypted IMAP) |
| 11332 | rspamd-mailcow | TCP | Rspamd milter |
| 11334 | rspamd-mailcow | TCP | Rspamd web UI |

### Internal-Only Ports (Docker Network)

| Port | Service | Purpose |
|------|---------|---------|
| 3306 | mysql-mailcow | MySQL |
| 6379 | redis-mailcow | Redis |
| 9000 | php-fpm-mailcow | PHP-FPM |
| 8080 | sogo-mailcow | SOGo HTTP |
| 2581 | nginx-mailcow-api | Demo Mailcow UI, API shim, Roundcube proxy |
| 2582 | roundcube-mailcow-demo | Loopback-only Roundcube webmail |
| 24 | dovecot-mailcow | LMTP |
| 10001 | dovecot-mailcow | SASL Auth |
| 9900 | rspamd-mailcow | Milter |

---

## 18. Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2026-04-24 | Initial Mailcow Docker Compose deployment |
| 2.0 | 2026-04-27 | Complete blueprint rewrite — full deployment guide, error catalog, service interaction, all configs documented |

---

## Quick Reference Card

```
┌─────────────────────────────────────────────────────────┐
│ Mailcow Quick Commands                                  │
├─────────────────────────────────────────────────────────┤
│ Start:    bash /home/cereal/Mailcow/deploy/mailcow_start.sh │
│ Stop:     bash /home/cereal/Mailcow/deploy/stop.sh          │
│ Restart:  bash /home/cereal/Mailcow/deploy/restart.sh       │
│ Status:   python3 /home/cereal/Mailcow/deploy/status.py     │
│ Test:     python3 /home/cereal/Mailcow/deploy/test_smtp.py  │
│ Seed DB:  python3 /home/cereal/Mailcow/deploy/seed_db.py    │
│ Logs:     docker logs <container-name> --tail 50            │
│ MySQL:    docker exec mysql-mailcow mysql -uroot -p...      │
│ Redis:    docker exec redis-mailcow redis-cli -a ... ping   │
└─────────────────────────────────────────────────────────┘
```
