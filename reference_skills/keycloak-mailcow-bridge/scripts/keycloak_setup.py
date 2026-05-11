#!/usr/bin/env python3
"""Keycloak Setup - Create mailcow realm, OIDC client, groups, roles, mappers, and test users.

Idempotent - safe to run multiple times. Uses Keycloak Admin REST API.
All credentials loaded from .env file (no hardcoded secrets).
"""

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request


# ─── Environment Loading ───────────────────────────────────────────────

def load_env(env_path=None):
    """Load environment variables from .env file."""
    if env_path is None:
        for candidate in [".env", os.path.join(os.path.dirname(__file__), "..", ".env")]:
            if os.path.exists(candidate):
                env_path = candidate
                break
    if env_path is None or not os.path.exists(env_path):
        print("[ERROR] .env file not found. Copy .env.example to .env and configure.", file=sys.stderr)
        sys.exit(1)

    vars = {}
    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            vars[k.strip()] = v.strip()
    return vars


ENV = load_env()

KEYCLOAK_URL = ENV.get("KEYCLOAK_URL", "http://localhost:8080")
KEYCLOAK_ADMIN_USER = ENV.get("KEYCLOAK_ADMIN_USER", "admin")
KEYCLOAK_ADMIN_PASSWORD = ENV.get("KEYCLOAK_ADMIN_PASSWORD", "")
REALM = ENV.get("BRIDGE_REALM", "mailcow")
CLIENT_ID = ENV.get("BRIDGE_CLIENT_ID", "mailcow-oidc")
TEST_USER_PASSWORD = ENV.get("TEST_USER_PASSWORD", "")
MAILCOW_DOMAIN = ENV.get("MAILCOW_DOMAIN", "localhost")
KEYCLOAK_VERSION = int(ENV.get("KEYCLOAK_VERSION", "26"))

if not TEST_USER_PASSWORD:
    print("[ERROR] TEST_USER_PASSWORD must be set from vault or environment")
    sys.exit(1)
ENABLE_MAILPASSWORD = ENV.get("ENABLE_MAILPASSWORD_FLOW", "true").lower() == "true"


# ─── HTTP Client ────────────────────────────────────────────────────────

class KeycloakClient:
    """Pure Python Keycloak Admin API client (zero external deps, no ORM)."""

    def __init__(self, url, admin_user, admin_password):
        self.url = url.rstrip("/")
        self.admin_user = admin_user
        self.admin_password = admin_password
        self.token = None
        self.realm_id = None

    def login(self):
        """Authenticate as admin and get access token."""
        data = urllib.parse.urlencode({
            "grant_type": "password",
            "username": self.admin_user,
            "password": self.admin_password,
            "client_id": "admin-cli",
        }).encode()

        req = urllib.request.Request(
            f"{self.url}/realms/master/protocol/openid-connect/token",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
                self.token = result["access_token"]
                print(f"[OK] Keycloak admin login successful")
                return True
        except urllib.error.HTTPError as e:
            print(f"[FAIL] Keycloak login failed: {e.code} {e.reason}")
            return False
        except Exception as e:
            print(f"[FAIL] Keycloak login error: {e}")
            return False

    def health_check(self):
        """Check Keycloak health endpoint."""
        try:
            req = urllib.request.Request(f"{self.url}/health/ready", method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status == 200
        except Exception:
            # Fallback to old health endpoint
            try:
                req = urllib.request.Request(f"{self.url}/realms/master", method="GET")
                with urllib.request.urlopen(req, timeout=10) as resp:
                    return resp.status == 200
            except Exception:
                return False

    def request(self, method, path, data=None):
        """Make authenticated API request."""
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }
        body = json.dumps(data).encode() if data else None
        req = urllib.request.Request(
            f"{self.url}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                if resp.status == 204:
                    return None
                return json.loads(resp.read())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace") if e.fp else ""
            return {"error": f"HTTP {e.code}: {body[:200]}"}
        except Exception as e:
            return {"error": str(e)}

    def get_realm(self, realm_name):
        """Get realm by name."""
        result = self.request("GET", f"/admin/realms/{realm_name}")
        if result and "error" not in result:
            return result
        return None

    def create_realm(self, realm_name, attributes=None):
        """Create realm if it doesn't exist."""
        existing = self.get_realm(realm_name)
        if existing:
            print(f"[OK] Realm '{realm_name}' already exists")
            return existing

        realm_data = {
            "realm": realm_name,
            "enabled": True,
            "registrationAllowed": False,
            "resetPasswordAllowed": False,
            "editUsernameAllowed": True,
        }
        if attributes:
            realm_data["attributes"] = attributes

        result = self.request("POST", "/admin/realms", realm_data)
        if result and "error" not in result:
            print(f"[OK] Realm '{realm_name}' created")
            return True
        elif result:
            print(f"[WARN] Realm '{realm_name}': {result.get('error', 'unknown')}")
            return False
        return True

    def find_client(self, realm, client_id):
        """Find client by client_id in realm."""
        path = f"/admin/realms/{realm}/clients?clientId={urllib.parse.quote(client_id)}"
        result = self.request("GET", path)
        if result and isinstance(result, list) and len(result) > 0:
            return result[0]
        return None

    def create_oidc_client(self, realm, client_id, redirect_uris, client_secret=None):
        """Create OIDC client for mailcow."""
        existing = self.find_client(realm, client_id)
        if existing:
            print(f"[OK] OIDC client '{client_id}' already exists (id={existing['id']})")
            return existing

        client_data = {
            "clientId": client_id,
            "enabled": True,
            "surrogateAuthRequired": False,
            "standardFlowEnabled": True,
            "implicitFlowEnabled": False,
            "directAccessGrantsEnabled": True,
            "serviceAccountsEnabled": True,
            "publicClient": False,
            "redirectUris": redirect_uris,
            "webOrigins": ["+"],
            "protocol": "openid-connect",
            "attributes": {
                "post.logout.redirect.uris": "+",
                "oauth2.device.authorization.grant.enabled": "false",
            },
        }

        result = self.request("POST", f"/admin/realms/{realm}/clients", client_data)
        if result and "error" not in result:
            print(f"[OK] OIDC client '{client_id}' created")
            # Get client secret from credentials
            client = self.find_client(realm, client_id)
            if client:
                creds = self.request("GET", f"/admin/realms/{realm}/clients/{client['id']}/client-secret")
                if creds:
                    return creds.get("secret", client_secret)
            return client
        elif result:
            print(f"[WARN] OIDC client: {result.get('error', 'unknown')}")
        return None

    def create_group(self, realm, group_name):
        """Create group if it doesn't exist."""
        result = self.request("GET", f"/admin/realms/{realm}/groups?search={urllib.parse.quote(group_name)}")
        if result and isinstance(result, list):
            for g in result:
                if g.get("name") == group_name:
                    print(f"[OK] Group '{group_name}' already exists")
                    return g

        group_data = {"name": group_name}
        result = self.request("POST", f"/admin/realms/{realm}/groups", group_data)
        if result and "error" not in result:
            print(f"[OK] Group '{group_name}' created")
            return True
        elif result:
            print(f"[WARN] Group '{group_name}': {result.get('error', 'unknown')}")
        return None

    def create_role(self, realm, role_name, description=""):
        """Create realm role if it doesn't exist."""
        result = self.request("GET", f"/admin/realms/{realm}/roles?name={urllib.parse.quote(role_name)}")
        if result and isinstance(result, list) and len(result) > 0:
            print(f"[OK] Role '{role_name}' already exists")
            return result[0]

        role_data = {"name": role_name, "description": description}
        result = self.request("POST", f"/admin/realms/{realm}/roles", role_data)
        if result and "error" not in result:
            print(f"[OK] Role '{role_name}' created")
            return True
        elif result:
            print(f"[WARN] Role '{role_name}': {result.get('error', 'unknown')}")
        return None

    def assign_user_to_group(self, realm, user_id, group_id):
        """Assign user to group."""
        self.request("PUT", f"/admin/realms/{realm}/users/{user_id}/groups/{group_id}", None)

    def find_user(self, realm, username):
        """Find user by username (full representation with attributes)."""
        result = self.request("GET", f"/admin/realms/{realm}/users?username={urllib.parse.quote(username)}&briefRepresentation=false")
        if result and isinstance(result, list) and len(result) > 0:
            return result[0]
        return None

    def get_user_full(self, realm, username):
        """Get full user details including attributes via GET /users/{id}."""
        user = self.find_user(realm, username)
        if not user or "id" not in user:
            return None
        return self.request("GET", f"/admin/realms/{realm}/users/{user['id']}")

    def create_user(self, realm, username, email, first_name="", last_name="",
                    attributes=None, groups=None, password=None):
        """Create user with attributes and group membership."""
        existing = self.find_user(realm, username)
        if existing:
            print(f"[OK] User '{username}' already exists (id={existing['id']})")
            # Update attributes if provided
            if attributes:
                self.update_user_attributes(realm, existing["id"], attributes)
            if password:
                self.set_user_password(realm, existing["id"], password)
            return existing

        user_data = {
            "username": username,
            "email": email,
            "firstName": first_name,
            "lastName": last_name,
            "enabled": True,
            "emailVerified": True,
        }
        if attributes:
            user_data["attributes"] = attributes

        result = self.request("POST", f"/admin/realms/{realm}/users", user_data)
        if result and "error" not in result:
            user_id = existing.get("id") if (existing := self.find_user(realm, username)) else None
            if user_id:
                if password:
                    self.set_user_password(realm, user_id, password)
                if groups:
                    self.assign_groups(realm, user_id, groups)
            print(f"[OK] User '{username}' created")
            return user_id
        elif result:
            print(f"[WARN] User '{username}': {result.get('error', 'unknown')}")
        return None

    def update_user_attributes(self, realm, user_id, attributes):
        """Update user attributes."""
        user = self.request("GET", f"/admin/realms/{realm}/users/{user_id}")
        if user and "error" not in user:
            existing_attrs = user.get("attributes", {})
            existing_attrs.update(attributes)
            user["attributes"] = existing_attrs
            self.request("PUT", f"/admin/realms/{realm}/users/{user_id}", user)

    def set_user_password(self, realm, user_id, password):
        """Set user password."""
        cred = [{"type": "password", "value": password, "temporary": False}]
        self.request("PUT", f"/admin/realms/{realm}/users/{user_id}/reset-password", cred)

    def assign_groups(self, realm, user_id, group_names):
        """Assign user to groups by name."""
        for group_name in group_names:
            groups = self.request("GET", f"/admin/realms/{realm}/groups?search={urllib.parse.quote(group_name)}")
            if groups and isinstance(groups, list):
                for g in groups:
                    if g.get("name") == group_name:
                        self.assign_user_to_group(realm, user_id, g["id"])

    def add_oidc_mapper(self, realm, client_id, mapper_name, user_attribute, claim_name):
        """Add OIDC user attribute mapper to default client scope."""
        client = self.find_client(realm, client_id)
        if not client:
            print(f"[WARN] Client '{client_id}' not found for mapper")
            return False

        # Find default client scope
        scopes = self.request("GET", f"/admin/realms/{realm}/client-scopes")
        if not scopes or not isinstance(scopes, list):
            return False

        default_scope = None
        scope_name = f"{client_id}-scope"
        for scope in scopes:
            if scope.get("name") == scope_name:
                default_scope = scope
                break

        if not default_scope:
            print(f"[WARN] Default client scope '{scope_name}' not found")
            return False

        # Check if mapper already exists
        mappers = self.request("GET", f"/admin/realms/{realm}/client-scopes/{default_scope['id']}/protocol-mappers/models")
        if mappers and isinstance(mappers, list):
            for m in mappers:
                if m.get("name") == mapper_name:
                    print(f"[OK] Mapper '{mapper_name}' already exists")
                    return True

        mapper_data = {
            "name": mapper_name,
            "protocol": "openid-connect",
            "protocolMapper": "oidc-usermodel-attribute-mapper",
            "consentRequired": False,
            "config": {
                "user.attribute": user_attribute,
                "id.token.claim": "true",
                "access.token.claim": "true",
                "introspection.token.claim": "true",
                "userinfo.token.claim": "true",
                "claim.name": claim_name,
                "jsonType.label": "String",
            },
        }
        result = self.request("POST",
                              f"/admin/realms/{realm}/client-scopes/{default_scope['id']}/protocol-mappers/models",
                              mapper_data)
        if result and "error" not in result:
            print(f"[OK] OIDC mapper '{mapper_name}' added")
            return True
        elif result:
            print(f"[WARN] Mapper '{mapper_name}': {result.get('error', 'unknown')}")
        return False

    def grant_view_users(self, realm, client_id):
        """Grant view-users role to service account of client."""
        client = self.find_client(realm, client_id)
        if not client:
            return False

        # Get service account user
        sa_user = self.find_user(realm, f"service-account-{client_id}")
        if not sa_user:
            print(f"[WARN] Service account user not found for '{client_id}'")
            return False

        # Get view-users role
        roles = self.request("GET", f"/admin/realms/{realm}/roles?name=view-users")
        if not roles or not isinstance(roles, list) or not roles:
            print("[WARN] view-users role not found")
            return False

        role = roles[0]
        # Assign role to service account
        self.request("POST",
                     f"/admin/realms/{realm}/users/{sa_user['id']}/role-mappings/realm",
                     [{"id": role["id"], "name": "view-users"}])
        print("[OK] view-users role granted to mailcow service account")
        return True


# ─── Main Setup ─────────────────────────────────────────────────────────

def run_setup():
    """Execute complete Keycloak setup."""
    print("=" * 50)
    print("Keycloak-Mailcow Bridge: Keycloak Setup")
    print("=" * 50)

    if not KEYCLOAK_ADMIN_PASSWORD or KEYCLOAK_ADMIN_PASSWORD.startswith("CHANGE_ME"):
        print("[ERROR] KEYCLOAK_ADMIN_PASSWORD not configured in .env", file=sys.stderr)
        sys.exit(1)

    kc = KeycloakClient(KEYCLOAK_URL, KEYCLOAK_ADMIN_USER, KEYCLOAK_ADMIN_PASSWORD)

    # Health check
    if not kc.health_check():
        print("[FAIL] Keycloak is not healthy. Check if it's running on port 8080.")
        sys.exit(1)
    print("[OK] Keycloak health check passed")

    # Login
    if not kc.login():
        print("[FAIL] Cannot authenticate to Keycloak")
        sys.exit(1)

    # 1. Create realm
    print("\n--- Realm Setup ---")
    kc.create_realm(REALM)

    # 2. Create OIDC client
    print("\n--- OIDC Client Setup ---")
    redirect_uris = [
        f"http://{MAILCOW_DOMAIN}/*",
        f"https://{MAILCOW_DOMAIN}/*",
        "http://localhost/*",
        "https://localhost/*",
    ]
    client_secret = kc.create_oidc_client(REALM, CLIENT_ID, redirect_uris)
    if isinstance(client_secret, str) and client_secret:
        print(f"[INFO] Client secret: {client_secret}")
        # Update .env with client secret
        env_path = os.path.join(os.path.dirname(__file__), "..", ".env")
        if os.path.exists(env_path):
            with open(env_path) as f:
                lines = f.readlines()
            updated = False
            with open(env_path, "w") as f:
                for line in lines:
                    if line.startswith("BRIDGE_CLIENT_SECRET="):
                        f.write(f"BRIDGE_CLIENT_SECRET={client_secret}\n")
                        updated = True
                    else:
                        f.write(line)
            if not updated:
                with open(env_path, "a") as f:
                    f.write(f"\nBRIDGE_CLIENT_SECRET={client_secret}\n")

    # 3. Create groups
    print("\n--- Group Setup ---")
    groups = {
        "mailcow-user": "Standard mail user",
        "mailcow-premium": "Premium mail user with higher quota",
        "mailcow-admin": "Mail admin with full access",
    }
    group_ids = {}
    for group_name, desc in groups.items():
        g = kc.create_group(REALM, group_name)
        if g:
            group_ids[group_name] = g.get("id")

    # 4. Create roles
    print("\n--- Role Setup ---")
    roles = {
        "mail-user": "Standard mail user role",
        "mail-premium": "Premium mail user role",
        "mail-admin": "Mail admin role",
    }
    for role_name, desc in roles.items():
        kc.create_role(REALM, role_name, desc)

    # 5. Add OIDC mappers
    print("\n--- OIDC Mapper Setup ---")
    kc.add_oidc_mapper(REALM, CLIENT_ID, "mailcow_template", "mailcow_template", "mailcow_template")
    if ENABLE_MAILPASSWORD:
        kc.add_oidc_mapper(REALM, CLIENT_ID, "mailcow_password", "mailcow_password", "mailcow_password")

    # 6. Grant view-users for sync/mailpassword flow
    print("\n--- Service Account Permissions ---")
    kc.grant_view_users(REALM, CLIENT_ID)

    # 7. Create test users
    print("\n--- Test User Creation ---")
    test_users = [
        {
            "username": "alice.smith",
            "email": f"alice.smith@{MAILCOW_DOMAIN}",
            "first_name": "Alice",
            "last_name": "Smith",
            "template": "default",
            "groups": ["mailcow-user"],
        },
        {
            "username": "bob.jones",
            "email": f"bob.jones@{MAILCOW_DOMAIN}",
            "first_name": "Bob",
            "last_name": "Jones",
            "template": "default",
            "groups": ["mailcow-user"],
        },
        {
            "username": "admin.user",
            "email": f"admin.user@{MAILCOW_DOMAIN}",
            "first_name": "Admin",
            "last_name": "User",
            "template": "default",
            "groups": ["mailcow-admin"],
        },
    ]

    for user_info in test_users:
        attrs = {"mailcow_template": user_info.pop("template", "default")}
        groups_list = user_info.pop("groups", ["mailcow-user"])
        kc.create_user(
            REALM,
            username=user_info["username"],
            email=user_info["email"],
            first_name=user_info.get("first_name", ""),
            last_name=user_info.get("last_name", ""),
            attributes=attrs,
            groups=groups_list,
            password=TEST_USER_PASSWORD,
        )

    print("\n" + "=" * 50)
    print("Keycloak setup complete!")
    print("=" * 50)
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Keycloak setup for Mailcow integration")
    parser.add_argument("--env", help="Path to .env file")
    args = parser.parse_args()

    if args.env:
        ENV = load_env(args.env)

    run_setup()
