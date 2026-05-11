#!/usr/bin/env python3
"""
IAM Bridge Deployment Orchestrator.
Deploys Keycloak + iTop integration with OIDC and SAML.
Idempotent: safe to run multiple times.
"""

import json
import os
import secrets
import subprocess
import sys
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)


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
        "keycloak_url": os.environ.get("KEYCLOAK_URL", "http://localhost:8080"),
        "keycloak_admin": os.environ.get("KEYCLOAK_ADMIN_USER", "admin"),
        "keycloak_password": os.environ.get("KEYCLOAK_ADMIN_PASSWORD"),
        "itop_url": os.environ.get("ITOP_URL", "http://localhost:25432"),
        "itop_username": os.environ.get("ITOP_USERNAME", "admin"),
        "itop_password": os.environ.get("ITOP_PASSWORD"),
    }


def write_env_file(env_path, keycloak_pw, itop_pw):
    """Write or update .env file with secrets."""
    content = f"""# IAM Bridge - Auto-generated .env file
# DO NOT commit to version control

# --- Keycloak Identity Provider ---
KEYCLOAK_URL=http://localhost:8080
KEYCLOAK_ADMIN_USER=admin
KEYCLOAK_ADMIN_PASSWORD={keycloak_pw}

# --- iTop ITSM Platform ---
ITOP_URL=http://localhost:25432
ITOP_USERNAME=admin
ITOP_PASSWORD={itop_pw}

# --- Bridge Configuration ---
BRIDGE_REALM=itop
BRIDGE_CLIENT_ID=itop-oidc-client
"""
    with open(env_path, "w") as f:
        f.write(content)
    os.chmod(env_path, 0o600)
    print(f"[OK] Environment file written: {env_path}")


def check_service_reachable(name, url):
    """Check if a service is reachable."""
    try:
        import urllib.request
        import ssl
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, context=ctx, timeout=10) as resp:
            return True
    except Exception:
        return False


def check_keycloak_health(kc_url):
    """Check Keycloak health endpoint."""
    management_url = kc_url.replace("8080", "9000", 1)
    if ":9000" not in management_url:
        management_url = kc_url.rsplit(":", 1)[0] + ":9000"
    return check_service_reachable("Keycloak Health", f"{management_url}/health")


def check_prerequisites(config):
    """Verify both services are running."""
    print("=== Checking Prerequisites ===")
    all_ok = True

    if check_keycloak_health(config["keycloak_url"]):
        print("[OK] Keycloak is healthy")
    else:
        print("[FAIL] Keycloak is not reachable")
        all_ok = False

    if check_service_reachable("iTop", config["itop_url"]):
        print("[OK] iTop is reachable")
    else:
        print("[FAIL] iTop is not reachable")
        all_ok = False

    if not config["keycloak_password"]:
        print("[FAIL] KEYCLOAK_ADMIN_PASSWORD not configured")
        all_ok = False

    if not config["itop_password"]:
        print("[FAIL] ITOP_PASSWORD not configured")
        all_ok = False

    return all_ok


def run_script(script_name, *args):
    """Run a Python script and return success status."""
    script_path = os.path.join(SCRIPT_DIR, script_name)
    if not os.path.exists(script_path):
        print(f"[ERROR] Script not found: {script_path}")
        return False

    cmd = [sys.executable or "python3", script_path] + list(args)
    print(f"[INFO] Running: {' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, timeout=300)
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        print(f"[ERROR] Script timed out: {script_name}")
        return False
    except Exception as e:
        print(f"[ERROR] Script failed: {e}")
        return False


def show_status(config):
    """Show deployment status."""
    print("=== IAM Bridge Status ===")
    print(f"  Keycloak URL: {config['keycloak_url']}")
    print(f"  iTop URL: {config['itop_url']}")

    if check_keycloak_health(config["keycloak_url"]):
        print("  Keycloak: HEALTHY")
    else:
        print("  Keycloak: UNREACHABLE")

    if check_service_reachable("iTop", config["itop_url"]):
        print("  iTop: REACHABLE")
    else:
        print("  iTop: UNREACHABLE")

    env_path = os.path.join(SKILL_DIR, ".env")
    if os.path.exists(env_path):
        print(f"  Config: {env_path} (exists)")
    else:
        print("  Config: MISSING")

    sync_state = os.environ.get("SYNC_STATE_FILE", os.path.join(SKILL_DIR, ".sync_state.json"))
    if os.path.exists(sync_state):
        with open(sync_state, "r") as f:
            state = json.load(f)
        print(f"  Last sync: {state.get('last_sync', 'never')}")
        print(f"  Synced users: {len(state.get('synced_users', {}))}")
    else:
        print("  Sync state: Not initialized")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="IAM Bridge Deployment Orchestrator")
    parser.add_argument("--status", action="store_true", help="Show deployment status")
    parser.add_argument("--setup-keycloak", action="store_true", help="Setup Keycloak side only")
    parser.add_argument("--setup-itop", action="store_true", help="Setup iTop side only")
    parser.add_argument("--full", action="store_true", help="Full deployment")
    parser.add_argument("--sync", action="store_true", help="Run sync after deployment")
    parser.add_argument("--init-env", action="store_true", help="Generate .env file with secrets")

    args = parser.parse_args()
    config = load_config()

    if args.status:
        show_status(config)
        return

    if args.init_env:
        kc_pw = secrets.token_urlsafe(32)
        itop_pw = secrets.token_urlsafe(32)
        write_env_file(os.path.join(SKILL_DIR, ".env"), kc_pw, itop_pw)
        print(f"[CRITICAL] Save these passwords:")
        print(f"  Keycloak admin: {kc_pw}")
        print(f"  iTop admin: {itop_pw}")
        return

    if not check_prerequisites(config):
        print("[ERROR] Prerequisites not met. Fix issues before proceeding.")
        sys.exit(1)

    if args.setup_keycloak:
        success = run_script("keycloak_setup.py")
        if success:
            print("[OK] Keycloak setup complete")
        else:
            print("[WARN] Keycloak setup had issues")
        return

    if args.setup_itop:
        success = run_script("itop_setup.py")
        if success:
            print("[OK] iTop setup complete")
        else:
            print("[WARN] iTop setup had issues")
        return

    if args.full or not any([args.setup_keycloak, args.setup_itop]):
        print("=== Full IAM Bridge Deployment ===\n")

        # Step 1: Keycloak setup
        print("--- Step 1: Keycloak Setup ---")
        if not run_script("keycloak_setup.py"):
            print("[WARN] Keycloak setup had issues, continuing...")

        # Step 2: iTop setup
        print("\n--- Step 2: iTop Setup ---")
        if not run_script("itop_setup.py"):
            print("[WARN] iTop setup had issues, continuing...")

        # Step 3: Initial sync
        if args.sync:
            print("\n--- Step 3: Initial Sync ---")
            run_script("sync_bridge.py", "--sync")

        print("\n[OK] IAM Bridge deployment complete!")
        show_status(config)
        return

    parser.print_help()


if __name__ == "__main__":
    main()
