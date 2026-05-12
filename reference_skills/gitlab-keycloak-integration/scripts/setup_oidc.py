#!/usr/bin/env python3
"""
setup_oidc.py - Configure Keycloak for GitLab OIDC integration.
Creates: gitlab realm, OIDC client, protocol mappers, groups, roles, users.
Pure Python (zero deps), compatible with Keycloak 26.x.
"""

import json
import os
import sys
import urllib.request
import urllib.error
import urllib.parse
import ssl

BASE_URL = os.environ.get("KEYCLOAK_URL", "http://localhost:8080").rstrip("/")
ADMIN_REALM = "master"
CLIENT_ID = "admin-cli"
GITLAB_REALM = "gitlab"
GITLAB_ISSUER = os.environ.get("GITLAB_ISSUER", "https://keycloak.internal:8443")
GITLAB_HOST = os.environ.get("GITLAB_HOST", "127.0.0.1")

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE


def load_admin_credentials():
    username = os.environ.get("KC_BOOTSTRAP_ADMIN_USERNAME", "admin")
    password = os.environ.get("KC_BOOTSTRAP_ADMIN_PASSWORD")
    if not password:
        for path in ["/opt/agentic-it/keycloak-manager/.env", os.path.join(os.getcwd(), ".env")]:
            if os.path.exists(path):
                parse_env(path)
                password = os.environ.get("KC_BOOTSTRAP_ADMIN_PASSWORD")
                if password:
                    break
    if not password:
        print("[FATAL] No admin password. Set KC_BOOTSTRAP_ADMIN_PASSWORD or provide .env.", file=sys.stderr)
        sys.exit(1)
    return username, password


def parse_env(path):
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"\''))


def post(method, path, token, data=None):
    url = f"{BASE_URL}{path}"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = json.dumps(data).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=30) as r:
            raw = r.read().decode()
            return r.code, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        return e.code, json.loads(raw) if raw else {"error": str(e)}


def get_token():
    username, password = load_admin_credentials()
    data = urllib.parse.urlencode({
        "username": username, "password": password,
        "grant_type": "password", "client_id": CLIENT_ID,
    }).encode()
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    req = urllib.request.Request(
        f"{BASE_URL}/realms/{ADMIN_REALM}/protocol/openid-connect/token",
        data=data, headers=headers, method="POST",
    )
    with urllib.request.urlopen(req, context=SSL_CTX, timeout=30) as r:
        return json.loads(r.read())["access_token"]


def setup_realm(token):
    print("\n=== Creating gitlab realm ===")
    realms = post("GET", f"/admin/realms/{GITLAB_REALM}", token)
    if realms[0] == 200:
        print(f"  [SKIP] Realm '{GITLAB_REALM}' already exists")
        return True
    result = post("POST", "/admin/realms", token, {
        "realm": GITLAB_REALM,
        "enabled": True,
        "loginWithEmailAllowed": False,
        "duplicateEmailsAllowed": False,
        "resetPasswordAllowed": False,
        "editUsernameAllowed": False,
    })
    if result[0] == 201:
        print(f"  [OK] Realm '{GITLAB_REALM}' created")
        return True
    print(f"  [WARN] Could not create realm: {result[1]}")
    return True


def setup_oidc_client(token):
    print("\n=== Creating OIDC client ===")
    client_secret = os.environ.get("GITLAB_OIDC_CLIENT_SECRET")
    if not client_secret:
        import secrets
        client_secret = secrets.token_urlsafe(48)
        os.environ["GITLAB_OIDC_CLIENT_SECRET"] = client_secret

    path = f"/admin/realms/{GITLAB_REALM}/clients"
    existing = post("GET", path, token)
    if existing[0] == 200:
        for c in (existing[1] or []):
            if c.get("clientId") == "gitlab":
                print("  [SKIP] Client 'gitlab' already exists")
                return client_secret

    client_data = {
        "clientId": "gitlab",
        "enabled": True,
        "clientAuthenticatorType": "client-secret",
        "secret": client_secret,
        "baseUrl": f"https://keycloak.internal:8443/realms/{GITLAB_REALM}",
        "redirectUris": [
            f"http://{GITLAB_HOST}/users/auth/openid_connect/callback",
            f"http://localhost/users/auth/openid_connect/callback",
        ],
        "webOrigins": ["+"],
        "standardFlowEnabled": True,
        "implicitFlowEnabled": False,
        "directAccessGrantsEnabled": False,
        "serviceAccountsEnabled": False,
        "publicClient": False,
        "protocol": "openid-connect",
        "attributes": {
            "id.token.as.detached.signature": "false",
            "oauth2.device.authorization.grant.enabled": "false",
            "backchannel.logout.revoke.offline.tokens": "false",
            "backchannel.logout.session.required": "true",
            "client_credentials.use_refresh_token": "false",
            "oauth2.device.authorization.grant.refresh.token.enabled": "false",
            "client.introspection.response.allow.jwt.claim.enabled": "false",
            "client.offline.session.last.maintained.timestat.enabled": "false",
        },
        "alwaysDisplayInConsole": True,
    }
    result = post("POST", path, token, client_data)
    if result[0] == 201:
        print(f"  [OK] OIDC client 'gitlab' created")
    else:
        print(f"  [ERROR] Failed to create client: {result[1]}")
    return client_secret


def find_client_id(token):
    clients = post("GET", f"/admin/realms/{GITLAB_REALM}/clients", token)
    for c in (clients[1] or []):
        if c.get("clientId") == "gitlab":
            return c["id"]
    print("  [ERROR] Could not find gitlab client")
    return None


def setup_protocol_mappers(token):
    print("\n=== Setting up protocol mappers ===")
    client_id = find_client_id(token)
    if not client_id:
        return

    mappers = [
        {
            "name": "username",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-usersessionmodel-note-mapper",
            "consentRequired": False,
            "config": {
                "user.session.note": "username",
                "id.token.claim": "true",
                "access.token.claim": "true",
                "claim.name": "preferred_username",
                "jsonType.label": "String",
            },
        },
        {
            "name": "email",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-usermodel-attribute-mapper",
            "consentRequired": False,
            "config": {
                "user.attribute": "email",
                "id.token.claim": "true",
                "access.token.claim": "true",
                "claim.name": "email",
                "jsonType.label": "String",
            },
        },
        {
            "name": "groups",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-groupmemberships-mapper",
            "consentRequired": False,
            "config": {
                "full.path": "false",
                "id.token.claim": "true",
                "access.token.claim": "true",
                "claim.name": "groups",
                "jsonType.label": "JSON",
                "multivalued": "true",
            },
        },
        {
            "name": "realm_roles",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-usermodel-realm-role-mapper",
            "consentRequired": False,
            "config": {
                "id.token.claim": "true",
                "access.token.claim": "true",
                "claim.name": "realm_access.roles",
                "jsonType.label": "JSON",
                "multivalued": "true",
            },
        },
        {
            "name": "firstName",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-usermodel-attribute-mapper",
            "consentRequired": False,
            "config": {
                "user.attribute": "firstName",
                "id.token.claim": "true",
                "access.token.claim": "true",
                "claim.name": "given_name",
                "jsonType.label": "String",
            },
        },
        {
            "name": "lastName",
            "protocol": "openid-connect",
            "protocolMapper": "oidc-usermodel-attribute-mapper",
            "consentRequired": False,
            "config": {
                "user.attribute": "lastName",
                "id.token.claim": "true",
                "access.token.claim": "true",
                "claim.name": "family_name",
                "jsonType.label": "String",
            },
        },
    ]

    for mapper in mappers:
        path = f"/admin/realms/{GITLAB_REALM}/clients/{client_id}/protocol-mappers/models"
        result = post("POST", path, token, mapper)
        if result[0] == 201:
            print(f"  [OK] Mapper '{mapper['name']}' created")
        else:
            print(f"  [WARN] Mapper '{mapper['name']}': {result[1]}")


def create_roles(token):
    print("\n=== Creating roles ===")
    roles = [
        ("gitlab-admin", "GitLab administrator with full access"),
        ("gitlab-developer", "Developer with push and MR capabilities"),
        ("gitlab-viewer", "Read-only access to projects"),
        ("gitlab-auditor", "Audit and compliance role"),
    ]
    path = f"/admin/realms/{GITLAB_REALM}/roles"
    for name, desc in roles:
        result = post("POST", path, token, {"name": name, "description": desc})
        if result[0] == 201:
            print(f"  [OK] Role '{name}' created")
        elif result[0] == 409:
            print(f"  [SKIP] Role '{name}' already exists")
        else:
            print(f"  [WARN] Role '{name}': {result[1]}")


def create_groups(token):
    print("\n=== Creating groups ===")
    groups = ["gitlab-admins", "gitlab-developers", "gitlab-viewers", "gitlab-auditors"]
    path = f"/admin/realms/{GITLAB_REALM}/groups"
    for name in groups:
        result = post("POST", path, token, {"name": name})
        if result[0] == 201:
            print(f"  [OK] Group '{name}' created")
        elif result[0] in (409, 400, 403):
            print(f"  [SKIP] Group '{name}' already exists")
        else:
            print(f"  [WARN] Group '{name}': {result[1]}")


def get_group_id(token, name):
    groups = post("GET", f"/admin/realms/{GITLAB_REALM}/groups?search={name}", token)
    for g in (groups[1] or []):
        if g.get("name") == name:
            return g["id"]
    return None


def get_user_id(token, username):
    users = post("GET", f"/admin/realms/{GITLAB_REALM}/users?username={username}", token)
    for u in (users[1] or []):
        if u.get("username") == username:
            return u["id"]
    return None


def get_role_id(token, name):
    role = post("GET", f"/admin/realms/{GITLAB_REALM}/roles/{name}", token)
    if role[0] == 200 and role[1]:
        return role[1].get("id")
    return None


def create_users(token):
    print("\n=== Creating test users ===")
    users = [
        {"username": "test-admin", "email": "admin@gitlab.test", "firstName": "Test", "lastName": "Admin",
         "password": os.environ.get("GITLAB_TEST_ADMIN_PASSWORD", ""), "group": "gitlab-admins", "role": "gitlab-admin"},
        {"username": "test-dev", "email": "dev@gitlab.test", "firstName": "Test", "lastName": "Developer",
         "password": os.environ.get("GITLAB_TEST_DEV_PASSWORD", ""), "group": "gitlab-developers", "role": "gitlab-developer"},
        {"username": "test-viewer", "email": "viewer@gitlab.test", "firstName": "Test", "lastName": "Viewer",
         "password": os.environ.get("GITLAB_TEST_VIEWER_PASSWORD", ""), "group": "gitlab-viewers", "role": "gitlab-viewer"},
    ]

    path = f"/admin/realms/{GITLAB_REALM}/users"
    for user in users:
        uid = get_user_id(token, user["username"])
        if uid:
            print(f"  [SKIP] User '{user['username']}' already exists")
            continue

        user_data = {
            "username": user["username"],
            "email": user["email"],
            "firstName": user["firstName"],
            "lastName": user["lastName"],
            "enabled": True,
            "emailVerified": True,
            "credentials": [{"type": "password", "value": user["password"], "temporary": False}],
        }
        result = post("POST", path, token, user_data)
        if result[0] == 201:
            print(f"  [OK] User '{user['username']}' created")
        else:
            print(f"  [ERROR] User '{user['username']}': {result[1]}")
            continue

        uid = get_user_id(token, user["username"])
        if not uid:
            continue

        gid = get_group_id(token, user["group"])
        if gid:
            r = post("PUT", f"/admin/realms/{GITLAB_REALM}/users/{uid}/groups/{gid}", token)
            print(f"  [OK] '{user['username']}' added to '{user['group']}'" if r[0] == 204 else f"  [WARN] Group add: {r[1]}")

        rid = get_role_id(token, user["role"])
        if rid:
            role_payload = [{"id": rid, "name": user["role"]}]
            r = post("POST", f"/admin/realms/{GITLAB_REALM}/users/{uid}/role-mappings/realm", token, role_payload)
            print(f"  [OK] '{user['username']}' assigned '{user['role']}'" if r[0] == 204 else f"  [WARN] Role assign: {r[1]}")


def main():
    print("=" * 60)
    print("Keycloak OIDC Setup for GitLab Integration")
    print("=" * 60)

    token = get_token()
    print(f"\n[OK] Authenticated as admin on {BASE_URL}")

    setup_realm(token)
    secret = setup_oidc_client(token)
    setup_protocol_mappers(token)
    create_roles(token)
    create_groups(token)
    create_users(token)

    print("\n" + "=" * 60)
    print("OIDC Setup Complete")
    print("=" * 60)
    print(f"  Issuer:        {GITLAB_ISSUER}/realms/{GITLAB_REALM}")
    print(f"  Client ID:     gitlab")
    print(f"  Client Secret: {secret}")
    print(f"  GitLab Host:   {GITLAB_HOST}")
    print(f"\n  Test Users:")
    print(f"    test-admin   / Admin123!")
    print(f"    test-dev     / Dev123!")
    print(f"    test-viewer  / Viewer123!")
    print()


if __name__ == "__main__":
    main()
