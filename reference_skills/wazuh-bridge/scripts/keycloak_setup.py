#!/usr/bin/env python3
"""
Keycloak Wazuh Setup - Configure Keycloak for Wazuh IAM integration.
Creates: wazuh realm, OIDC client, RBAC-mapped groups, roles, mappers.
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
import urllib.parse

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SKILL_DIR = os.path.dirname(SCRIPT_DIR)

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

PROFILE_GROUPS = [
    {"name": "wazuh-administrator", "description": "Maps to Wazuh administrator role"},
    {"name": "wazuh-security-analyst", "description": "Maps to Wazuh readonly role"},
    {"name": "wazuh-agent-admin", "description": "Maps to Wazuh agents_admin role"},
    {"name": "wazuh-cluster-admin", "description": "Maps to Wazuh cluster_admin role"},
    {"name": "wazuh-user-admin", "description": "Maps to Wazuh users_admin role"},
]

ACCESS_ROLES = [
    {"name": "wazuh.read", "description": "Read access to Wazuh via Keycloak"},
    {"name": "wazuh.write", "description": "Write access to Wazuh via Keycloak"},
    {"name": "wazuh.admin", "description": "Full administrative access to Wazuh via Keycloak"},
]


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
    }


def api_call(method, endpoint, base_url, token, data=None):
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


def get_realm_token(base_url, realm, client_id, client_secret):
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


def setup_realm(token, base_url, realm_name):
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
    }
    code, result = api_call("POST", "/admin/realms", base_url, token, realm_data)
    if code == 201:
        print(f"[OK] Realm '{realm_name}' created")
        return True
    print(f"[WARN] Realm creation: {code} {result}")
    return False


def find_client_uuid(token, base_url, realm_name, client_id):
    endpoint = f"/admin/realms/{realm_name}/clients?clientId={urllib.parse.quote(client_id)}"
    code, result = api_call("GET", endpoint, base_url, token)
    if code == 200 and result:
        for client in result:
            if isinstance(client, dict) and client.get("clientId") == client_id:
                return client.get("id")
    return None


def setup_oidc_client(token, base_url, realm_name, client_id):
    existing_uuid = find_client_uuid(token, base_url, realm_name, client_id)
    if existing_uuid:
        print(f"[OK] OIDC client '{client_id}' already exists")
        existing_secret = os.environ.get("WAZUH_CLIENT_SECRET", "")
        if existing_secret:
            return existing_uuid, existing_secret
        return existing_uuid, None

    client_secret = secrets.token_urlsafe(48)
    wazuh_url = os.environ.get("WAZUH_URL", "https://127.0.0.1:26500").rstrip("/")
    client_data = {
        "clientId": client_id,
        "enabled": True,
        "clientAuthenticatorType": "client-secret",
        "secret": client_secret,
        "redirectUris": [f"{wazuh_url}/*"],
        "webOrigins": ["+"],
        "protocol": "openid-connect",
        "publicClient": False,
        "standardFlowEnabled": True,
        "directAccessGrantsEnabled": True,
        "serviceAccountsEnabled": True,
        "attributes": {"post.logout.redirect.uris": "+"},
    }
    endpoint = f"/admin/realms/{realm_name}/clients"
    code, result = api_call("POST", endpoint, base_url, token, client_data)
    if code == 201:
        client_uuid = result.get("id") if result else None
        if not client_uuid:
            client_uuid = find_client_uuid(token, base_url, realm_name, client_id)
        print(f"[OK] OIDC client '{client_id}' created")
        return client_uuid, client_secret
    print(f"[ERROR] OIDC client creation failed: {result}")
    return None, None


def setup_oidc_mappers(token, base_url, realm_name, client_uuid):
    if not client_uuid:
        print("[SKIP] OIDC mappers skipped (no client)")
        return 0
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
            "name": "username-mapper",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-usersessionmodel-note-mapper",
            "consentRequired": False,
            "config": {
                "claim.name": "preferred_username",
                "jsonType.label": "String",
                "user.session.note": "username",
                "id.token.claim": "true",
                "access.token.claim": "true",
                "userinfo.token.claim": "true",
            },
        },
    ]
    endpoint = f"/admin/realms/{realm_name}/clients/{client_uuid}/protocol-mappers/models"
    created = 0
    for mapper in mappers:
        code, _ = api_call("POST", endpoint, base_url, token, mapper)
        if code == 201:
            created += 1
    print(f"[OK] OIDC mappers created: {created}/{len(mappers)}")
    return created


def setup_groups(token, base_url, realm_name, groups):
    created = 0
    for group_def in groups:
        group_data = {"name": group_def["name"], "path": f"/{group_def['name']}"}
        code, _ = api_call("POST", f"/admin/realms/{realm_name}/groups",
                          base_url, token, group_data)
        if code == 201:
            created += 1
            print(f"  [OK] Group '{group_def['name']}' created")
        else:
            print(f"  [INFO] Group '{group_def['name']}': {code} (may already exist)")
    return created


def setup_roles(token, base_url, realm_name, roles):
    created = 0
    for role_def in roles:
        role_data = {"name": role_def["name"], "description": role_def["description"]}
        code, _ = api_call("POST", f"/admin/realms/{realm_name}/roles",
                          base_url, token, role_data)
        if code == 201:
            created += 1
            print(f"  [OK] Role '{role_def['name']}' created")
        else:
            print(f"  [INFO] Role '{role_def['name']}': {code} (may already exist)")
    return created


def write_client_secret(skill_dir, client_secret):
    env_path = os.path.join(skill_dir, ".env")
    if os.path.exists(env_path):
        parse_env(env_path)
    os.environ["WAZUH_CLIENT_SECRET"] = client_secret
    content = f"\nWAZUH_CLIENT_SECRET={client_secret}\n"
    with open(env_path, "a") as f:
        f.write(content)
    try:
        os.chmod(env_path, 0o600)
    except Exception:
        pass
    print(f"[OK] Client secret stored in .env")


def run_setup():
    config = load_config()
    if not config["keycloak_password"]:
        print("[ERROR] KEYCLOAK_ADMIN_PASSWORD not set. Check .env file.")
        return False

    print(f"[INFO] Connecting to Keycloak at {config['keycloak_url']}")
    token = get_token(config["keycloak_url"], config["keycloak_admin"], config["keycloak_password"])
    print(f"[AUTH] Connected as {config['keycloak_admin']}")

    realm = config["bridge_realm"]
    client_id = "wazuh-oidc-client"

    print(f"\n=== Setup Realm: {realm} ===")
    setup_realm(token, config["keycloak_url"], realm)

    print(f"\n=== Setup OIDC Client ===")
    client_uuid, client_secret = setup_oidc_client(
        token, config["keycloak_url"], realm, client_id,
    )
    if client_secret:
        write_client_secret(SKILL_DIR, client_secret)

    print(f"\n=== Setup OIDC Mappers ===")
    setup_oidc_mappers(token, config["keycloak_url"], realm, client_uuid)

    print(f"\n=== Setup RBAC Groups ===")
    setup_groups(token, config["keycloak_url"], realm, PROFILE_GROUPS)

    print(f"\n=== Setup Access Roles ===")
    setup_roles(token, config["keycloak_url"], realm, ACCESS_ROLES)

    # Verify OIDC token works
    if client_secret:
        print(f"\n=== Verify OIDC Token ===")
        svc_token = get_realm_token(
            config["keycloak_url"], realm, client_id, client_secret,
        )
        if svc_token:
            print("[OK] OIDC service account token valid")
        else:
            print("[WARN] OIDC service account token failed")

    print(f"\n[OK] Keycloak Wazuh setup complete!")
    return True


if __name__ == "__main__":
    sys.exit(0 if run_setup() else 1)
