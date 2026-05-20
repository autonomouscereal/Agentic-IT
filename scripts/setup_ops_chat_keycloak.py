#!/usr/bin/env python3
"""Configure the Keycloak OIDC client used by Matrix/Synapse Ops Chat.

This script intentionally uses only the Python standard library and raw HTTP.
It reads runtime values from a deployment .env file or process environment and
never prints secrets.
"""

from __future__ import annotations

import argparse
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _env(name: str, *sources: dict[str, str], default: str = "") -> str:
    if os.getenv(name):
        return os.getenv(name, "")
    for source in sources:
        if source.get(name):
            return source[name]
    return default


class Keycloak:
    def __init__(self, base_url: str, admin_user: str, admin_password: str, ca_cert: str = ""):
        self.base_url = base_url.rstrip("/")
        self.admin_user = admin_user
        self.admin_password = admin_password
        if ca_cert:
            self.context = ssl.create_default_context(cafile=ca_cert)
        else:
            self.context = ssl.create_default_context()
        self.token = ""

    def request(self, method: str, path: str, body: object | None = None, form: dict[str, str] | None = None):
        data = None
        headers: dict[str, str] = {}
        if form is not None:
            data = urllib.parse.urlencode(form).encode("utf-8")
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        elif body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(self.base_url + path, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req, context=self.context, timeout=30) as response:
                raw = response.read()
                if not raw:
                    return None
                text = raw.decode("utf-8")
                return json.loads(text) if text else None
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"{method} {path} failed with HTTP {exc.code}: {detail[:500]}") from exc

    def login(self):
        data = self.request(
            "POST",
            "/realms/master/protocol/openid-connect/token",
            form={
                "grant_type": "password",
                "client_id": "admin-cli",
                "username": self.admin_user,
                "password": self.admin_password,
            },
        )
        self.token = data["access_token"]

    def get_client(self, realm: str, client_id: str):
        encoded = urllib.parse.quote(client_id, safe="")
        clients = self.request("GET", f"/admin/realms/{realm}/clients?clientId={encoded}") or []
        for client in clients:
            if client.get("clientId") == client_id:
                return client
        return None

    def create_or_update_client(self, realm: str, client_id: str, secret: str, redirect_uris: list[str], web_origins: list[str]):
        client = self.get_client(realm, client_id)
        payload = {
            "clientId": client_id,
            "name": "Agentic Ops Chat",
            "enabled": True,
            "protocol": "openid-connect",
            "publicClient": False,
            "clientAuthenticatorType": "client-secret",
            "secret": secret,
            "standardFlowEnabled": True,
            "directAccessGrantsEnabled": False,
            "serviceAccountsEnabled": False,
            "implicitFlowEnabled": False,
            "bearerOnly": False,
            "redirectUris": redirect_uris,
            "webOrigins": web_origins,
            "attributes": {
                "post.logout.redirect.uris": "+",
                "pkce.code.challenge.method": "S256",
            },
        }
        if client:
            payload.update({"id": client["id"]})
            self.request("PUT", f"/admin/realms/{realm}/clients/{client['id']}", body=payload)
            return "updated"
        self.request("POST", f"/admin/realms/{realm}/clients", body=payload)
        return "created"

    def get_user(self, realm: str, username: str):
        encoded = urllib.parse.quote(username, safe="")
        users = self.request("GET", f"/admin/realms/{realm}/users?username={encoded}&exact=true") or []
        for user in users:
            if user.get("username") == username:
                return user
        return None

    def create_or_update_user_password(self, realm: str, username: str, password: str, email: str = ""):
        user = self.get_user(realm, username)
        if not user:
            payload = {
                "username": username,
                "enabled": True,
                "emailVerified": True,
                "email": email or f"{username}@agentic-ops.local",
                "firstName": username.replace("_", " ").title(),
                "lastName": "Demo",
            }
            self.request("POST", f"/admin/realms/{realm}/users", body=payload)
            user = self.get_user(realm, username)
            if not user:
                raise RuntimeError(f"Keycloak user {username!r} was not created")
            action = "created"
        else:
            self.request(
                "PUT",
                f"/admin/realms/{realm}/users/{user['id']}",
                body={
                    **user,
                    "enabled": True,
                    "emailVerified": True,
                    "email": user.get("email") or email or f"{username}@agentic-ops.local",
                },
            )
            action = "updated"
        self.request(
            "PUT",
            f"/admin/realms/{realm}/users/{user['id']}/reset-password",
            body={"type": "password", "value": password, "temporary": False},
        )
        return action


def main() -> int:
    parser = argparse.ArgumentParser(description="Configure Keycloak OIDC for Ops Chat.")
    parser.add_argument("--deployment-env", default=".env")
    parser.add_argument("--keycloak-env", default="/home/cereal/keycloak-manager/.env")
    parser.add_argument("--keycloak-url", default="")
    parser.add_argument("--realm", default="master")
    parser.add_argument("--ensure-user", default="", help="Optional demo/user account to create or reset.")
    parser.add_argument("--ensure-user-email", default="")
    args = parser.parse_args()

    deployment_env = _read_env_file(Path(args.deployment_env))
    keycloak_env = _read_env_file(Path(args.keycloak_env))

    issuer = _env("MATRIX_OIDC_ISSUER", deployment_env, default="").rstrip("/")
    if not issuer and not args.keycloak_url:
        print("[ERROR] MATRIX_OIDC_ISSUER or --keycloak-url is required", file=sys.stderr)
        return 2
    keycloak_url = (args.keycloak_url or issuer.rsplit("/realms/", 1)[0]).rstrip("/")
    realm = args.realm or (issuer.rsplit("/realms/", 1)[1] if "/realms/" in issuer else "master")
    client_id = _env("MATRIX_OIDC_CLIENT_ID", deployment_env, default="agentic-ops-chat")
    client_secret = _env("MATRIX_OIDC_CLIENT_SECRET", deployment_env)
    public_base = _env("MATRIX_PUBLIC_BASEURL", deployment_env, default="http://localhost:3302").rstrip("/")
    element_url = _env("MATRIX_ELEMENT_PUBLIC_URL", deployment_env, default="http://localhost:3301").rstrip("/")
    ca_cert = _env("MATRIX_OIDC_CA_CERT_PATH", deployment_env)

    admin_user = _env("KC_BOOTSTRAP_ADMIN_USERNAME", keycloak_env, default="admin")
    admin_password = _env("KC_BOOTSTRAP_ADMIN_PASSWORD", keycloak_env) or _env("KEYCLOAK_ADMIN_PASSWORD", keycloak_env)
    if not client_secret:
        print("[ERROR] MATRIX_OIDC_CLIENT_SECRET is required", file=sys.stderr)
        return 2
    if not admin_password:
        print("[ERROR] Keycloak admin password is required", file=sys.stderr)
        return 2

    redirect_uris = [
        f"{public_base}/_synapse/client/oidc/callback",
        f"{public_base}/_synapse/client/oidc/callback*",
        f"{element_url}/*",
    ]
    web_origins = [element_url, public_base]

    kc = Keycloak(keycloak_url, admin_user, admin_password, ca_cert)
    kc.login()
    action = kc.create_or_update_client(realm, client_id, client_secret, redirect_uris, web_origins)
    print(f"[OK] Keycloak client {client_id!r} {action} in realm {realm!r}.")
    print("[OK] Redirect URIs and web origins now match Ops Chat runtime URLs.")
    if args.ensure_user:
        user_password = os.getenv("OPS_CHAT_DEMO_PASSWORD", "")
        if not user_password:
            print("[ERROR] OPS_CHAT_DEMO_PASSWORD is required with --ensure-user", file=sys.stderr)
            return 2
        user_action = kc.create_or_update_user_password(realm, args.ensure_user, user_password, args.ensure_user_email)
        print(f"[OK] Keycloak user {args.ensure_user!r} {user_action} and password reset.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
