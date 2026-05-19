#!/usr/bin/env python3
"""Set a local dashboard login password without printing the secret."""
import argparse
import asyncio
import getpass
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

from database import execute, fetchrow  # noqa: E402
from services import access_control  # noqa: E402


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("username")
    parser.add_argument("--password-env", default="DASHBOARD_LOGIN_PASSWORD")
    parser.add_argument("--password-file", default="")
    parser.add_argument("--role", default="platform-admin")
    parser.add_argument("--display-name", default="")
    parser.add_argument("--provider", default="local")
    args = parser.parse_args()

    password = os.getenv(args.password_env, "")
    if not password and args.password_file:
        password = Path(args.password_file).read_text(encoding="utf-8").strip()
    if not password:
        password = getpass.getpass("Dashboard password: ")
    if not password:
        raise SystemExit("password is required")

    password_hash = access_control.hash_password(password)
    row = await fetchrow("SELECT id FROM dashboard_users WHERE username = $1", args.username)
    if row:
        await execute(
            """
            UPDATE dashboard_users
            SET password_hash = $1,
                password_changed_at = NOW(),
                provider = COALESCE(NULLIF(provider, ''), $2),
                display_name = COALESCE(NULLIF(display_name, ''), $3),
                enabled = true,
                failed_login_count = 0,
                updated_at = NOW()
            WHERE id = $4
            """,
            password_hash,
            args.provider,
            args.display_name or args.username,
            row["id"],
        )
        user_id = row["id"]
    else:
        user_id = await fetchrow(
            """
            INSERT INTO dashboard_users (
                username, display_name, provider, enabled, password_hash, password_changed_at
            )
            VALUES ($1, $2, $3, true, $4, NOW())
            RETURNING id
            """,
            args.username,
            args.display_name or args.username,
            args.provider,
            password_hash,
        )
        user_id = user_id["id"]

    role = await fetchrow("SELECT id FROM dashboard_roles WHERE name = $1", args.role)
    if role:
        await execute(
            "INSERT INTO dashboard_user_roles (user_id, role_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
            user_id,
            role["id"],
        )
    print({"status": "password_set", "username": args.username, "role": args.role, "secret_printed": False})


if __name__ == "__main__":
    asyncio.run(main())
