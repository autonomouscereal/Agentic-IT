#!/usr/bin/env python3
"""
Keycloak Admin CLI - Complete CRUD operations for Keycloak Admin REST API.
Manages: realms, users, groups, roles, role-mappings.
Zero hardcoded secrets. Credentials from .env file or environment.
Compatible with Keycloak 26.x (tested on 26.6.0).
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
import ssl

# --- Configuration ---
DEFAULT_BASE_URL = "http://localhost:8080"
REALM = "master"
CLIENT_ID = "admin-cli"
ADMIN_USERNAME_ENV = "KC_BOOTSTRAP_ADMIN_USERNAME"
ADMIN_PASSWORD_ENV = "KC_BOOTSTRAP_ADMIN_PASSWORD"

# --- SSL Context (disable cert verification for self-signed/internal) ---
SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE


def load_credentials():
    """Load admin credentials from environment or .env file."""
    username = os.environ.get(ADMIN_USERNAME_ENV, "admin")
    password = os.environ.get(ADMIN_PASSWORD_ENV)

    if not password:
        # Try .env file in script directory, then cwd
        for env_path in [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"),
            os.path.join(os.getcwd(), ".env"),
        ]:
            if os.path.exists(env_path):
                parse_env(env_path)
                password = os.environ.get(ADMIN_PASSWORD_ENV)
                break

    if not password:
        print("[ERROR] No admin password found. Set KC_BOOTSTRAP_ADMIN_PASSWORD env var or create .env file.", file=sys.stderr)
        sys.exit(1)

    return username, password


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


def api_call(method, endpoint, base_url, token, data=None):
    """Make an authenticated API call to Keycloak."""
    url = f"{base_url}{endpoint}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")

    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=30) as resp:
            resp_data = resp.read().decode("utf-8")
            return resp.code, json.loads(resp_data) if resp_data else None
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        return e.code, json.loads(err_body) if err_body else {"error": str(e)}
    except urllib.error.URLError as e:
        return 0, {"error": f"Connection failed: {e.reason}"}


def get_token(base_url, username, password):
    """Obtain admin bearer token via password grant."""
    endpoint = f"/realms/{REALM}/protocol/openid-connect/token"
    data = {
        "username": username,
        "password": password,
        "grant_type": "password",
        "client_id": CLIENT_ID,
    }
    # URL-encode form data
    body = urllib.parse.urlencode(data).encode("utf-8")
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    req = urllib.request.Request(
        f"{base_url}{endpoint}", data=body, headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))["access_token"]
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        print(f"[AUTH FAILED] {err}", file=sys.stderr)
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"[CONNECTION FAILED] Cannot reach Keycloak at {base_url}: {e.reason}", file=sys.stderr)
        sys.exit(1)


# --- USER OPERATIONS ---

def create_user(token, base_url, realm, username, email=None, first_name=None,
                last_name=None, password=None, email_verified=True, enabled=True):
    """Create a new user."""
    user_data = {
        "username": username,
        "enabled": enabled,
        "emailVerified": email_verified,
    }
    if email:
        user_data["email"] = email
    if first_name:
        user_data["firstName"] = first_name
    if last_name:
        user_data["lastName"] = last_name

    code, result = api_call("POST", f"/admin/realms/{realm}/users", base_url, token, user_data)
    if code in (201, 204):
        user_id = result.get("id") if result else "created"
        print(f"[OK] User '{username}' created")

        # Set password if provided
        if password:
            set_user_password(token, base_url, realm, username, password)

        # Get user ID for return
        users = list_users(token, base_url, realm, username=username)
        return users[0] if users else {"username": username}
    else:
        print(f"[ERROR] Failed to create user: {result}")
        return None


def list_users(token, base_url, realm, username=None, email=None, max_results=100):
    """List/search users."""
    endpoint = f"/admin/realms/{realm}/users?max={max_results}"
    if username:
        endpoint += f"&username={username}"
    if email:
        endpoint += f"&email={email}"

    code, result = api_call("GET", endpoint, base_url, token)
    if code == 200:
        return result if result else []
    else:
        print(f"[ERROR] Failed to list users: {result}")
        return []


def get_user(token, base_url, realm, user_id):
    """Get user by ID."""
    code, result = api_call("GET", f"/admin/realms/{realm}/users/{user_id}", base_url, token)
    return result if code == 200 else None


def update_user(token, base_url, realm, user_id, **kwargs):
    """Update user attributes."""
    user = get_user(token, base_url, realm, user_id)
    if not user:
        print(f"[ERROR] User {user_id} not found")
        return False

    user.update(kwargs)
    code, result = api_call("PUT", f"/admin/realms/{realm}/users/{user_id}", base_url, token, user)
    if code == 204:
        print(f"[OK] User '{user.get('username')}' updated")
        return True
    else:
        print(f"[ERROR] Failed to update user: {result}")
        return False


def delete_user(token, base_url, realm, user_id):
    """Delete a user by ID."""
    user = get_user(token, base_url, realm, user_id)
    username = user.get("username") if user else user_id
    code, result = api_call("DELETE", f"/admin/realms/{realm}/users/{user_id}", base_url, token)
    if code == 204:
        print(f"[OK] User '{username}' deleted")
        return True
    else:
        print(f"[ERROR] Failed to delete user: {result}")
        return False


def set_user_password(token, base_url, realm, username, password, temporary=False):
    """Set/reset a user's password via PUT /users/{id} with credentials array."""
    users = list_users(token, base_url, realm, username=username)
    if not users:
        print(f"[ERROR] User '{username}' not found")
        return False

    user_data = dict(users[0])
    user_data["credentials"] = [{"type": "password", "value": password, "temporary": temporary}]
    code, result = api_call(
        "PUT", f"/admin/realms/{realm}/users/{users[0]['id']}",
        base_url, token, user_data
    )
    if code == 204:
        print(f"[OK] Password set for '{username}'")
        return True
    else:
        print(f"[ERROR] Failed to set password: {result}")
        return False


# --- GROUP OPERATIONS ---

def create_group(token, base_url, realm, name, parent_id=None):
    """Create a group (top-level or subgroup)."""
    group_data = {"name": name}

    if parent_id:
        endpoint = f"/admin/realms/{realm}/groups/{parent_id}/children"
    else:
        endpoint = f"/admin/realms/{realm}/groups"

    code, result = api_call("POST", endpoint, base_url, token, group_data)
    if code == 201:
        print(f"[OK] Group '{name}' created")
        # 201 response may have empty body; search to get full group data
        groups = list_groups(token, base_url, "master", search=name)
        if groups:
            return groups[0]
        return {"id": "created", "name": name}
    else:
        print(f"[ERROR] Failed to create group: {result}")
        return None


def list_groups(token, base_url, realm, search=None):
    """List groups."""
    endpoint = f"/admin/realms/{realm}/groups?briefRepresentation=false"
    if search:
        endpoint += f"&search={search}"

    code, result = api_call("GET", endpoint, base_url, token)
    return result if code == 200 and result else []


def get_group(token, base_url, realm, group_id):
    """Get group by ID."""
    code, result = api_call("GET", f"/admin/realms/{realm}/groups/{group_id}", base_url, token)
    return result if code == 200 else None


def update_group(token, base_url, realm, group_id, name=None):
    """Update group name."""
    group = get_group(token, base_url, realm, group_id)
    if not group:
        print(f"[ERROR] Group {group_id} not found")
        return False

    if name:
        group["name"] = name

    code, result = api_call("PUT", f"/admin/realms/{realm}/groups/{group_id}", base_url, token, group)
    if code == 204:
        print(f"[OK] Group '{group.get('name')}' updated")
        return True
    else:
        print(f"[ERROR] Failed to update group: {result}")
        return False


def delete_group(token, base_url, realm, group_id):
    """Delete a group."""
    group = get_group(token, base_url, realm, group_id)
    name = group.get("name") if group else group_id
    code, result = api_call("DELETE", f"/admin/realms/{realm}/groups/{group_id}", base_url, token)
    if code == 204:
        print(f"[OK] Group '{name}' deleted")
        return True
    else:
        print(f"[ERROR] Failed to delete group: {result}")
        return False


def add_user_to_group(token, base_url, realm, user_id, group_id):
    """Add user to a group."""
    code, result = api_call(
        "PUT", f"/admin/realms/{realm}/users/{user_id}/groups/{group_id}",
        base_url, token
    )
    if code == 204:
        print(f"[OK] User added to group")
        return True
    else:
        print(f"[ERROR] Failed: {result}")
        return False


def remove_user_from_group(token, base_url, realm, user_id, group_id):
    """Remove user from a group."""
    code, result = api_call(
        "DELETE", f"/admin/realms/{realm}/users/{user_id}/groups/{group_id}",
        base_url, token
    )
    if code == 204:
        print(f"[OK] User removed from group")
        return True
    else:
        print(f"[ERROR] Failed: {result}")
        return False


def get_group_members(token, base_url, realm, group_id):
    """Get members of a group."""
    code, result = api_call("GET", f"/admin/realms/{realm}/groups/{group_id}/members", base_url, token)
    return result if code == 200 and result else []


# --- ROLE OPERATIONS ---

def create_role(token, base_url, realm, name, description=""):
    """Create a realm role."""
    role_data = {"name": name, "description": description}
    code, result = api_call("POST", f"/admin/realms/{realm}/roles", base_url, token, role_data)
    if code == 201:
        print(f"[OK] Role '{name}' created")
        return True
    else:
        print(f"[ERROR] Failed to create role: {result}")
        return False


def list_roles(token, base_url, realm):
    """List realm roles."""
    code, result = api_call("GET", f"/admin/realms/{realm}/roles", base_url, token)
    return result if code == 200 and result else []


def get_role(token, base_url, realm, name):
    """Get role by name."""
    code, result = api_call("GET", f"/admin/realms/{realm}/roles/{name}", base_url, token)
    return result if code == 200 else None


def delete_role(token, base_url, realm, name):
    """Delete a realm role."""
    code, result = api_call("DELETE", f"/admin/realms/{realm}/roles/{name}", base_url, token)
    if code == 204:
        print(f"[OK] Role '{name}' deleted")
        return True
    else:
        print(f"[ERROR] Failed to delete role: {result}")
        return False


def assign_roles_to_user(token, base_url, realm, username, role_names, scope="realm"):
    """Assign realm or client roles to a user."""
    users = list_users(token, base_url, realm, username=username)
    if not users:
        print(f"[ERROR] User '{username}' not found")
        return False

    user_id = users[0]["id"]
    roles = []
    for rname in role_names:
        role = get_role(token, base_url, realm, rname)
        if role:
            roles.append({"id": role["id"], "name": role["name"]})

    if not roles:
        print("[ERROR] No valid roles found")
        return False

    if scope == "realm":
        endpoint = f"/admin/realms/{realm}/users/{user_id}/role-mappings/realm"
    else:
        endpoint = f"/admin/realms/{realm}/users/{user_id}/role-mappings/client/{scope}"

    code, result = api_call("POST", endpoint, base_url, token, roles)
    if code == 204:
        print(f"[OK] Roles {role_names} assigned to '{username}'")
        return True
    else:
        print(f"[ERROR] Failed to assign roles: {result}")
        return False


def remove_roles_from_user(token, base_url, realm, username, role_names, scope="realm"):
    """Remove roles from a user."""
    users = list_users(token, base_url, realm, username=username)
    if not users:
        print(f"[ERROR] User '{username}' not found")
        return False

    user_id = users[0]["id"]
    roles = []
    for rname in role_names:
        role = get_role(token, base_url, realm, rname)
        if role:
            roles.append({"id": role["id"], "name": role["name"]})

    if scope == "realm":
        endpoint = f"/admin/realms/{realm}/users/{user_id}/role-mappings/realm"
    else:
        endpoint = f"/admin/realms/{realm}/users/{user_id}/role-mappings/client/{scope}"

    code, result = api_call("DELETE", endpoint, base_url, token, roles)
    if code == 204:
        print(f"[OK] Roles {role_names} removed from '{username}'")
        return True
    else:
        print(f"[ERROR] Failed to remove roles: {result}")
        return False


def get_user_roles(token, base_url, realm, username):
    """Get all roles for a user."""
    users = list_users(token, base_url, realm, username=username)
    if not users:
        print(f"[ERROR] User '{username}' not found")
        return []

    user_id = users[0]["id"]
    code, result = api_call(
        "GET", f"/admin/realms/{realm}/users/{user_id}/role-mappings/realm",
        base_url, token
    )
    if code == 200 and result:
        if isinstance(result, dict):
            return result.get("realmMappings", [])
        return result
    return []


def assign_roles_to_group(token, base_url, realm, group_id, role_names):
    """Assign realm roles to a group."""
    roles = []
    for rname in role_names:
        role = get_role(token, base_url, realm, rname)
        if role:
            roles.append({"id": role["id"], "name": role["name"]})

    if not roles:
        print("[ERROR] No valid roles found")
        return False

    endpoint = f"/admin/realms/{realm}/groups/{group_id}/role-mappings/realm"
    code, result = api_call("POST", endpoint, base_url, token, roles)
    if code == 204:
        print(f"[OK] Roles assigned to group")
        return True
    else:
        print(f"[ERROR] Failed: {result}")
        return False


# --- REALM OPERATIONS ---

def list_realms(token, base_url):
    """List all realms. Returns list of realm name strings for simplicity."""
    code, result = api_call("GET", "/admin/realms", base_url, token)
    if code == 200 and result:
        if isinstance(result, list):
            # Keycloak returns realm objects with 'realm' key or just strings
            return [r.get("realm", r) if isinstance(r, dict) else r for r in result]
    return []


def create_realm(token, base_url, realm_name, enabled=True):
    """Create a new realm."""
    realm_data = {
        "realm": realm_name,
        "enabled": enabled,
    }
    code, result = api_call("POST", "/admin/realms", base_url, token, realm_data)
    if code == 201:
        print(f"[OK] Realm '{realm_name}' created")
        return True
    else:
        print(f"[ERROR] Failed to create realm: {result}")
        return False


# --- HEALTH CHECK ---

def health_check(base_url):
    """Check Keycloak health endpoint (port 9000 management interface)."""
    # Keycloak health/metrics are on the management port (9000), not the HTTP port (8080)
    # Derive management URL from base URL by replacing port or appending :9000
    management_url = base_url.replace("8080", "9000", 1)
    if ":8080" not in base_url and ":9000" not in management_url:
        management_url = base_url.replace(":443", ":9000", 1).replace(":8443", ":9000", 1)
    if ":9000" not in management_url:
        # default: append 9000 if no known port found
        management_url = base_url.rsplit(":", 1)[0] + ":9000"

    try:
        url = f"{management_url}/health"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            status = data.get("status", "UNKNOWN")
            return status == "UP", data
    except Exception as e:
        return False, {"error": str(e)}


# --- MAIN CLI ---

def main():
    import urllib.parse  # needed for token endpoint

    parser = argparse.ArgumentParser(description="Keycloak Admin CLI - Manage users, groups, roles")
    parser.add_argument("-u", "--url", default=None, help="Keycloak base URL (default: env or localhost:8080)")
    parser.add_argument("-r", "--realm", default="master", help="Realm name (default: master)")

    sub = parser.add_subparsers(dest="command", help="Operation to perform")

    # Health
    sub.add_parser("health", help="Check Keycloak health")

    # Realms
    rp = sub.add_parser("list-realms", help="List all realms")
    crp = sub.add_parser("create-realm", help="Create a new realm")
    crp.add_argument("name", help="Realm name")

    # Users
    lup = sub.add_parser("list-users", help="List users")
    lup.add_argument("--username", help="Filter by username")
    lup.add_argument("--email", help="Filter by email")

    cup = sub.add_parser("create-user", help="Create a user")
    cup.add_argument("username", help="Username")
    cup.add_argument("--email", help="Email address")
    cup.add_argument("--first-name", help="First name")
    cup.add_argument("--last-name", help="Last name")
    cup.add_argument("--password", help="Initial password")

    dup = sub.add_parser("delete-user", help="Delete user by username")
    dup.add_argument("username", help="Username to delete")

    upp = sub.add_parser("update-user", help="Update user")
    upp.add_argument("username", help="Username")
    upp.add_argument("--email", help="New email")
    upp.add_argument("--first-name", help="New first name")
    upp.add_argument("--last-name", help="New last name")
    upp.add_argument("--disable", action="store_true", help="Disable the user")

    spp = sub.add_parser("set-password", help="Set/reset user password")
    spp.add_argument("username", help="Username")
    spp.add_argument("password", help="New password")

    # Groups
    lgp = sub.add_parser("list-groups", help="List groups")
    lgp.add_argument("--search", help="Search groups")

    cgp = sub.add_parser("create-group", help="Create a group")
    cgp.add_argument("name", help="Group name")
    cgp.add_argument("--parent-id", help="Parent group ID for subgroups")

    dgp = sub.add_parser("delete-group", help="Delete group by name")
    dgp.add_argument("name", help="Group name to delete")

    augp = sub.add_parser("add-user-group", help="Add user to group")
    augp.add_argument("username", help="Username")
    augp.add_argument("group_name", help="Group name")

    rugp = sub.add_parser("remove-user-group", help="Remove user from group")
    rugp.add_argument("username", help="Username")
    rugp.add_argument("group_name", help="Group name")

    mgp = sub.add_parser("group-members", help="Show group members")
    mgp.add_argument("group_name", help="Group name")

    # Roles
    lrp = sub.add_parser("list-roles", help="List realm roles")

    crp2 = sub.add_parser("create-role", help="Create a realm role")
    crp2.add_argument("name", help="Role name")
    crp2.add_argument("--description", default="", help="Role description")

    drp = sub.add_parser("delete-role", help="Delete a realm role")
    drp.add_argument("name", help="Role name")

    arup = sub.add_parser("assign-role", help="Assign role to user")
    arup.add_argument("username", help="Username")
    arup.add_argument("roles", nargs="+", help="Role name(s)")

    rrup = sub.add_parser("remove-role", help="Remove role from user")
    rrup.add_argument("username", help="Username")
    rrup.add_argument("roles", nargs="+", help="Role name(s)")

    urp = sub.add_parser("user-roles", help="Show user roles")
    urp.add_argument("username", help="Username")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    base_url = (args.url or os.environ.get("KEYCLOAK_URL", DEFAULT_BASE_URL)).rstrip("/")
    realm = args.realm

    # Health check doesn't need auth
    if args.command == "health":
        ok, data = health_check(base_url)
        print(f"{'[OK] Keycloak is UP' if ok else '[FAIL] Keycloak is DOWN'}")
        print(json.dumps(data, indent=2))
        return

    # Auth for all other commands
    username, password = load_credentials()
    token = get_token(base_url, username, password)

    if args.command == "list-realms":
        print(json.dumps(list_realms(token, base_url), indent=2))

    elif args.command == "create-realm":
        create_realm(token, base_url, args.name)

    elif args.command == "list-users":
        users = list_users(token, base_url, realm, username=args.username, email=args.email)
        print(json.dumps(users, indent=2))

    elif args.command == "create-user":
        create_user(
            token, base_url, realm, args.username,
            email=args.email, first_name=args.first_name,
            last_name=args.last_name, password=args.password,
        )

    elif args.command == "delete-user":
        users = list_users(token, base_url, realm, username=args.username)
        if users:
            delete_user(token, base_url, realm, users[0]["id"])

    elif args.command == "update-user":
        users = list_users(token, base_url, realm, username=args.username)
        if users:
            kwargs = {}
            if args.email:
                kwargs["email"] = args.email
            if args.first_name:
                kwargs["firstName"] = args.first_name
            if args.last_name:
                kwargs["lastName"] = args.last_name
            if args.disable:
                kwargs["enabled"] = False
            update_user(token, base_url, realm, users[0]["id"], **kwargs)

    elif args.command == "set-password":
        set_user_password(token, base_url, realm, args.username, args.password)

    elif args.command == "list-groups":
        groups = list_groups(token, base_url, realm, search=args.search)
        print(json.dumps(groups, indent=2))

    elif args.command == "create-group":
        create_group(token, base_url, realm, args.name, parent_id=args.parent_id)

    elif args.command == "delete-group":
        groups = list_groups(token, base_url, realm, search=args.name)
        if groups:
            delete_group(token, base_url, realm, groups[0]["id"])

    elif args.command == "add-user-group":
        users = list_users(token, base_url, realm, username=args.username)
        groups = list_groups(token, base_url, realm, search=args.group_name)
        if users and groups:
            add_user_to_group(token, base_url, realm, users[0]["id"], groups[0]["id"])

    elif args.command == "remove-user-group":
        users = list_users(token, base_url, realm, username=args.username)
        groups = list_groups(token, base_url, realm, search=args.group_name)
        if users and groups:
            remove_user_from_group(token, base_url, realm, users[0]["id"], groups[0]["id"])

    elif args.command == "group-members":
        groups = list_groups(token, base_url, realm, search=args.group_name)
        if groups:
            members = get_group_members(token, base_url, realm, groups[0]["id"])
            print(json.dumps(members, indent=2))

    elif args.command == "list-roles":
        roles = list_roles(token, base_url, realm)
        print(json.dumps(roles, indent=2))

    elif args.command == "create-role":
        create_role(token, base_url, realm, args.name, description=args.description)

    elif args.command == "delete-role":
        delete_role(token, base_url, realm, args.name)

    elif args.command == "assign-role":
        assign_roles_to_user(token, base_url, realm, args.username, args.roles)

    elif args.command == "remove-role":
        remove_roles_from_user(token, base_url, realm, args.username, args.roles)

    elif args.command == "user-roles":
        roles = get_user_roles(token, base_url, realm, args.username)
        print(json.dumps(roles, indent=2))


if __name__ == "__main__":
    main()
