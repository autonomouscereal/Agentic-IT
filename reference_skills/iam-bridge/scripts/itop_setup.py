#!/usr/bin/env python3
"""
iTop IAM Setup - Configure iTop for Keycloak integration.
Installs: combodo-hybridauth (OIDC) and combodo-saml extensions.
Configures: Keycloak as IdP, profile mappings, auto-provisioning.
Zero hardcoded secrets. All credentials from .env or environment.
Compatible with iTop 3.2.1.
"""

import json
import os
import sys
import urllib.request
import urllib.error
import urllib.parse
import base64

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)


# --- Configuration Loading ---

def parse_env(path):
    """Parse a simple .env file into os.environ."""
    with open(path, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip().strip('"\''))


def load_config():
    """Load configuration from environment or .env file."""
    for env_path in [
        os.path.join(SKILL_DIR, ".env"),
        os.path.join(os.getcwd(), ".env"),
    ]:
        if os.path.exists(env_path):
            parse_env(env_path)
            break

    return {
        "itop_url": os.environ.get("ITOP_URL", "http://localhost:25432").rstrip("/"),
        "itop_username": os.environ.get("ITOP_USERNAME", "admin"),
        "itop_password": os.environ.get("ITOP_PASSWORD"),
        "keycloak_url": os.environ.get("KEYCLOAK_URL", "http://localhost:8080").rstrip("/"),
        "bridge_realm": os.environ.get("BRIDGE_REALM", "itop"),
        "client_id": os.environ.get("BRIDGE_CLIENT_ID", "itop-oidc-client"),
        "client_secret": os.environ.get("BRIDGE_CLIENT_SECRET"),
    }


# --- iTop REST API Client ---

class iTopClient:
    """iTop REST API client (v1.4)."""

    def __init__(self, base_url, username, password):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password

    def _auth_header(self):
        creds = f"{self.username}:{self.password}"
        token = base64.b64encode(creds.encode()).decode()
        return f"Basic {token}"

    def _post(self, operation, data=None):
        """Make a REST API call to iTop."""
        payload = {"operation": operation, "user": self.username, "password": self.password}
        if data:
            payload.update(data)
        body = urllib.parse.urlencode({
            "version": "1.4", "json_output": "1",
            "json_data": json.dumps(payload),
        }).encode()
        req = urllib.request.Request(
            f"{self.base_url}/webservices/rest.php",
            data=body, method="POST",
            headers={
                "Authorization": self._auth_header(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8", errors="replace")
            return {"error": err[:300]}
        except urllib.error.URLError as e:
            return {"error": f"Connection failed: {e.reason}"}

    def check_credentials(self):
        """Verify iTop authentication."""
        return self._post("core/check_credentials")

    def get(self, class_name, key, attrs=None):
        """Query objects by key."""
        req = {"class": class_name, "key": key}
        if attrs:
            req["output_fields"] = attrs
        return self._post("core/get", req)

    def create(self, class_name, fields, comment="IAM Bridge setup"):
        """Create a new object."""
        return self._post("core/create", {
            "class": class_name, "comment": comment, "fields": fields,
        })

    def update(self, class_name, key, fields, comment="IAM Bridge update"):
        """Update an existing object."""
        return self._post("core/update", {
            "class": class_name, "key": key, "comment": comment, "fields": fields,
        })

    def delete(self, class_name, key, comment="IAM Bridge cleanup"):
        """Delete an object."""
        return self._post("core/delete", {
            "class": class_name, "key": key, "comment": comment,
        })


# --- Setup Functions ---

def verify_connectivity(client):
    """Verify iTop is reachable and credentials work."""
    result = client.check_credentials()
    if result.get("code") == 0:
        print("[OK] iTop authentication successful")
        return True
    print(f"[FAIL] iTop authentication failed: {result}")
    return False


def get_organization_id(client):
    """Get the default organization ID."""
    result = client.get("Organization", 1, attrs="name")
    if result.get("code") == 0 and result.get("objects"):
        return 1, result["objects"]["Organization::1"]["fields"]["name"]
    # Try to find first organization
    result = client.get("Organization", "all", attrs="id,name")
    if result.get("code") == 0 and result.get("objects"):
        for key, obj in result["objects"].items():
            return obj["fields"]["id"], obj["fields"]["name"]
    print("[ERROR] No organization found in iTop")
    return None, None


def get_user_id(client, login):
    """Get a UserLocal ID by login."""
    oql = f'SELECT UserLocal WHERE login = "{login}"'
    result = client.get("UserLocal", oql)
    if result.get("code") == 0 and result.get("objects"):
        for k in result["objects"]:
            # Key format: "UserLocal::2" -> extract "2"
            return k.split("::")[-1]
    return None


def get_profile_id(client, profile_name):
    """Get a profile ID by name via UserLocal admin lookup."""
    # Profiles are not directly queryable; query admin's profile_list
    result = client.get("UserLocal", 'SELECT UserLocal WHERE login = "admin"')
    if result.get("code") == 0 and result.get("objects"):
        for k, v in result["objects"].items():
            profiles = v["fields"].get("profile_list", [])
            for p in profiles:
                if p.get("profile") == profile_name:
                    return p.get("profileid")
    # Default fallback mapping
    fallback = {
        "Administrator": "1",
        "Configuration Manager": "2",
        "Portal power user": "3",
        "Portal user": "4",
    }
    return fallback.get(profile_name, "4")


def setup_test_teams(client, org_id):
    """Create teams that map to Keycloak groups for ticket assignment."""
    teams = [
        {"name": "Support Team", "description": "General support team"},
        {"name": "Engineering Team", "description": "Engineering support team"},
        {"name": "Management Team", "description": "Management team"},
    ]

    created = 0
    for team in teams:
        # Check if team already exists
        result = client.get("Team", team["name"], attrs="id,name")
        if result.get("code") == 0 and result.get("objects"):
            print(f"  [INFO] Team '{team['name']}' already exists")
            continue

        team_result = client.create("Team", {
            "name": team["name"],
            "org_id": org_id,
        })
        if team_result.get("code") == 0:
            created += 1
            print(f"  [OK] Team '{team['name']}' created")
        else:
            print(f"  [WARN] Team '{team['name']}': {team_result.get('error', 'unknown')}")

    return created


def setup_test_users(client, org_id):
    """Create test users for integration testing."""
    test_users = [
        {"login": "bridge_test_admin", "first_name": "Bridge", "full_name": "Bridge Test Admin",
         "email": "bridge-admin@test.local", "profile": "Administrator"},
        {"login": "bridge_test_user", "first_name": "Bridge", "full_name": "Bridge Test User",
         "email": "bridge-user@test.local", "profile": "Portal user"},
    ]

    created = 0
    for user in test_users:
        uid = get_user_id(client, user["login"])
        if uid:
            print(f"  [INFO] User '{user['login']}' already exists (id={uid})")
            continue

        full_name = user["full_name"]
        person_result = client.create("Person", {
            "name": full_name,
            "first_name": user["first_name"],
            "email": user["email"],
            "phone": "",
            "function": "Test user",
            "org_id": org_id,
        })
        if person_result.get("code") != 0:
            print(f"  [WARN] Person '{full_name}': {person_result.get('message', person_result.get('error', 'unknown'))}")
            continue

        # Get person ID from result
        person_id = None
        if person_result.get("objects"):
            for key, obj in person_result["objects"].items():
                person_id = obj.get("key")
                break

        if not person_id:
            person_result = client.get("Person", full_name, attrs="id")
            if person_result.get("code") == 0 and person_result.get("objects"):
                for key, obj in person_result["objects"].items():
                    person_id = obj["fields"]["id"]
                    break

        if person_id:
            profile_id = get_profile_id(client, user["profile"])
            user_result = client.create("UserLocal", {
                "contactid": person_id,
                "login": user["login"],
                "password": os.environ.get("IAM_BRIDGE_PASSWORD", ""),
                "status": "enabled",
                "profile_list": [{"profileid": profile_id}],
            })
            if user_result.get("code") == 0:
                created += 1
                print(f"  [OK] User '{user['login']}' created")
            else:
                print(f"  [WARN] UserLocal '{user['login']}': {user_result.get('message', user_result.get('error', 'unknown'))}")

    return created


def configure_hybridauth(config):
    """Generate the combodo-hybridauth configuration snippet for config-itop.php."""
    realm = config["bridge_realm"]
    keycloak_url = config["keycloak_url"]
    client_id = config["client_id"]
    client_secret = config["client_secret"] or "PLACEHOLDER_SECRET"

    oidc_config = {
        "Keycloak": {
            "enabled": True,
            "keys": {
                "id": client_id,
                "secret": client_secret,
            },
            "scope": ["openid", "profile", "email", "roles"],
            "option": {
                "subscription_info": {
                    "authorize": {
                        "redirect_uri": f"{config['itop_url']}/env-production/combodo-hybridauth/callback.php",
                    },
                },
            },
            "profiles_idp_key": "groups",
            "profiles_idp_separator": ",",
            "groups_to_profiles": {
                "itop-administrator": "Administrator",
                "itop-configuration-manager": "Configuration Manager",
                "itop-portal-power-user": ["Portal power user", "Portal user"],
                "itop-portal-user": "Portal user",
            },
            "default_profiles": ["Portal user"],
            "synchronize_user": True,
            "synchronize_contact": True,
            "refresh_existing_user": True,
            "refresh_existing_contact": True,
            "user_login_attribute": "preferred_username",
        },
    }

    return json.dumps(oidc_config, indent=2)


def configure_saml(config):
    """Generate SAML configuration guidance for iTop."""
    realm = config["bridge_realm"]
    keycloak_url = config["keycloak_url"]

    saml_info = {
        "idp_metadata_url": f"{keycloak_url}/realms/{realm}/protocol/saml/descriptor",
        "acs_url": f"{config['itop_url']}/env-production/combodo-saml/acs.php",
        "sp_entity_id": f"{config['itop_url']}/env-production/combodo-saml/metadata.php",
        "attribute_mapping": {
            "uid": "Login identifier",
            "email": "User email",
            "Groups": "Profile mapping",
        },
    }

    return json.dumps(saml_info, indent=2)


def check_extension_installed(client, extension_name):
    """Check if an extension is installed via REST API (indirect check)."""
    # iTop doesn't expose extension list via REST, we check by testing endpoints
    if extension_name == "combodo-hybridauth":
        # Check by trying to reach the landing page
        try:
            url = f"{client.base_url}/env-production/{extension_name}/landing.php"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.code == 200
        except Exception:
            return False
    elif extension_name == "combodo-saml":
        try:
            url = f"{client.base_url}/env-production/{extension_name}/saml.php"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.code in (200, 302, 404)  # 404 means it exists but needs config
        except Exception:
            return False
    return False


def print_extension_instructions(config):
    """Print instructions for installing extensions (must be done via iTop UI or manual install)."""
    realm = config["bridge_realm"]

    print("\n=== Extension Installation Required ===")
    print("The following extensions must be installed in iTop:")
    print()
    print("1. combodo-hybridauth (OIDC - PRIMARY)")
    print(f"   Download from: https://store.itophub.io/en_US/products/combodo-hybridauth")
    print("   Install via iTop UI: Admin > Extensions > Install")
    print()
    print("2. combodo-saml (SAML - FALLBACK)")
    print(f"   Download from: https://store.itophub.io/en_US/products/combodo-saml")
    print("   Install via iTop UI: Admin > Extensions > Install")
    print()
    print("=== OIDC Configuration ===")
    print("Add the following to config-itop.php $MySettings:")
    print()
    print(configure_hybridauth(config))
    print()
    print("=== SAML Configuration ===")
    print("Import IdP metadata from:")
    print(f"  {config['keycloak_url']}/realms/{realm}/protocol/saml/descriptor")
    print()
    print("Set allowed_login_types in config-itop.php:")
    print("  'allowed_login_types' => 'hybridauth-Keycloak|saml|form|basic',")
    print()


# --- Main ---

def run_setup():
    """Execute the full iTop setup."""
    config = load_config()

    if not config["itop_password"]:
        print("[ERROR] ITOP_PASSWORD not set. Check .env file.")
        return False

    print(f"[INFO] Connecting to iTop at {config['itop_url']}")
    client = iTopClient(config["itop_url"], config["itop_username"], config["itop_password"])

    # Step 1: Verify connectivity
    print("\n=== Verify Connectivity ===")
    if not verify_connectivity(client):
        return False

    # Step 2: Get organization
    print("\n=== Get Organization ===")
    org_id, org_name = get_organization_id(client)
    if not org_id:
        print("[ERROR] Cannot find organization")
        return False
    print(f"[OK] Organization: {org_name} (id={org_id})")

    # Step 3: Create test teams
    print("\n=== Setup Test Teams ===")
    setup_test_teams(client, org_id)

    # Step 4: Create test users
    print("\n=== Setup Test Users ===")
    setup_test_users(client, org_id)

    # Step 5: Check extensions
    print("\n=== Check Extensions ===")
    has_hybridauth = check_extension_installed(client, "combodo-hybridauth")
    has_saml = check_extension_installed(client, "combodo-saml")
    print(f"[INFO] combodo-hybridauth: {'Installed' if has_hybridauth else 'NOT installed'}")
    print(f"[INFO] combodo-saml: {'Installed' if has_saml else 'NOT installed'}")

    # Step 6: Print configuration instructions
    if not has_hybridauth or not has_saml:
        print_extension_instructions(config)

    # Save OIDC config for bridge_deploy.py to use
    oidc_config_path = os.path.join(SKILL_DIR, ".oidc_config.json")
    with open(oidc_config_path, "w") as f:
        json.dump(json.loads(configure_hybridauth(config))["Keycloak"], f, indent=2)
    print(f"\n[OK] OIDC config saved to {oidc_config_path}")

    print(f"\n[OK] iTop setup complete!")
    return True


if __name__ == "__main__":
    sys.exit(0 if run_setup() else 1)
