#!/usr/bin/env python3
"""Deployment Orchestrator - Keycloak-Mailcow Bridge.

Orchestrates the complete deployment:
1. Prerequisites check (Keycloak and Mailcow MySQL connectivity)
2. Keycloak realm, client, groups, roles, mappers, users setup
3. Mailcow IDP configuration, domain, distribution groups, shared mailboxes
4. Initial bidirectional sync
5. Verification and status report

Uses direct MySQL for Mailcow communication (HTTP API unavailable in this deployment).
Idempotent - safe to run multiple times.
"""

import argparse
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

# Add scripts directory to path for imports
sys.path.insert(0, os.path.dirname(__file__))

from keycloak_setup import KeycloakClient, ENV, KEYCLOAK_URL, REALM
from keycloak_setup import KEYCLOAK_ADMIN_PASSWORD, run_setup
from mailcow_idp_config import MailcowClient, MAILCOW_DOMAIN
from mailcow_idp_config import MYSQL_CONTAINER, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE
from mailcow_idp_config import ensure_domain, configure_idp
from mailcow_idp_config import create_distribution_groups, create_shared_mailbox, verify_config
from sync_engine import run_sync, load_sync_state


def banner(text):
    """Print a formatted banner."""
    width = 60
    print(f"\n{'=' * width}")
    print(f"  {text}")
    print("=" * width)


def check_keycloak_connectivity():
    """Check if Keycloak is reachable."""
    try:
        req = urllib.request.Request(
            f"{KEYCLOAK_URL.rstrip('/')}/realms/master",
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status == 200
    except Exception:
        return False


def check_mailcow_connectivity():
    """Check if Mailcow MySQL is reachable."""
    mc = MailcowClient(MYSQL_CONTAINER, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE)
    return mc.test_api()


def run_prerequisites():
    """Check all prerequisites before deployment."""
    banner("Prerequisites Check")

    checks = []

    # Keycloak connectivity
    print("[CHECK] Keycloak connectivity...")
    kc_ok = check_keycloak_connectivity()
    checks.append(("Keycloak API", kc_ok))
    print("[OK] Keycloak is reachable" if kc_ok
          else f"[FAIL] Keycloak NOT reachable at {KEYCLOAK_URL}")

    # Mailcow MySQL connectivity
    print("[CHECK] Mailcow MySQL connectivity...")
    mc_ok = check_mailcow_connectivity()
    checks.append(("Mailcow MySQL", mc_ok))
    print("[OK] Mailcow MySQL is reachable" if mc_ok
          else f"[FAIL] Mailcow MySQL NOT reachable (container={MYSQL_CONTAINER})")

    # Credentials check
    print("[CHECK] Credentials configured...")
    creds_ok = bool(KEYCLOAK_ADMIN_PASSWORD and MYSQL_PASSWORD)
    checks.append(("Credentials", creds_ok))
    if creds_ok:
        print("[OK] All credentials are configured")
    else:
        if not KEYCLOAK_ADMIN_PASSWORD:
            print("[FAIL] KEYCLOAK_ADMIN_PASSWORD not set")
        if not MYSQL_PASSWORD:
            print("[FAIL] MYSQL_PASSWORD not set")

    # Docker container check
    print("[CHECK] Mailcow containers running...")
    result = subprocess.run(
        ["docker", "inspect", "--format", "{{.State.Running}}", MYSQL_CONTAINER],
        capture_output=True, text=True, timeout=10,
    )
    docker_ok = result.stdout.strip() == "true"
    checks.append(("Mailcow MySQL container", docker_ok))
    print("[OK] MySQL container running" if docker_ok else "[FAIL] MySQL container not running")

    failed = [name for name, ok in checks if not ok]
    if failed:
        print(f"\n[ERROR] Prerequisites FAILED: {', '.join(failed)}")
        return False

    print("\n[OK] All prerequisites passed!")
    return True


def run_full_deployment():
    """Execute the complete deployment pipeline."""
    start_time = time.time()

    banner("Keycloak-Mailcow Bridge Deployment")
    print("Starting full deployment...")

    # Phase 0: Prerequisites
    if not run_prerequisites():
        return False

    # Phase 1: Keycloak Setup
    banner("Phase 1: Keycloak Configuration")
    try:
        run_setup()
    except Exception as e:
        print(f"[FAIL] Keycloak setup failed: {e}")
        return False
    print("[OK] Keycloak configuration complete")

    # Phase 2: Mailcow IDP Configuration
    banner("Phase 2: Mailcow IDP Configuration")
    try:
        mc = MailcowClient(MYSQL_CONTAINER, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE)
        ensure_domain(mc)
        configure_idp(mc)
        create_distribution_groups(mc)
        create_shared_mailbox(mc)
    except Exception as e:
        print(f"[FAIL] Mailcow setup failed: {e}")
        return False
    print("[OK] Mailcow configuration complete")

    # Phase 3: Initial Sync
    banner("Phase 3: Initial Bidirectional Sync")
    try:
        run_sync()
    except Exception as e:
        print(f"[FAIL] Initial sync failed: {e}")
        return False
    print("[OK] Initial sync complete")

    # Phase 4: Verification
    banner("Phase 4: Verification")
    try:
        mc = MailcowClient(MYSQL_CONTAINER, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE)
        verify_config(mc)
    except Exception as e:
        print(f"[WARN] Verification had issues: {e}")

    # Status Summary
    banner("Deployment Complete")
    elapsed = time.time() - start_time

    state = load_sync_state()
    print(f"  Time elapsed:    {elapsed:.1f}s")
    print(f"  Sync count:      {state.get('sync_count', 0)}")
    print(f"  Users synced:    {len(state.get('keycloak_users', {}))}")
    print(f"  Last sync:       {state.get('last_sync', 'never')}")
    print(f"\n  Keycloak URL:    {KEYCLOAK_URL}")
    print(f"  Mailcow Domain:  {MAILCOW_DOMAIN}")
    print(f"  Realm:           {REALM}")

    print("\n  Next steps:")
    print(f"    1. Visit {KEYCLOAK_URL}/admin/master/console/#/{REALM}/users")
    print("       Verify users have mailcow_template attribute")
    print("    2. Test IMAP/SMTP auth with provisioned mailboxes")
    print("    3. Test distribution group email routing")
    print('    4. Run: python3 scripts/test_integration.py --all')

    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deploy Keycloak-Mailcow Bridge")
    parser.add_argument("--env", help="Path to .env file")
    parser.add_argument("--prereq-only", action="store_true", help="Only check prerequisites")
    args = parser.parse_args()

    if args.prereq_only:
        sys.exit(0 if run_prerequisites() else 1)

    sys.exit(0 if run_full_deployment() else 1)
