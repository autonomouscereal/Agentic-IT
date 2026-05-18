#!/usr/bin/env python3
"""Deploy the Mailcow HTTP API stack in parallel with existing MySQL-based setup.

Creates:
1. php-fpm-mailcow-api container (mailcow/phpfpm:1.92, web code mounted, port 9002)
2. nginx-mailcow-api container (nginx:alpine, FastCGI proxy on port 8081 and demo UI on 2581)
3. API/UI compatibility schema fixes + API key seed

Keeps existing php-fpm-mailcow + MySQL bridge scripts fully functional.
"""

import json
import os
import secrets
import shlex
import subprocess
import sys
import time
import re
import urllib.error
import urllib.request


def read_env_file(path):
    values = {}
    if not os.path.exists(path):
        return values
    with open(path, encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip('"').strip("'")
    return values


# ─── Configuration ──────────────────────────────────────────────────────

MAILCOW_DOCKERIZED_WEB = "/home/cereal/mailcow-dockerized/data/web"
NGINX_CONF_DIR = "/home/cereal/Mailcow/deploy/api-nginx"
MAILCOW_ENV_FILE = os.environ.get("MAILCOW_ENV_FILE", "/home/cereal/Mailcow/deploy/.env")
API_PORT = 8081
UI_DEMO_PORT = int(os.environ.get("MAILCOW_UI_DEMO_PORT", "2581"))
PHPFPM_PORT = 9002
MAILCOW_ENV = read_env_file(MAILCOW_ENV_FILE)
MYSQL_DATABASE = os.environ.get("MYSQL_DATABASE") or os.environ.get("DBNAME") or MAILCOW_ENV.get("DBNAME") or "mailcow"
MAILCOW_API_KEY = None  # Will be generated if not found
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


# ─── Helpers ────────────────────────────────────────────────────────────

def run(cmd, check=True):
    """Run a shell command and return output."""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"  [ERROR] Command failed: {cmd}")
        print(f"  stdout: {result.stdout}")
        print(f"  stderr: {result.stderr}")
        sys.exit(1)
    return result.stdout.strip(), result.stderr.strip()


def docker_run(args, check=True):
    """Run docker without shell interpolation so secrets never appear in errors."""
    result = subprocess.run(args, capture_output=True, text=True)
    if check and result.returncode != 0:
        printable = " ".join(shlex.quote(a) for a in args if "PASSWORD" not in a and "PASS=" not in a)
        print(f"  [ERROR] Command failed: {printable}")
        print(f"  stdout: {result.stdout}")
        print(f"  stderr: {result.stderr}")
        sys.exit(1)
    return result.stdout.strip(), result.stderr.strip()


def run_sql(query):
    """Run SQL inside the Mailcow MySQL container using container-held creds."""
    args = [
        "sudo",
        "docker",
        "exec",
        "-e",
        f"SQL_QUERY={query}",
        "-e",
        f"SQL_DATABASE={MYSQL_DATABASE}",
        "mysql-mailcow",
        "sh",
        "-lc",
        'mysql -uroot -p"$MYSQL_ROOT_PASSWORD" -B -e "$SQL_QUERY" "$SQL_DATABASE" 2>/dev/null',
    ]
    return docker_run(args, check=False)[0]


def sql_literal(value):
    """Return a single-quoted SQL literal for generated non-secret values."""
    return "'" + str(value).replace("\\", "\\\\").replace("'", "''") + "'"


def table_columns(table):
    result = run_sql(f"DESCRIBE `{table}`")
    columns = set()
    for line in result.splitlines()[1:]:
        if line.strip():
            columns.add(line.split("\t", 1)[0])
    return columns


def write_api_key_file(api_key):
    api_key_file = os.path.join(NGINX_CONF_DIR, ".api_key")
    with open("/tmp/mailcow_api_key", "w", encoding="utf-8") as f:
        f.write(api_key + "\n")
    run(f"mkdir -p {shlex.quote(NGINX_CONF_DIR)}")
    run(f"cp /tmp/mailcow_api_key {shlex.quote(api_key_file)}")
    run(f"chmod 600 {shlex.quote(api_key_file)}")
    print("  API key file: OK")


def wait_for_port(host, port, timeout=30):
    """Wait for a TCP port to become available."""
    import socket
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection((host, port), timeout=2):
                return True
        except (OSError, ConnectionRefusedError):
            time.sleep(1)
    return False


# ─── Step 1: Fix API table schema ──────────────────────────────────────

def setup_api_table():
    """Create proper API table schema if it doesn't exist."""
    print("\n--- Step 1: Fixing API table schema ---")

    columns = table_columns("api")
    if not columns:
        print("  Creating api table with proper schema...")
        run_sql("""
            CREATE TABLE IF NOT EXISTS api (
                id INT(10) UNSIGNED NOT NULL AUTO_INCREMENT,
                api_key VARCHAR(255) NOT NULL,
                allow_from VARCHAR(512) DEFAULT NULL,
                skip_ip_check TINYINT(1) DEFAULT 1,
                access ENUM('ro','rw') DEFAULT 'rw',
                active TINYINT(1) DEFAULT 1,
                created DATETIME DEFAULT CURRENT_TIMESTAMP,
                modified DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                PRIMARY KEY (id),
                UNIQUE KEY api_key (api_key)
            )
        """)
        print("  Created api table.")
    else:
        column_defs = {
            "api_key": "VARCHAR(255) NOT NULL DEFAULT ''",
            "allow_from": "VARCHAR(512) DEFAULT NULL",
            "skip_ip_check": "TINYINT(1) DEFAULT 1",
            "access": "ENUM('ro','rw') DEFAULT 'rw'",
            "active": "TINYINT(1) DEFAULT 1",
            "created": "DATETIME DEFAULT CURRENT_TIMESTAMP",
            "modified": "DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP",
        }
        missing = [name for name in column_defs if name not in columns]
        for name in missing:
            run_sql(f"ALTER TABLE api ADD COLUMN `{name}` {column_defs[name]}")
        if missing:
            print(f"  Added API columns: {', '.join(missing)}")
        else:
            print("  API table columns already correct.")

    run_sql("DELETE FROM api WHERE LENGTH(api_key) <= 10")
    index_result = run_sql("SHOW INDEX FROM api WHERE Key_name = 'api_key'")
    if not index_result.strip():
        run_sql("ALTER TABLE api ADD UNIQUE INDEX api_key (api_key)")
        print("  API key unique index: OK")

    # Seed API key if none exists (or existing key is empty)
    existing = run_sql("SELECT api_key FROM api WHERE LENGTH(api_key) > 10 LIMIT 1")
    if not existing or not existing.strip():
        api_key = secrets.token_hex(32)
        run_sql(f"INSERT INTO api (api_key, access, active) VALUES ({sql_literal(api_key)}, 'rw', 1)")
        print("  Seeded new API key.")
        return api_key
    else:
        key = existing.strip().split("\n")[-1].strip()
        print("  Existing API key found.")
        return key


def setup_identity_provider_table():
    """Create compatibility table required by mounted Mailcow web code."""
    print("\n--- Step 1b: Ensuring identity_provider table ---")
    run_sql("""
        CREATE TABLE IF NOT EXISTS identity_provider (
            `key` VARCHAR(255) NOT NULL,
            `value` TEXT NOT NULL,
            `created` DATETIME(0) NOT NULL DEFAULT NOW(0),
            `modified` DATETIME ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (`key`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 ROW_FORMAT=DYNAMIC
    """)
    print("  identity_provider table: OK")


def setup_identity_provider_defaults():
    """Seed Mailcow's own IAM UI model when a Keycloak client secret is provided."""
    client_secret = os.environ.get("MAILCOW_IAM_CLIENT_SECRET") or MAILCOW_ENV.get("MAILCOW_IAM_CLIENT_SECRET", "")
    if not client_secret:
        existing = run_sql("SELECT `value` FROM `identity_provider` WHERE `key`='client_secret' LIMIT 1")
        if existing.strip():
            print("  identity_provider Keycloak settings: existing config preserved")
        else:
            print("  [WARN] MAILCOW_IAM_CLIENT_SECRET unavailable; Mailcow IAM UI config not seeded")
        return
    settings = {
        "authsource": "keycloak",
        "server_url": os.environ.get("MAILCOW_IAM_SERVER_URL") or MAILCOW_ENV.get("MAILCOW_IAM_SERVER_URL", "https://keycloak.internal:8443"),
        "realm": os.environ.get("MAILCOW_IAM_REALM") or MAILCOW_ENV.get("MAILCOW_IAM_REALM", "mailcow"),
        "client_id": os.environ.get("MAILCOW_IAM_CLIENT_ID") or MAILCOW_ENV.get("MAILCOW_IAM_CLIENT_ID", "mailcow-oidc"),
        "client_secret": client_secret,
        "redirect_url": os.environ.get("MAILCOW_IAM_REDIRECT_URL") or MAILCOW_ENV.get("MAILCOW_IAM_REDIRECT_URL", "http://192.168.50.222:2581"),
        "version": os.environ.get("MAILCOW_IAM_VERSION") or MAILCOW_ENV.get("MAILCOW_IAM_VERSION", "26"),
        "mailpassword_flow": "1",
        "periodic_sync": "1",
        "import_users": "1",
        "sync_interval": os.environ.get("MAILCOW_IAM_SYNC_INTERVAL") or MAILCOW_ENV.get("MAILCOW_IAM_SYNC_INTERVAL", "15"),
        "ignore_ssl_error": "1",
        "login_provisioning": "1",
        "redirect_url_extra": json.dumps(["http://localhost:2581"]),
        "default_template": "Default",
        "mappers": json.dumps(["default"]),
        "templates": json.dumps(["Default"]),
        "access_token": "",
    }
    for key, value in settings.items():
        run_sql(
            "INSERT INTO `identity_provider` (`key`, `value`) "
            f"VALUES ({sql_literal(key)}, {sql_literal(value)}) "
            "ON DUPLICATE KEY UPDATE `value` = VALUES(`value`)"
        )
    print("  identity_provider Keycloak settings: OK")


def setup_mailbox_delivery_aliases():
    """Ensure direct mailbox addresses win before the demo catch-all alias."""
    run_sql("""
        INSERT INTO `alias` (
            `address`, `goto`, `domain`, `active`, `sogo_visible`,
            `is_group`, `is_dynamic`, `max_recipients`
        )
        SELECT
            CONCAT(`username`, '@', `domain`),
            CONCAT(`username`, '@', `domain`),
            `domain`,
            1,
            1,
            0,
            0,
            '0'
        FROM `mailbox`
        WHERE `active` = 1
          AND `kind` = 'user'
          AND NOT EXISTS (
              SELECT 1
              FROM `alias` a
              WHERE a.`address` = CONCAT(`mailbox`.`username`, '@', `mailbox`.`domain`)
          )
    """)
    print("  direct mailbox delivery aliases: OK")


def setup_ui_compat_schema():
    """Repair schema drift that blocks the optional Mailcow demo UI."""
    print("\n--- Step 1c: Ensuring Mailcow UI compatibility schema ---")
    run_sql("""
        CREATE TABLE IF NOT EXISTS `logs` (
            `id` INT NOT NULL AUTO_INCREMENT,
            `task` CHAR(32) NOT NULL DEFAULT '000000',
            `type` VARCHAR(32) DEFAULT '',
            `msg` TEXT,
            `call` TEXT,
            `user` VARCHAR(64) NOT NULL,
            `role` VARCHAR(32) NOT NULL,
            `remote` VARCHAR(39) NOT NULL,
            `time` INT(11) NOT NULL,
            PRIMARY KEY (`id`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 ROW_FORMAT=DYNAMIC
    """)
    run_sql("""
        ALTER TABLE `tfa`
          ADD COLUMN IF NOT EXISTS `key_id` VARCHAR(255) NOT NULL DEFAULT 'unidentified' AFTER `id`,
          ADD COLUMN IF NOT EXISTS `username` VARCHAR(255) NOT NULL DEFAULT '' AFTER `key_id`,
          ADD COLUMN IF NOT EXISTS `authmech` ENUM('yubi_otp', 'u2f', 'hotp', 'totp', 'webauthn') NULL AFTER `username`,
          ADD COLUMN IF NOT EXISTS `secret` VARCHAR(255) DEFAULT NULL AFTER `authmech`,
          ADD COLUMN IF NOT EXISTS `keyHandle` VARCHAR(1023) DEFAULT NULL AFTER `secret`,
          ADD COLUMN IF NOT EXISTS `publicKey` VARCHAR(4096) DEFAULT NULL AFTER `keyHandle`,
          ADD COLUMN IF NOT EXISTS `counter` INT NOT NULL DEFAULT '0' AFTER `publicKey`,
          ADD COLUMN IF NOT EXISTS `certificate` TEXT AFTER `counter`,
          ADD COLUMN IF NOT EXISTS `active` TINYINT(1) NOT NULL DEFAULT '0' AFTER `certificate`
    """)
    run_sql("""
        ALTER TABLE `mailbox`
          ADD COLUMN IF NOT EXISTS `authsource` ENUM('mailcow', 'keycloak', 'generic-oidc', 'ldap') DEFAULT 'mailcow' AFTER `attributes`
    """)
    run_sql("UPDATE `mailbox` SET `authsource`='mailcow' WHERE `authsource` IS NULL OR `authsource`=''")
    run_sql("""
        CREATE TABLE IF NOT EXISTS `fido2` (
            `id` INT(10) UNSIGNED NOT NULL AUTO_INCREMENT,
            `data` TEXT DEFAULT NULL,
            PRIMARY KEY (`id`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 ROW_FORMAT=DYNAMIC
    """)
    run_sql("""
        ALTER TABLE `fido2`
          ADD COLUMN IF NOT EXISTS `credentialId` VARBINARY(512) DEFAULT NULL AFTER `id`,
          ADD COLUMN IF NOT EXISTS `credentialPublicKey` BLOB DEFAULT NULL AFTER `credentialId`,
          ADD COLUMN IF NOT EXISTS `certificateSubject` VARCHAR(255) DEFAULT NULL AFTER `credentialPublicKey`,
          ADD COLUMN IF NOT EXISTS `username` VARCHAR(255) NOT NULL DEFAULT '' AFTER `certificateSubject`,
          ADD COLUMN IF NOT EXISTS `friendlyName` VARCHAR(255) DEFAULT NULL AFTER `username`,
          ADD COLUMN IF NOT EXISTS `created` DATETIME DEFAULT CURRENT_TIMESTAMP AFTER `friendlyName`,
          ADD COLUMN IF NOT EXISTS `modified` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP AFTER `created`
    """)
    run_sql("""
        CREATE TABLE IF NOT EXISTS `settingsmap` (
            `id` INT(10) UNSIGNED NOT NULL AUTO_INCREMENT,
            `desc` VARCHAR(255) NOT NULL DEFAULT '',
            `content` TEXT DEFAULT NULL,
            `active` TINYINT(1) NOT NULL DEFAULT 1,
            `created` DATETIME DEFAULT CURRENT_TIMESTAMP,
            `modified` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (`id`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 ROW_FORMAT=DYNAMIC
    """)
    run_sql("""
        CREATE TABLE IF NOT EXISTS `templates` (
            `id` INT(10) UNSIGNED NOT NULL AUTO_INCREMENT,
            `type` VARCHAR(32) NOT NULL,
            `template` VARCHAR(255) NOT NULL,
            `attributes` LONGTEXT NOT NULL,
            `created` DATETIME DEFAULT CURRENT_TIMESTAMP,
            `modified` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (`id`),
            UNIQUE KEY `type_template` (`type`, `template`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 ROW_FORMAT=DYNAMIC
    """)
    run_sql("""
        CREATE TABLE IF NOT EXISTS `relayhosts` (
            `id` INT(10) UNSIGNED NOT NULL AUTO_INCREMENT,
            `hostname` VARCHAR(255) NOT NULL DEFAULT '',
            `username` VARCHAR(255) NOT NULL DEFAULT '',
            `password` VARCHAR(255) NOT NULL DEFAULT '',
            `active` TINYINT(1) NOT NULL DEFAULT 1,
            `created` DATETIME DEFAULT CURRENT_TIMESTAMP,
            `modified` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (`id`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 ROW_FORMAT=DYNAMIC
    """)
    run_sql("""
        CREATE TABLE IF NOT EXISTS `bcc_maps` (
            `id` INT(10) UNSIGNED NOT NULL AUTO_INCREMENT,
            `local_dest` VARCHAR(255) NOT NULL DEFAULT '',
            `bcc_dest` VARCHAR(255) NOT NULL DEFAULT '',
            `domain` VARCHAR(255) NOT NULL DEFAULT '',
            `active` TINYINT(1) NOT NULL DEFAULT 1,
            `type` ENUM('sender','rcpt') NOT NULL DEFAULT 'rcpt',
            `created` DATETIME DEFAULT CURRENT_TIMESTAMP,
            `modified` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (`id`),
            KEY `domain` (`domain`),
            KEY `local_dest_type` (`local_dest`, `type`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 ROW_FORMAT=DYNAMIC
    """)
    run_sql("""
        CREATE TABLE IF NOT EXISTS `tls_policy_override` (
            `id` INT(10) UNSIGNED NOT NULL AUTO_INCREMENT,
            `dest` VARCHAR(255) NOT NULL DEFAULT '',
            `policy` VARCHAR(32) NOT NULL DEFAULT 'none',
            `parameters` TEXT DEFAULT NULL,
            `active` TINYINT(1) NOT NULL DEFAULT 1,
            `created` DATETIME DEFAULT CURRENT_TIMESTAMP,
            `modified` DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            PRIMARY KEY (`id`),
            UNIQUE KEY `dest` (`dest`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 ROW_FORMAT=DYNAMIC
    """)
    default_domain_template = {
        "tags": [],
        "max_num_aliases_for_domain": 400,
        "max_num_mboxes_for_domain": 100,
        "def_quota_for_mbox": 5368709120,
        "max_quota_for_mbox": 10737418240,
        "max_quota_for_domain": 107374182400,
        "rl_frame": "s",
        "rl_value": "",
        "active": 1,
        "gal": 1,
        "backupmx": 0,
        "relay_all_recipients": 0,
        "relay_unknown_only": 0,
        "dkim_selector": "dkim",
        "key_size": 2048,
    }
    default_mailbox_template = {
        "quota": 5368709120,
        "tags": [],
        "tagged_mail_handler": "subfolder",
        "quarantine_notification": "never",
        "quarantine_category": "reject",
        "rl_frame": "s",
        "rl_value": "",
        "force_pw_update": 0,
        "force_tfa": 0,
        "sogo_access": 1,
        "active": 1,
        "tls_enforce_in": 0,
        "tls_enforce_out": 0,
        "imap_access": 1,
        "pop3_access": 1,
        "smtp_access": 1,
        "sieve_access": 1,
        "eas_access": 1,
        "dav_access": 1,
        "acl_spam_alias": 1,
        "acl_tls_policy": 1,
        "acl_spam_score": 1,
        "acl_spam_policy": 1,
        "acl_delimiter_action": 1,
        "acl_syncjobs": 1,
        "acl_eas_reset": 1,
        "acl_sogo_profile_reset": 1,
        "acl_pushover": 0,
        "acl_quarantine": 1,
        "acl_quarantine_attachments": 1,
        "acl_quarantine_notification": 1,
        "acl_quarantine_category": 1,
        "acl_app_passwds": 1,
        "acl_pw_reset": 1,
    }
    for template_type, attributes in (
        ("domain", default_domain_template),
        ("mailbox", default_mailbox_template),
    ):
        run_sql(
            "INSERT INTO `templates` (`type`, `template`, `attributes`) "
            f"VALUES ({sql_literal(template_type)}, 'Default', "
            f"{sql_literal(json.dumps(attributes, separators=(',', ':')))}) "
            "ON DUPLICATE KEY UPDATE `attributes` = VALUES(`attributes`)"
        )
    print("  logs/tfa/fido2/settingsmap/templates/routing UI compatibility schema: OK")
    redispass = os.environ.get("REDISPASS") or MAILCOW_ENV.get("REDISPASS", "")
    if redispass:
        docker_run(
            [
                "sudo",
                "docker",
                "exec",
                "-e",
                f"REDISPASS={redispass}",
                "redis-mailcow",
                "sh",
                "-lc",
                'redis-cli -a "$REDISPASS" SET Q_RETENTION_SIZE 50 >/dev/null && redis-cli -a "$REDISPASS" SET Q_MAX_SIZE 10 >/dev/null',
            ],
            check=False,
        )
        print("  quarantine demo defaults: OK")
    else:
        print("  [WARN] REDISPASS unavailable; quarantine demo defaults not set")


def patch_mailcow_web_for_ui():
    """Patch mounted Mailcow web code for this custom schema."""
    print("\n--- Step 1d: Patching Mailcow UI route/query compatibility ---")
    auth_path = os.path.join(MAILCOW_DOCKERIZED_WEB, "inc", "functions.auth.inc.php")
    if not os.path.exists(auth_path):
        print(f"  [FAIL] Missing auth functions file: {auth_path}")
        sys.exit(1)
    with open(auth_path, encoding="utf-8") as handle:
        content = handle.read()
    patched = content.replace("WHERE `kind` NOT REGEXP", "WHERE `mailbox`.`kind` NOT REGEXP")
    if patched != content:
        backup = f"{auth_path}.bak.{int(time.time())}"
        run(f"sudo cp {shlex.quote(auth_path)} {shlex.quote(backup)}")
        with open("/tmp/mailcow_functions_auth.inc.php", "w", encoding="utf-8") as handle:
            handle.write(patched)
        run(f"sudo cp /tmp/mailcow_functions_auth.inc.php {shlex.quote(auth_path)}")
        print("  functions.auth.inc.php mailbox.kind query patch: OK")
    else:
        print("  functions.auth.inc.php mailbox.kind query patch already present.")

    asset_rewrites = {
        os.path.join(MAILCOW_DOCKERIZED_WEB, "inc", "header.inc.php"): [
            ("$CSSPath = '/tmp/' . $hash . '.css';", "$CSSPath = '/web/cache/' . $hash . '.css';"),
            ("cleanupCSS($hash);", "cleanupCSS($hash, '/web/cache/*.css');"),
            ("'css_path' => '/cache/'.basename($CSSPath),", "'css_path' => '/cache/'.basename($CSSPath).'?v='.filemtime($CSSPath),"),
        ],
        os.path.join(MAILCOW_DOCKERIZED_WEB, "inc", "footer.inc.php"): [
            ("$JSPath = '/tmp/' . $hash . '.js';", "$JSPath = '/web/cache/' . $hash . '.js';"),
            ("cleanupJS($hash);", "cleanupJS($hash, '/web/cache/*.js');"),
            ("'js_path' => '/cache/'.basename($JSPath),", "'js_path' => '/cache/'.basename($JSPath).'?v='.filemtime($JSPath),"),
        ],
    }
    for file_path, replacements in asset_rewrites.items():
        if not os.path.exists(file_path):
            print(f"  [FAIL] Missing UI include file: {file_path}")
            sys.exit(1)
        with open(file_path, encoding="utf-8") as handle:
            current = handle.read()
        updated = current
        for old, new in replacements:
            if old not in updated and new not in updated:
                print(f"  [FAIL] Missing expected asset-cache marker in {file_path}: {old}")
                sys.exit(1)
            updated = updated.replace(old, new)
        if updated != current:
            backup = f"{file_path}.bak.{int(time.time())}"
            run(f"sudo cp {shlex.quote(file_path)} {shlex.quote(backup)}")
            temp_path = f"/tmp/mailcow_{os.path.basename(file_path)}"
            with open(temp_path, "w", encoding="utf-8") as handle:
                handle.write(updated)
            run(f"sudo cp {shlex.quote(temp_path)} {shlex.quote(file_path)}")
            print(f"  {os.path.basename(file_path)} /web/cache asset path patch: OK")
        else:
            print(f"  {os.path.basename(file_path)} /web/cache asset path patch already present.")


def install_compat_api():
    """Install read-only compatibility endpoints for custom Mailcow stacks."""
    print("\n--- Step 1e: Installing compatibility API shim ---")
    source = os.path.join(SCRIPT_DIR, "mailcow_api_compat.php")
    destination = os.path.join(MAILCOW_DOCKERIZED_WEB, "mailcow_compat_api.php")
    if not os.path.exists(source):
        print(f"  [FAIL] Missing compatibility script: {source}")
        sys.exit(1)
    run(f"sudo cp {shlex.quote(source)} {shlex.quote(destination)}")
    run(f"sudo chmod 0444 {shlex.quote(destination)}")
    print("  compatibility API: OK")


def install_demo_webmail():
    """Install lab webmail with a Report Phish button."""
    print("\n--- Step 1f: Installing demo webmail surface ---")
    source = os.path.join(SCRIPT_DIR, "mailcow_demo_webmail.php")
    destination = os.path.join(MAILCOW_DOCKERIZED_WEB, "demo_webmail.php")
    if not os.path.exists(source):
        print(f"  [FAIL] Missing demo webmail script: {source}")
        sys.exit(1)
    run(f"sudo cp {shlex.quote(source)} {shlex.quote(destination)}")
    run(f"sudo chmod 0444 {shlex.quote(destination)}")
    print("  demo webmail: OK")


# ─── Step 2: Deploy php-fpm-mailcow-api ────────────────────────────────

def deploy_php_fpm():
    """Deploy parallel php-fpm container with web code on port 9002."""
    print("\n--- Step 2: Deploying php-fpm-mailcow-api ---")

    # Check if already running
    existing = run("sudo docker ps --filter name=php-fpm-mailcow-api --format '{{.Names}}'", check=False)
    if existing[0] == "php-fpm-mailcow-api":
        print("  php-fpm-mailcow-api already running. Stopping for redeploy...")
        run("sudo docker stop php-fpm-mailcow-api")
        run("sudo docker rm php-fpm-mailcow-api")

    # Create config directory
    run(f"mkdir -p {NGINX_CONF_DIR}/phpfpm")

    # Write www.conf overriding listen port to 9002 (Keycloak owns 9000)
    pool_conf = """[www]
listen = 127.0.0.1:9002
listen.backlog = 511
user = www-data
group = www-data
pm = dynamic
pm.max_children = 5
pm.start_servers = 2
pm.min_spare_servers = 1
pm.max_spare_servers = 3
pm.max_requests = 500
clear_env = no
catch_workers_output = yes
decorate_workers_output = no
"""
    www_conf_path = f"{NGINX_CONF_DIR}/phpfpm/www.conf"
    with open("/tmp/mailcow_api_www.conf", "w") as f:
        f.write(pool_conf)
    run(f"cp /tmp/mailcow_api_www.conf {www_conf_path}")

    # Override zz-docker.conf (loads after www.conf, would reset listen back to 9000)
    zz_conf = """[global]
daemonize = no

[www]
listen = 127.0.0.1:9002
"""
    zz_conf_path = f"{NGINX_CONF_DIR}/phpfpm/zz-docker.conf"
    with open("/tmp/mailcow_api_zz.conf", "w") as f:
        f.write(zz_conf)
    run(f"cp /tmp/mailcow_api_zz.conf {zz_conf_path}")

    # Write Redis session config (entrypoint normally does this)
    redispass = os.environ.get("REDISPASS") or MAILCOW_ENV.get("REDISPASS", "")
    session_conf = f"""session.save_handler = redis
session.save_path = "tcp://127.0.0.1:6379?auth={redispass}"
"""
    session_path = f"{NGINX_CONF_DIR}/phpfpm/session_store.ini"
    with open("/tmp/mailcow_api_session.ini", "w") as f:
        f.write(session_conf)
    run(f"cp /tmp/mailcow_api_session.ini {session_path}")

    # Write a simple startup script instead of using the broken entrypoint
    startup_script = """#!/bin/bash
# Set up Redis session store
cat > /usr/local/etc/php/conf.d/session_store.ini << 'SESS_EOF'
SESS_EOF
echo 'session.save_handler = redis' > /usr/local/etc/php/conf.d/session_store.ini
echo 'session.save_path = "tcp://127.0.0.1:6379?auth='${REDISPASS}'"' >> /usr/local/etc/php/conf.d/session_store.ini

# Fix permissions
mkdir -p /web/cache /web/templates/cache
chown -R 82:82 /web/cache /web/templates/cache 2>/dev/null
chmod 775 /web/cache /web/templates/cache 2>/dev/null
find /web/cache/* -not -name '.gitkeep' -delete 2>/dev/null
find /web/templates/cache/* -not -name '.gitkeep' -delete 2>/dev/null

# Start php-fpm
exec php-fpm
"""
    startup_path = f"{NGINX_CONF_DIR}/phpfpm/start.sh"
    with open("/tmp/mailcow_api_start.sh", "w") as f:
        f.write(startup_script)
    run(f"cp /tmp/mailcow_api_start.sh {startup_path}")
    run(f"chmod +x {startup_path}")

    cmd = (
        f"sudo docker run -d "
        f"--name php-fpm-mailcow-api "
        f"--restart unless-stopped "
        f"--network host "
        f"-e MAILCOW_HOSTNAME=mailcow.local "
        f"-e TZ=America/New_York "
        f"-e MAILCOW_PASS_SCHEME=BLF-CRYPT "
        f"-e DASHBOARD_API_BASE={shlex.quote(os.environ.get('DASHBOARD_API_BASE', 'http://127.0.0.1:25480'))} "
        f"-e DEMO_WEBMAIL_IMAP_HOST={shlex.quote(os.environ.get('DEMO_WEBMAIL_IMAP_HOST', '127.0.0.1'))} "
        f"-e DEMO_WEBMAIL_IMAP_PORT={shlex.quote(os.environ.get('DEMO_WEBMAIL_IMAP_PORT', '143'))} "
        f"-e DEMO_WEBMAIL_SMTP_HOST={shlex.quote(os.environ.get('DEMO_WEBMAIL_SMTP_HOST', '127.0.0.1'))} "
        f"-e DEMO_WEBMAIL_SMTP_PORT={shlex.quote(os.environ.get('DEMO_WEBMAIL_SMTP_PORT', '25'))} "
        f"--add-host dockerapi:127.0.0.1 "
        f"--add-host nginx:127.0.0.1 "
        f"-v {MAILCOW_DOCKERIZED_WEB}:/web:rw "
        f"-v {www_conf_path}:/usr/local/etc/php-fpm.d/www.conf:ro "
        f"-v {zz_conf_path}:/usr/local/etc/php-fpm.d/zz-docker.conf:ro "
        f"-v {startup_path}:/usr/local/bin/mailcow-api-start.sh:ro "
        f"-v deploy_mysql-socket:/var/run/mysqld:ro "
        f"--env-file {shlex.quote(MAILCOW_ENV_FILE)} "
        f"--entrypoint /usr/local/bin/mailcow-api-start.sh "
        f"mailcow/phpfpm:1.92"
    )
    stdout, stderr = run(cmd)
    print(f"  Started php-fpm-mailcow-api (container ID: {stdout[:12]})")

    # Wait for php-fpm to listen on port 9002
    if wait_for_port("127.0.0.1", PHPFPM_PORT):
        print(f"  php-fpm listening on port {PHPFPM_PORT}")
    else:
        print(f"  [WARN] php-fpm port {PHPFPM_PORT} not ready after 30s")


# ─── Step 3: Deploy nginx-mailcow-api ──────────────────────────────────

def deploy_nginx():
    """Deploy nginx container with FastCGI proxy on port 8081."""
    print("\n--- Step 3: Deploying nginx-mailcow-api ---")

    # Check if already running
    existing = run("sudo docker ps --filter name=nginx-mailcow-api --format '{{.Names}}'", check=False)
    if existing[0] == "nginx-mailcow-api":
        print("  nginx-mailcow-api already running. Stopping for redeploy...")
        run("sudo docker stop nginx-mailcow-api")
        run("sudo docker rm nginx-mailcow-api")

    # Create nginx config directory
    run(f"mkdir -p {NGINX_CONF_DIR}/nginx/conf")
    run(f"mkdir -p {NGINX_CONF_DIR}/nginx/logs")

    # Write nginx config
    nginx_conf = f"""user nginx;
worker_processes auto;
error_log /var/log/nginx/error.log notice;
pid /var/run/nginx.pid;

events {{
    worker_connections 1024;
}}

http {{
    include /etc/nginx/mime.types;
    default_type application/octet-stream;
    server_tokens off;

    log_format main '$remote_addr - $remote_user [$time_local] "$request" '
                    '$status $body_bytes_sent "$http_referer" '
                    '"$http_user_agent" "$http_x_forwarded_for"';
    access_log /var/log/nginx/access.log main;

    sendfile on;
    keepalive_timeout 65;

    server {{
        listen {API_PORT};
        listen [::]:{API_PORT};
        listen {UI_DEMO_PORT};
        listen [::]:{UI_DEMO_PORT};
        server_name _;

        root /web;
        index index.php;

        client_max_body_size 0;

        # Block direct access to internal files
        location ~ ^/inc/lib/ {{
            deny all;
            return 403;
        }}

        # Compatibility read endpoints for custom deployments where the stock
        # json_api.php returns empty bodies behind this shim.
        location = /api/v1/search/domain {{
            rewrite ^ /mailcow_compat_api.php?action=search_domain last;
        }}

        location = /api/v1/get/quarantine/all {{
            rewrite ^ /mailcow_compat_api.php?action=get_quarantine last;
        }}

        location ~ ^/api/v1/get/(domain|mailbox)/template/all$ {{
            rewrite ^/api/v1/get/(domain|mailbox)/template/all$ /mailcow_compat_api.php?action=get_template&type=$1 last;
        }}

        location ~ ^/api/v1/get/(domain|mailbox|alias)/(.*)$ {{
            rewrite ^/api/v1/get/(domain|mailbox|alias)/(.*)$ /mailcow_compat_api.php?resource=$1&selector=$2 last;
        }}

        # API routing - forwards everything else to json_api.php
        location ~ ^/api/v1/(.*)$ {{
            try_files $uri $uri/ /json_api.php?query=$1&$args;
        }}

        # PHP processing via FastCGI
        location ~ \\.php$ {{
            try_files $uri =404;
            fastcgi_split_path_info ^(.+\\.php)(/.+)$;
            fastcgi_pass 127.0.0.1:{PHPFPM_PORT};
            fastcgi_index index.php;
            include /etc/nginx/fastcgi_params;
            fastcgi_param SCRIPT_FILENAME $document_root$fastcgi_script_name;
            fastcgi_param PATH_INFO $fastcgi_path_info;
            fastcgi_param HTTP_X_API_KEY $http_x_api_key;
            fastcgi_param HTTP_SEC_FETCH_DEST empty;
            fastcgi_param HTTP_CONTENT_TYPE $content_type;
            fastcgi_read_timeout 3600;
            fastcgi_send_timeout 3600;
        }}

        # Static files
        location ~ ^/cache/ {{
            add_header Cache-Control "no-store, no-cache, must-revalidate" always;
            try_files $uri =404;
        }}

        location ~ ^/(fonts|js|css|img)/ {{
            expires max;
            add_header Cache-Control public;
        }}

        # Demo entrypoint: route the bare UI URL to the admin surface.
        # The custom deployment's root/user-login path can return an empty body,
        # while /admin/ is the verified Mailcow admin UI used for demos. Strip
        # stale user-session cookies here so old /user sessions cannot redirect
        # operators back to the blank user UI.
        location = / {{
            include /etc/nginx/fastcgi_params;
            fastcgi_pass 127.0.0.1:{PHPFPM_PORT};
            fastcgi_index index.php;
            fastcgi_param SCRIPT_FILENAME $document_root/admin/index.php;
            fastcgi_param SCRIPT_NAME /admin/index.php;
            fastcgi_param REQUEST_URI /admin/;
            fastcgi_param HTTP_COOKIE "";
            fastcgi_param HTTP_X_API_KEY $http_x_api_key;
            fastcgi_param HTTP_SEC_FETCH_DEST empty;
            fastcgi_param HTTP_CONTENT_TYPE $content_type;
            fastcgi_read_timeout 3600;
            fastcgi_send_timeout 3600;
        }}

        location = /admin/ {{
            include /etc/nginx/fastcgi_params;
            fastcgi_pass 127.0.0.1:{PHPFPM_PORT};
            fastcgi_index index.php;
            fastcgi_param SCRIPT_FILENAME $document_root/admin/index.php;
            fastcgi_param SCRIPT_NAME /admin/index.php;
            fastcgi_param REQUEST_URI /admin/;
            fastcgi_param HTTP_COOKIE "";
            fastcgi_param HTTP_X_API_KEY $http_x_api_key;
            fastcgi_param HTTP_SEC_FETCH_DEST empty;
            fastcgi_param HTTP_CONTENT_TYPE $content_type;
            fastcgi_read_timeout 3600;
            fastcgi_send_timeout 3600;
        }}

        location = /user {{
            add_header Set-Cookie "PHPSESSID=deleted; Path=/; Max-Age=0; HttpOnly; SameSite=Lax" always;
            add_header Set-Cookie "MCSESSID=deleted; Path=/; Max-Age=0; HttpOnly; SameSite=Lax" always;
            return 302 /;
        }}

        location = /user/ {{
            add_header Set-Cookie "PHPSESSID=deleted; Path=/; Max-Age=0; HttpOnly; SameSite=Lax" always;
            add_header Set-Cookie "MCSESSID=deleted; Path=/; Max-Age=0; HttpOnly; SameSite=Lax" always;
            return 302 /;
        }}

        # Demo webmail uses the real Mailcow IMAP/SMTP path and records
        # Report Phish actions into the dashboard intake plus Mailcow
        # quarantine table. Route SOGo links here until the upstream SOGo
        # service is production-hardened in this custom stack.
        location = /webmail {{
            rewrite ^ /demo_webmail.php last;
        }}

        location = /webmail/ {{
            rewrite ^ /demo_webmail.php last;
        }}

        location ~ ^/SOGo/ {{
            rewrite ^ /demo_webmail.php last;
        }}

        location / {{
            try_files $uri $uri/ @php_extension;
        }}

        location @php_extension {{
            rewrite ^(.+)$ $1.php last;
        }}
    }}
}}
"""
    nginx_conf_path = f"{NGINX_CONF_DIR}/nginx/conf/nginx.conf"
    with open("/tmp/mailcow_nginx.conf", "w") as f:
        f.write(nginx_conf)
    run(f"cp /tmp/mailcow_nginx.conf {nginx_conf_path}")

    # Pull nginx:alpine if not present
    run("sudo docker pull nginx:alpine", check=False)

    cmd = (
        f"sudo docker run -d "
        f"--name nginx-mailcow-api "
        f"--restart unless-stopped "
        f"--network host "
        f"-e TZ=America/New_York "
        f"-v {MAILCOW_DOCKERIZED_WEB}:/web:ro "
        f"-v {nginx_conf_path}:/etc/nginx/nginx.conf:ro "
        f"-v {NGINX_CONF_DIR}/nginx/logs:/var/log/nginx:rw "
        f"nginx:alpine"
    )
    stdout, stderr = run(cmd)
    print(f"  Started nginx-mailcow-api (container ID: {stdout[:12]})")

    # Wait for nginx to listen on API port
    if wait_for_port("127.0.0.1", API_PORT):
        print(f"  nginx listening on port {API_PORT}")
    else:
        print(f"  [WARN] nginx port {API_PORT} not ready after 30s")


# ─── Step 4: Test API ──────────────────────────────────────────────────

def test_api(api_key):
    """Test the API endpoints."""
    print("\n--- Step 4: Testing API endpoints ---")

    base_url = f"http://127.0.0.1:{API_PORT}"
    headers = {
        "X-API-Key": api_key,
        "Content-Type": "application/json",
        "Sec-Fetch-Dest": "script",
    }

    # Test 1: Get all mailboxes
    try:
        req = urllib.request.Request(
            f"{base_url}/api/v1/get/mailbox/all",
            headers=headers,
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            count = len(data) if isinstance(data, list) else 0
            print(f"  [PASS] GET /api/v1/get/mailbox/all - {count} mailboxes")
    except Exception as e:
        print(f"  [FAIL] GET /api/v1/get/mailbox/all - {e}")
        return False

    # Test 2: Get domain
    try:
        req = urllib.request.Request(
            f"{base_url}/api/v1/get/domain/mailcow.local",
            headers=headers,
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            print(f"  [PASS] GET /api/v1/get/domain/mailcow.local")
    except Exception as e:
        print(f"  [FAIL] GET /api/v1/get/domain/mailcow.local - {e}")
        return False

    # Test 3: Get aliases
    try:
        req = urllib.request.Request(
            f"{base_url}/api/v1/get/alias/all",
            headers=headers,
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            count = len(data) if isinstance(data, list) else 0
            print(f"  [PASS] GET /api/v1/get/alias/all - {count} aliases")
    except Exception as e:
        print(f"  [FAIL] GET /api/v1/get/alias/all - {e}")
        return False

    # Test 4: Invalid API key returns 401
    try:
        bad_headers = {"X-API-Key": "invalid", "Sec-Fetch-Dest": "script"}
        req = urllib.request.Request(
            f"{base_url}/api/v1/get/mailbox/all",
            headers=bad_headers,
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            print(f"  [FAIL] Invalid key should be rejected (got {resp.status})")
            return False
    except urllib.error.HTTPError as e:
        if e.code == 401:
            print(f"  [PASS] Invalid API key correctly rejected (401)")
        else:
            print(f"  [FAIL] Wrong error code: {e.code}")
            return False
    except Exception as e:
        print(f"  [WARN] Invalid key test: {e}")

    return True


# ─── Main ──────────────────────────────────────────────────────────────

def test_ui():
    """Smoke test the optional demo UI without credentials."""
    print("\n--- Step 5: Testing demo UI surface ---")
    url = f"http://127.0.0.1:{UI_DEMO_PORT}/"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            body = resp.read()
            if resp.status == 200 and b"login_user" in body and b"pass_user" in body:
                print(f"  [PASS] Demo UI login page on port {UI_DEMO_PORT}")
                text = body.decode("utf-8", "replace")
                refs = re.findall(r"/cache/[^\"']+", text)
                for ref in refs:
                    with urllib.request.urlopen(f"http://127.0.0.1:{UI_DEMO_PORT}{ref}", timeout=15) as asset_resp:
                        asset_body = asset_resp.read(64)
                        if asset_resp.status != 200 or not asset_body:
                            print(f"  [FAIL] Demo UI cache asset failed: {ref}")
                            return False
                print(f"  [PASS] Demo UI cache assets - {len(refs)} checked")
                stale_req = urllib.request.Request(
                    url,
                    headers={"Cookie": "MCSESSID=stale-demo-session"},
                    method="GET",
                )
                with urllib.request.urlopen(stale_req, timeout=15) as stale_resp:
                    stale_body = stale_resp.read()
                    if stale_resp.status != 200 or b"Administrator Login" not in stale_body:
                        print("  [FAIL] Demo UI stale session did not return admin login")
                        return False
                user_req = urllib.request.Request(
                    f"http://127.0.0.1:{UI_DEMO_PORT}/user",
                    headers={"Cookie": "MCSESSID=stale-demo-session"},
                    method="GET",
                )
                opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler)
                with opener.open(user_req, timeout=15) as user_resp:
                    final_url = user_resp.geturl()
                    user_body = user_resp.read()
                    if "/user" in final_url or b"Administrator Login" not in user_body:
                        print("  [FAIL] Demo UI /user stale session did not recover to admin login")
                        return False
                print("  [PASS] Demo UI stale session recovery")
                search_payload = json.dumps({
                    "draw": 1,
                    "start": 0,
                    "length": 10,
                    "search": {"value": ""},
                }).encode("utf-8")
                search_req = urllib.request.Request(
                    f"http://127.0.0.1:{UI_DEMO_PORT}/api/v1/search/domain",
                    data=search_payload,
                    headers={
                        "Cookie": "MCSESSID=demo-ui-session",
                        "Content-Type": "application/json",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(search_req, timeout=15) as search_resp:
                    search_data = json.loads(search_resp.read())
                    if "data" not in search_data or "recordsTotal" not in search_data:
                        print("  [FAIL] Demo UI domain search returned invalid DataTables JSON")
                        return False
                quarantine_req = urllib.request.Request(
                    f"http://127.0.0.1:{UI_DEMO_PORT}/api/v1/get/quarantine/all",
                    headers={"Cookie": "MCSESSID=demo-ui-session"},
                    method="GET",
                )
                with urllib.request.urlopen(quarantine_req, timeout=15) as quarantine_resp:
                    quarantine_data = json.loads(quarantine_resp.read())
                    if not isinstance(quarantine_data, list):
                        print("  [FAIL] Demo UI quarantine endpoint returned invalid JSON")
                        return False
                for template_type in ("domain", "mailbox"):
                    template_req = urllib.request.Request(
                        f"http://127.0.0.1:{UI_DEMO_PORT}/api/v1/get/{template_type}/template/all",
                        headers={"Cookie": "MCSESSID=demo-ui-session"},
                        method="GET",
                    )
                    with urllib.request.urlopen(template_req, timeout=15) as template_resp:
                        template_data = json.loads(template_resp.read())
                        if not isinstance(template_data, list):
                            print(f"  [FAIL] Demo UI {template_type} template endpoint returned invalid JSON")
                            return False
                print("  [PASS] Demo UI table JSON endpoints")
                webmail_req = urllib.request.Request(
                    f"http://127.0.0.1:{UI_DEMO_PORT}/SOGo/so",
                    method="GET",
                )
                with urllib.request.urlopen(webmail_req, timeout=15) as webmail_resp:
                    webmail_body = webmail_resp.read(30000).decode("utf-8", errors="replace")
                    if "Mailcow Demo Webmail" not in webmail_body or "Report Phish" not in webmail_body:
                        print("  [FAIL] Demo webmail/report-phish route did not render")
                        return False
                print("  [PASS] Demo webmail/report-phish route")
                return True
            print(f"  [FAIL] Demo UI unexpected response on port {UI_DEMO_PORT}")
            return False
    except Exception as exc:
        print(f"  [FAIL] Demo UI check failed: {exc}")
        return False


def main():
    print("=" * 60)
    print("Mailcow HTTP API Stack Deployment")
    print("=" * 60)

    # Check prerequisites
    print("\n--- Prerequisites ---")

    # Check web code exists
    wc, _ = run(f"test -d {shlex.quote(MAILCOW_DOCKERIZED_WEB)} && echo 'OK'", check=False)
    if wc != "OK":
        print(f"  [FAIL] Web code not found at {MAILCOW_DOCKERIZED_WEB}")
        sys.exit(1)
    print("  Web code: OK")

    wc, _ = run(f"test -f {shlex.quote(MAILCOW_ENV_FILE)} && echo 'OK'", check=False)
    if wc != "OK":
        print(f"  [FAIL] Mailcow env file not found at {MAILCOW_ENV_FILE}")
        sys.exit(1)
    print("  Mailcow env file: OK")

    # Check php-fpm image
    wc, _ = run("sudo docker image inspect mailcow/phpfpm:1.92 >/dev/null 2>&1 && echo 'OK'", check=False)
    if wc != "OK":
        print("  [FAIL] mailcow/phpfpm:1.92 image not found")
        sys.exit(1)
    print("  php-fpm image: OK")

    # Check MySQL reachable
    wc = run_sql("SELECT 1")
    if "1" not in wc:
        print("  [FAIL] MySQL not reachable")
        sys.exit(1)
    print("  MySQL: OK")

    # Check port availability
    import socket
    for port in [PHPFPM_PORT, API_PORT]:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                print(f"  [WARN] Port {port} already in use - will be reclaimed")

    # Deploy
    api_key = setup_api_table()
    write_api_key_file(api_key)
    setup_identity_provider_table()
    setup_ui_compat_schema()
    setup_identity_provider_defaults()
    setup_mailbox_delivery_aliases()
    patch_mailcow_web_for_ui()
    install_compat_api()
    install_demo_webmail()
    deploy_php_fpm()
    deploy_nginx()

    # Wait a bit for everything to settle
    print("\n  Waiting for services to stabilize...")
    time.sleep(5)

    # Test
    success = test_api(api_key) and test_ui()

    if success:
        print("\n" + "=" * 60)
        print("DEPLOYMENT SUCCESSFUL")
        print(f"  API URL: http://127.0.0.1:{API_PORT}/api/v1/")
        print(f"  Demo UI: http://<host>:{UI_DEMO_PORT}/")
        print("  API Key: written to restricted local file")
        print(f"  php-fpm: port {PHPFPM_PORT}")
        print(f"  nginx:   port {API_PORT}")
        print("=" * 60)

        write_api_key_file(api_key)
    else:
        print("\n[FAIL] API tests failed. Check logs:")
        print("  docker logs nginx-mailcow-api")
        print("  docker logs php-fpm-mailcow-api")
        sys.exit(1)


if __name__ == "__main__":
    main()
