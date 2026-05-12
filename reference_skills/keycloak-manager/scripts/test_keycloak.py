#!/usr/bin/env python3
"""
Keycloak End-to-End Feature Test Script.
Tests: health, users CRUD, groups CRUD, roles CRUD, role mappings.
Runs against a live Keycloak instance and reports pass/fail.
"""

import json
import os
import sys
import time
import urllib
import urllib.request
import ssl

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)

# Import the admin module
sys.path.insert(0, SCRIPT_DIR)

# We use the keycloak_admin module directly
from keycloak_admin import (
    health_check, get_token, load_credentials,
    create_user, list_users, update_user, delete_user, set_user_password, get_user,
    create_group, list_groups, update_group, delete_group,
    add_user_to_group, remove_user_from_group, get_group_members,
    create_role, list_roles, delete_role,
    assign_roles_to_user, remove_roles_from_user, get_user_roles,
    create_realm, list_realms,
)

BASE_URL = os.environ.get("KEYCLOAK_URL", "http://localhost:8080")
REALM = "master"
TEST_PREFIX = "test_kc"
TEST_PASSWORD = os.environ.get("KEYCLOAK_TEST_PASSWORD") or f"TmpPass{int(time.time())}!"


class TestRunner:
    def __init__(self, base_url, realm):
        self.base_url = base_url.rstrip("/")
        self.realm = realm
        self.token = None
        self.tests_passed = 0
        self.tests_failed = 0
        self.test_results = []

    def authenticate(self):
        """Authenticate and get admin token."""
        username, password = load_credentials()
        self.token = get_token(self.base_url, username, password)
        print(f"[AUTH] Connected as {username}")

    def run_test(self, name, func, *args, **kwargs):
        """Run a single test and record result."""
        try:
            result = func(*args, **kwargs)
            if result is True or result is not None and result is not False:
                self.tests_passed += 1
                self.test_results.append(("PASS", name, None))
                print(f"  PASS: {name}")
                return result
            else:
                self.tests_failed += 1
                self.test_results.append(("FAIL", name, "Returned falsy value"))
                print(f"  FAIL: {name} (returned falsy)")
                return None
        except Exception as e:
            self.tests_failed += 1
            self.test_results.append(("FAIL", name, str(e)))
            print(f"  FAIL: {name} ({e})")
            return None

    def test_health(self):
        ok, data = health_check(self.base_url)
        return ok

    def test_list_realms(self):
        realms = list_realms(self.token, self.base_url)
        return REALM in realms

    def run_all(self):
        """Execute the full test suite."""
        print(f"\n{'='*60}")
        print(f"KEYCLOAK END-TO-END TEST SUITE")
        print(f"Target: {self.base_url}")
        print(f"Realm: {self.realm}")
        print(f"{'='*60}\n")

        # --- HEALTH ---
        print("=== HEALTH ===")
        self.run_test("Health check", self.test_health)

        # --- AUTH ---
        print("\n=== AUTHENTICATION ===")
        try:
            self.authenticate()
            self.tests_passed += 1
            print("  PASS: Admin authentication")
        except Exception as e:
            self.tests_failed += 1
            print(f"  FAIL: Admin authentication ({e})")
            self.print_summary()
            return

        # --- REALMS ---
        print("\n=== REALMS ===")
        self.run_test("List realms", self.test_list_realms)

        # --- USERS ---
        print("\n=== USER OPERATIONS ===")
        test_user = f"{TEST_PREFIX}_user_{int(time.time())}"

        user_result = self.run_test(
            "Create user",
            lambda: create_user(
                self.token, self.base_url, self.realm, test_user,
                email=f"{test_user}@test.local",
                first_name="Test", last_name="User",
                password=TEST_PASSWORD,
            ),
        )

        self.run_test("List users (filter by username)", lambda: len(list_users(self.token, self.base_url, self.realm, username=test_user)) > 0)

        self.run_test(
            "Update user email",
            lambda: update_user(
                self.token, self.base_url, self.realm,
                user_result["id"] if user_result else "",
                email=f"updated_{test_user}@test.local",
            ),
        )

        self.run_test("Set new password", lambda: set_user_password(self.token, self.base_url, self.realm, test_user, f"{TEST_PASSWORD}2"))

        self.run_test("Delete user", lambda: delete_user(self.token, self.base_url, self.realm, user_result["id"]) if user_result else True)

        # --- GROUPS ---
        print("\n=== GROUP OPERATIONS ===")
        test_group = f"{TEST_PREFIX}_group_{int(time.time())}"

        group_result = self.run_test("Create group", lambda: create_group(self.token, self.base_url, self.realm, test_group))

        self.run_test("List groups (search)", lambda: len(list_groups(self.token, self.base_url, self.realm, search=test_group)) > 0)

        new_group_name = f"{test_group}_renamed"
        if group_result:
            self.run_test("Update group name", lambda: update_group(self.token, self.base_url, self.realm, group_result["id"], name=new_group_name))

        # Create subgroup
        subgroup_name = f"{TEST_PREFIX}_subgroup_{int(time.time())}"
        if group_result:
            self.run_test("Create subgroup", lambda: create_group(self.token, self.base_url, self.realm, subgroup_name, parent_id=group_result["id"]))

        self.run_test("Delete group", lambda: delete_group(self.token, self.base_url, self.realm, group_result["id"]) if group_result else True)

        # --- ROLES ---
        print("\n=== ROLE OPERATIONS ===")
        test_role = f"{TEST_PREFIX}_role_{int(time.time())}"

        self.run_test("Create role", lambda: create_role(self.token, self.base_url, self.realm, test_role, description="Test role"))

        self.run_test("List roles contains test role", lambda: any(r["name"] == test_role for r in list_roles(self.token, self.base_url, self.realm)))

        # --- INTEGRATION: User + Group + Role ---
        print("\n=== INTEGRATION TESTS ===")
        integ_user = f"{TEST_PREFIX}_integ_{int(time.time())}"
        integ_group = f"{TEST_PREFIX}_integ_grp_{int(time.time())}"
        integ_role = f"{TEST_PREFIX}_integ_role_{int(time.time())}"

        iuser = self.run_test(
            "Create integration user",
            lambda: create_user(
                self.token, self.base_url, self.realm, integ_user,
                email=f"{integ_user}@test.local",
                password=TEST_PASSWORD,
            ),
        )

        igroup = self.run_test("Create integration group", lambda: create_group(self.token, self.base_url, self.realm, integ_group))

        self.run_test("Create integration role", lambda: create_role(self.token, self.base_url, self.realm, integ_role, description="Integration test role"))

        if iuser and igroup:
            self.run_test("Add user to group", lambda: add_user_to_group(self.token, self.base_url, self.realm, iuser["id"], igroup["id"]))

            self.run_test("Verify group membership", lambda: len(get_group_members(self.token, self.base_url, self.realm, igroup["id"])) > 0)

        if iuser:
            self.run_test("Assign role to user", lambda: assign_roles_to_user(self.token, self.base_url, self.realm, integ_user, [integ_role]))

            self.run_test("Verify user has role", lambda: any(r["name"] == integ_role for r in get_user_roles(self.token, self.base_url, self.realm, integ_user)))

        if iuser:
            self.run_test("Remove role from user", lambda: remove_roles_from_user(self.token, self.base_url, self.realm, integ_user, [integ_role]))

        # Cleanup integration test objects
        if iuser:
            self.run_test("Cleanup: delete integration user", lambda: delete_user(self.token, self.base_url, self.realm, iuser["id"]))
        if igroup:
            self.run_test("Cleanup: delete integration group", lambda: delete_group(self.token, self.base_url, self.realm, igroup["id"]))
        self.run_test("Cleanup: delete integration role", lambda: delete_role(self.token, self.base_url, self.realm, integ_role))

        # --- SUMMARY ---
        self.print_summary()

    def print_summary(self):
        print(f"\n{'='*60}")
        print(f"TEST SUMMARY")
        print(f"{'='*60}")
        print(f"  PASSED: {self.tests_passed}")
        print(f"  FAILED: {self.tests_failed}")
        print(f"  TOTAL:  {self.tests_passed + self.tests_failed}")
        print(f"  RESULT: {'ALL TESTS PASSED' if self.tests_failed == 0 else 'SOME TESTS FAILED'}")

        if self.test_results:
            print(f"\nDetailed results:")
            for status, name, detail in self.test_results:
                marker = "OK" if status == "PASS" else f"FAIL: {detail}"
                print(f"  [{status}] {name} - {marker}")

        print(f"{'='*60}")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Keycloak E2E Test Suite")
    parser.add_argument("-u", "--url", default=None, help="Keycloak URL")
    parser.add_argument("-r", "--realm", default="master", help="Realm to test")
    args = parser.parse_args()

    url = args.url or os.environ.get("KEYCLOAK_URL", "http://localhost:8080")
    runner = TestRunner(url, args.realm)
    runner.run_all()

    return 0 if runner.tests_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
