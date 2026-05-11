#!/usr/bin/env python3
"""
Wazuh Bridge Deployment Orchestrator.
Runs: prerequisite checks, Keycloak setup, Wazuh setup, initial sync.
Zero hardcoded secrets. All credentials from .env or environment.
"""

import json
import os
import secrets
import ssl
import sys
import urllib.request
import urllib.parse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE


def parse_env(path):
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip('"\''))


def load_config():
    for env_path in [
        os.path.join(SKILL_DIR, ".env"),
        os.path.join(os.getcwd(), ".env"),
    ]:
        if os.path.exists(env_path):
            parse_env(env_path)
            break
    return {
        "keycloak_url": os.environ.get("KEYCLOAK_URL", "http://localhost:8080").rstrip("/"),
        "keycloak_admin": os.environ.get("KEYCLOAK_ADMIN_USER", "admin"),
        "keycloak_password": os.environ.get("KEYCLOAK_ADMIN_PASSWORD"),
        "bridge_realm": os.environ.get("BRIDGE_REALM", "wazuh"),
        "wazuh_url": os.environ.get("WAZUH_URL", "https://192.168.50.222:26500").rstrip("/"),
        "wazuh_username": os.environ.get("WAZUH_USERNAME", "wazuh-wui"),
        "wazuh_password": os.environ.get("WAZUH_PASSWORD"),
    }


def check_keycloak_health():
    try:
        kc_url = os.environ.get("KEYCLOAK_URL", "http://localhost:8080").rstrip("/")
        parsed = urllib.parse.urlparse(kc_url)
        mgmt = f"{parsed.scheme}://{parsed.hostname}:9000"
        req = urllib.request.Request(f"{mgmt}/health")
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=10) as resp:
            return resp.code == 200
    except Exception:
        return False


def check_wazuh_reachable():
    try:
        from wazuh_setup import WazuhClient
        config = load_config()
        wc = WazuhClient(config["wazuh_url"], config["wazuh_username"], config["wazuh_password"])
        return wc.is_reachable()
    except Exception:
        return False


def check_credentials():
    ok = True
    if not os.environ.get("KEYCLOAK_ADMIN_PASSWORD"):
        print("[FAIL] KEYCLOAK_ADMIN_PASSWORD not set")
        ok = False
    if not os.environ.get("WAZUH_PASSWORD"):
        print("[FAIL] WAZUH_PASSWORD not set")
        ok = False
    if ok:
        print("[OK] Credentials configured")
    return ok


def run_keycloak_setup():
    from keycloak_setup import run_setup
    return run_setup()


def run_wazuh_setup():
    from wazuh_setup import run_setup
    return run_setup()


def run_initial_sync():
    from sync_bridge import run_sync_cycle, load_config as sync_load_config
    config = sync_load_config()
    return run_sync_cycle(config)


def generate_env():
    env_path = os.path.join(SKILL_DIR, ".env")
    if os.path.exists(env_path):
        print(f"[INFO] .env already exists at {env_path}")
        return
    kc_pw = secrets.token_urlsafe(24)
    wz_pw = secrets.token_urlsafe(24)
    content = f"""# Wazuh Bridge - Auto-generated .env
# DO NOT commit to version control

KEYCLOAK_URL=http://localhost:8080
KEYCLOAK_ADMIN_USER=admin
KEYCLOAK_ADMIN_PASSWORD={kc_pw}

WAZUH_URL=https://192.168.50.222:26500
WAZUH_USERNAME=wazuh-wui
WAZUH_PASSWORD={wz_pw}

BRIDGE_REALM=wazuh
SYNC_INTERVAL=300
SYNC_STATE_FILE=.sync_state.json
"""
    with open(env_path, "w") as f:
        f.write(content)
    try:
        os.chmod(env_path, 0o600)
    except Exception:
        pass
    print(f"[OK] Generated .env at {env_path}")


def show_status():
    config = load_config()
    print("=== Wazuh Bridge Status ===")
    print(f"  Keycloak URL: {config['keycloak_url']}")
    print(f"  Wazuh URL: {config['wazuh_url']}")
    print(f"  Realm: {config['bridge_realm']}")
    print(f"  Keycloak health: {'OK' if check_keycloak_health() else 'DOWN'}")
    print(f"  Wazuh reachable: {'OK' if check_wazuh_reachable() else 'DOWN'}")

    state_file = os.path.join(SKILL_DIR, ".sync_state.json")
    if os.path.exists(state_file):
        with open(state_file, "r") as f:
            state = json.load(f)
        print(f"  Last sync: {state.get('last_sync', 'never')}")
        print(f"  Synced users: {len(state.get('synced_users', {}))}")
    else:
        print("  Sync state: not yet synced")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Wazuh Bridge Deployment Orchestrator")
    parser.add_argument("--status", action="store_true", help="Show deployment status")
    parser.add_argument("--init-env", action="store_true", help="Generate .env with random passwords")
    parser.add_argument("--setup-keycloak", action="store_true", help="Setup Keycloak side only")
    parser.add_argument("--setup-wazuh", action="store_true", help="Setup Wazuh side only")
    parser.add_argument("--full", action="store_true", help="Full deployment")
    parser.add_argument("--sync", action="store_true", help="Run initial sync after full deploy")

    args = parser.parse_args()
    config = load_config()

    if args.status:
        show_status()
        return

    if args.init_env:
        generate_env()
        return

    if args.setup_keycloak:
        print("=== Keycloak Setup ===")
        run_keycloak_setup()
        return

    if args.setup_wazuh:
        print("=== Wazuh Setup ===")
        run_wazuh_setup()
        return

    if args.full:
        print("=== Prerequisite Checks ===")
        if not check_credentials():
            print("[ERROR] Fix credentials before continuing")
            sys.exit(1)
        if not check_keycloak_health():
            print("[WARN] Keycloak health check failed")
        if not check_wazuh_reachable():
            print("[WARN] Wazuh reachability check failed")

        print("\n=== Keycloak Setup ===")
        run_keycloak_setup()

        print("\n=== Wazuh Setup ===")
        run_wazuh_setup()

        if args.sync:
            print("\n=== Initial Sync ===")
            results = run_initial_sync()
            print(f"\n=== Sync Results ===")
            print(f"  Keycloak reachable: {results['keycloak_reachable']}")
            print(f"  Wazuh reachable: {results['wazuh_reachable']}")
            print(f"  KC→Wazuh: {results['kc_to_wazuh']}")

        print("\n=== Deployment Complete ===")
        show_status()
        return

    parser.print_help()


if __name__ == "__main__":
    main()
