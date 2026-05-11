#!/usr/bin/env python3
"""
Keycloak IAM Setup - Configure Keycloak for iTop integration.
Creates: itop realm, OIDC client, SAML SP, profile-mapped groups, roles, mappers.
Zero hardcoded secrets. All credentials from .env or environment.
Compatible with Keycloak 26.x (tested on 26.6.0).
"""

import json
import os
import secrets
import ssl
import sys
import urllib.request
import urllib.error

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)

# --- SSL Context ---
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

# --- iTop Profile Mappings ---
PROFILE_GROUPS = [
    {"name": "itop-administrator", "description": "Maps to iTop Administrator profile"},
    {"name": "itop-configuration-manager", "description": "Maps to iTop Configuration Manager"},
    {"name": "itop-portal-power-user", "description": "Maps to iTop Portal Power User"},
    {"name": "itop-portal-user", "description": "Maps to iTop Portal User"},
    {"name": "itop-support-team", "description": "Support team for ticket assignment"},
]

PROFILE_ROLES = [
    {"name": "itop.read", "description": "Read access to iTop via Keycloak"},
    {"name": "itop.write", "description": "Write access to iTop via Keycloak"},
    {"name": "itop.admin", "description": "Full administrative access to iTop via Keycloak"},
]


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
        "keycloak_url": os.environ.get("KEYCLOAK_URL", "http://localhost:8080").rstrip("/"),
        "keycloak_admin": os.environ.get("KEYCLOAK_ADMIN_USER", "admin"),
        "keycloak_password": os.environ.get("KEYCLOAK_ADMIN_PASSWORD"),
        "bridge_realm": os.environ.get("BRIDGE_REALM", "itop"),
        "client_id": os.environ.get("BRIDGE_CLIENT_ID", "itop-oidc-client"),
    }


# --- Keycloak API Helpers ---

def api_call(method, endpoint, base_url, token, data=None):
    """Make an authenticated API call to Keycloak."""
    url = f"{base_url}{endpoint}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    body = json.dumps(data).encode("utf-8") if data is not None else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=30) as resp:
            resp_text = resp.read().decode("utf-8")
            return resp.code, json.loads(resp_text) if resp_text else None
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        return e.code, json.loads(err_body) if err_body else {"error": str(e)}
    except urllib.error.URLError as e:
        return 0, {"error": f"Connection failed: {e.reason}"}


def get_token(base_url, username, password):
    """Obtain admin bearer token."""
    endpoint = f"/realms/master/protocol/openid-connect/token"
    data = urllib.parse.urlencode({
        "username": username, "password": password,
        "grant_type": "password", "client_id": "admin-cli",
    }).encode("utf-8")
    req = urllib.request.Request(f"{base_url}{endpoint}", data=data, method="POST",
                                headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))["access_token"]
    except urllib.error.HTTPError as e:
        print(f"[AUTH FAILED] {e.read().decode('utf-8', errors='replace')}")
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"[CONNECTION FAILED] Cannot reach Keycloak at {base_url}: {e.reason}")
        sys.exit(1)


def get_realm_token(base_url, realm, client_id, client_secret=None):
    """Get a service account token for a specific realm/client."""
    endpoint = f"/realms/{realm}/protocol/openid-connect/token"
    data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret or "",
    }).encode("utf-8")
    req = urllib.request.Request(f"{base_url}{endpoint}", data=data, method="POST",
                                headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))["access_token"]
    except Exception:
        return None


# --- Setup Functions ---

def setup_realm(token, base_url, realm_name):
    """Create the integration realm if it doesn't exist."""
    code, realms = api_call("GET", "/admin/realms", base_url, token)
    realm_list = []
    if code == 200 and realms:
        realm_list = [r.get("realm", r) if isinstance(r, dict) else r for r in realms]

    if realm_name in realm_list:
        print(f"[OK] Realm '{realm_name}' already exists")
        return True

    realm_data = {
        "realm": realm_name,
        "enabled": True,
        "loginWithEmailAllowed": False,
        "duplicateEmailsAllowed": False,
        "resetPasswordAllowed": False,
        "editUsernameAllowed": False,
    }
    code, result = api_call("POST", "/admin/realms", base_url, token, realm_data)
    if code == 201:
        print(f"[OK] Realm '{realm_name}' created")
        return True
    print(f"[WARN] Realm creation: {code} {result}")
    return False


def find_client_uuid(token, base_url, realm_name, client_id):
    """Look up a client's UUID by its clientId."""
    endpoint = f"/admin/realms/{realm_name}/clients?clientId={urllib.parse.quote(client_id)}"
    code, result = api_call("GET", endpoint, base_url, token)
    if code == 200 and result:
        for client in result:
            if isinstance(client, dict) and client.get("clientId") == client_id:
                return client.get("id")
    return None


def setup_oidc_client(token, base_url, realm_name, client_id, redirect_uri):
    """Create the OIDC client for iTop hybridauth integration (idempotent)."""
    # Check if client already exists
    existing_uuid = find_client_uuid(token, base_url, realm_name, client_id)
    if existing_uuid:
        print(f"[OK] OIDC client '{client_id}' already exists")
        # Read existing secret from .env
        existing_secret = os.environ.get("BRIDGE_CLIENT_SECRET", "")
        if existing_secret:
            return existing_uuid, existing_secret
        return existing_uuid, None

    client_secret = secrets.token_urlsafe(48)

    client_data = {
        "clientId": client_id,
        "enabled": True,
        "clientAuthenticatorType": "client-secret",
        "secret": client_secret,
        "redirectUris": [redirect_uri, f"{redirect_uri}/*"],
        "webOrigins": ["+"],
        "protocol": "openid-connect",
        "publicClient": False,
        "standardFlowEnabled": True,
        "implicitFlowEnabled": False,
        "directAccessGrantsEnabled": True,
        "serviceAccountsEnabled": True,
        "attributes": {
            "post.logout.redirect.uris": "+",
        },
    }

    endpoint = f"/admin/realms/{realm_name}/clients"
    code, result = api_call("POST", endpoint, base_url, token, client_data)
    if code == 201:
        client_uuid = result.get("id") if result else None
        # If API returned empty body, look up the UUID
        if not client_uuid:
            client_uuid = find_client_uuid(token, base_url, realm_name, client_id)
        if client_uuid:
            print(f"[OK] OIDC client '{client_id}' created (secret stored in .env)")
            return client_uuid, client_secret
        print("[ERROR] OIDC client created but could not resolve UUID")
        return None, client_secret
    print(f"[ERROR] OIDC client creation failed: {result}")
    return None, None


def setup_saml_client(token, base_url, realm_name, client_id):
    """Create the SAML client for iTop SAML fallback (idempotent)."""
    saml_client_id = "itop-saml-client"
    # Check if client already exists
    existing_uuid = find_client_uuid(token, base_url, realm_name, saml_client_id)
    if existing_uuid:
        print(f"[OK] SAML client '{saml_client_id}' already exists")
        return existing_uuid

    saml_client_data = {
        "clientId": saml_client_id,
        "enabled": True,
        "protocol": "saml",
        "publicClient": True,
        "attributes": {
            "saml.assertion.consume.bs": "false",
            "saml.client.signature": "false",
            "saml.signature.algorithm": "RSA_SHA256",
            "saml_force_post_binding": "true",
        },
    }

    endpoint = f"/admin/realms/{realm_name}/clients"
    code, result = api_call("POST", endpoint, base_url, token, saml_client_data)
    if code == 201:
        client_uuid = result.get("id") if result else None
        if not client_uuid:
            client_uuid = find_client_uuid(token, base_url, realm_name, saml_client_id)
        print(f"[OK] SAML client '{saml_client_id}' created")
        return client_uuid
    print(f"[WARN] SAML client creation: {code} {result}")
    return None


def setup_oidc_mappers(token, base_url, realm_name, client_uuid):
    """Create OIDC protocol mappers for group membership and user attributes."""
    mappers = [
        {
            "name": "groups-mapper",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-usermodel-realm-role-mapper",
            "consentRequired": False,
            "config": {
                "claim.name": "groups",
                "jsonType.label": "String",
                "multivalued": "true",
                "id.token.claim": "true",
                "access.token.claim": "true",
                "userinfo.token.claim": "true",
            },
        },
        {
            "name": "email-mapper",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-usersessionmodel-note-mapper",
            "consentRequired": False,
            "config": {
                "claim.name": "email",
                "jsonType.label": "String",
                "user.session.note": "email",
                "id.token.claim": "true",
                "access.token.claim": "true",
                "userinfo.token.claim": "true",
            },
        },
        {
            "name": "firstName-mapper",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-usermodel-attribute-mapper",
            "consentRequired": False,
            "config": {
                "claim.name": "given_name",
                "jsonType.label": "String",
                "user.attribute": "firstName",
                "id.token.claim": "true",
                "access.token.claim": "true",
                "userinfo.token.claim": "true",
            },
        },
        {
            "name": "lastName-mapper",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-usermodel-attribute-mapper",
            "consentRequired": False,
            "config": {
                "claim.name": "family_name",
                "jsonType.label": "String",
                "user.attribute": "lastName",
                "id.token.claim": "true",
                "access.token.claim": "true",
                "userinfo.token.claim": "true",
            },
        },
    ]

    endpoint = f"/admin/realms/{realm_name}/clients/{client_uuid}/protocol-mappers/models"
    created = 0
    for mapper in mappers:
        code, result = api_call("POST", endpoint, base_url, token, mapper)
        if code == 201:
            created += 1
    print(f"[OK] OIDC mappers created: {created}/{len(mappers)}")
    return created


def setup_saml_mappers(token, base_url, realm_name, saml_client_uuid):
    """Create SAML attribute mappers for group and user attributes."""
    if not saml_client_uuid:
        print("[SKIP] SAML mappers skipped (no SAML client)")
        return 0

    mappers = [
        {
            "name": "saml-groups",
            "protocol": "saml",
            "protocolMapper": "saml-role-list-mapper",
            "consentRequired": False,
            "config": {
                "singleRoleAttribute": "true",
                "roleAttributeNodeName": "Attribute",
                "roleAttributeName": "Groups",
                "roleAttributeNodeContents": "Role",
            },
        },
        {
            "name": "saml-email",
            "protocol": "saml",
            "protocolMapper": "saml-user-property-mapper",
            "consentRequired": False,
            "config": {
                "attribute.name": "Email",
                "user.attribute": "email",
                "friendlyname": "Email",
            },
        },
    ]

    endpoint = f"/admin/realms/{realm_name}/clients/{saml_client_uuid}/protocol-mappers/models"
    created = 0
    for mapper in mappers:
        code, result = api_call("POST", endpoint, base_url, token, mapper)
        if code == 201:
            created += 1
    print(f"[OK] SAML mappers created: {created}/{len(mappers)}")
    return created


def setup_groups(token, base_url, realm_name, groups):
    """Create groups mapped to iTop profiles."""
    created = 0
    for group_def in groups:
        group_data = {
            "name": group_def["name"],
            "path": f"/{group_def['name']}",
        }
        code, result = api_call("POST", f"/admin/realms/{realm_name}/groups",
                               base_url, token, group_data)
        if code == 201:
            created += 1
            print(f"  [OK] Group '{group_def['name']}' created")
        else:
            print(f"  [INFO] Group '{group_def['name']}': {code} (may already exist)")
    return created


def setup_roles(token, base_url, realm_name, roles):
    """Create realm roles for iTop access control."""
    created = 0
    for role_def in roles:
        role_data = {
            "name": role_def["name"],
            "description": role_def["description"],
        }
        code, result = api_call("POST", f"/admin/realms/{realm_name}/roles",
                               base_url, token, role_data)
        if code == 201:
            created += 1
            print(f"  [OK] Role '{role_def['name']}' created")
        else:
            print(f"  [INFO] Role '{role_def['name']}': {code} (may already exist)")
    return created


def write_client_secret(skill_dir, client_secret):
    """Write the OIDC client secret to .env file securely."""
    env_path = os.path.join(skill_dir, ".env")
    if os.path.exists(env_path):
        parse_env(env_path)

    os.environ["BRIDGE_CLIENT_SECRET"] = client_secret

    content = f"""# IAM Bridge - Auto-generated secrets
# DO NOT commit to version control

BRIDGE_CLIENT_SECRET={client_secret}
"""
    with open(env_path, "a") as f:
        f.write(content)
    os.chmod(env_path, 0o600)
    print(f"[OK] Client secret stored in .env")


# --- Main ---

def run_setup():
    """Execute the full Keycloak setup."""
    config = load_config()

    if not config["keycloak_password"]:
        print("[ERROR] KEYCLOAK_ADMIN_PASSWORD not set. Check .env file.")
        return False

    print(f"[INFO] Connecting to Keycloak at {config['keycloak_url']}")
    token = get_token(config["keycloak_url"], config["keycloak_admin"], config["keycloak_password"])
    print(f"[AUTH] Connected as {config['keycloak_admin']}")

    realm = config["bridge_realm"]
    client_id = config["client_id"]
    redirect_uri = os.environ.get("ITOP_URL", "http://localhost:25432")

    # Step 1: Create realm
    print(f"\n=== Setup Realm: {realm} ===")
    setup_realm(token, config["keycloak_url"], realm)

    # Step 2: Create OIDC client
    print(f"\n=== Setup OIDC Client ===")
    client_uuid, client_secret = setup_oidc_client(
        token, config["keycloak_url"], realm, client_id, redirect_uri
    )

    if client_secret:
        write_client_secret(SKILL_DIR, client_secret)

    # Step 3: Create SAML client
    print(f"\n=== Setup SAML Client ===")
    saml_client_uuid = setup_saml_client(token, config["keycloak_url"], realm, client_id)

    # Step 4: Create OIDC mappers
    print(f"\n=== Setup OIDC Mappers ===")
    if client_uuid:
        setup_oidc_mappers(token, config["keycloak_url"], realm, client_uuid)

    # Step 5: Create SAML mappers
    print(f"\n=== Setup SAML Mappers ===")
    setup_saml_mappers(token, config["keycloak_url"], realm, saml_client_uuid)

    # Step 6: Create groups
    print(f"\n=== Setup Profile Groups ===")
    setup_groups(token, config["keycloak_url"], realm, PROFILE_GROUPS)

    # Step 7: Create roles
    print(f"\n=== Setup Access Roles ===")
    setup_roles(token, config["keycloak_url"], realm, PROFILE_ROLES)

    print(f"\n[OK] Keycloak setup complete!")
    return True


if __name__ == "__main__":
    import urllib.parse
    sys.exit(0 if run_setup() else 1)
