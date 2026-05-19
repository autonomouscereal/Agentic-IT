#!/usr/bin/env python3
"""Fix GitLab OIDC config in gitlab.rb - remove broken lines, write correct config."""
import os
import re
import sys

CONFIG_PATH = "/etc/gitlab/gitlab.rb"
q = '"'  # double quote character
issuer = os.environ.get("GITLAB_OIDC_ISSUER", "https://127.0.0.1:8443/realms/gitlab")
redirect_uri = os.environ.get(
    "GITLAB_OIDC_REDIRECT_URI",
    "http://127.0.0.1/users/auth/openid_connect/callback",
)
client_secret = os.environ.get("GITLAB_OIDC_CLIENT_SECRET")

# Step 1: Read existing config and remove any broken Keycloak OIDC lines
with open(CONFIG_PATH, "r") as f:
    lines = f.readlines()

if not client_secret:
    existing = "".join(lines)
    match = re.search(r'"secret"\s*=>\s*"([^"]+)"', existing)
    if match:
        client_secret = match.group(1)

if not client_secret:
    print(
        "[ERROR] No GitLab OIDC client secret found. Set GITLAB_OIDC_CLIENT_SECRET "
        "from the credential vault or run setup_oidc.py first.",
        file=sys.stderr,
    )
    sys.exit(1)

# Find and remove our previous (broken) Keycloak config
start_idx = None
for i, line in enumerate(lines):
    if "Keycloak OIDC Integration" in line:
        start_idx = i
        break

if start_idx is not None:
    removed = len(lines) - start_idx
    lines = lines[:start_idx]
    print(f"Removed {removed} broken config lines starting at line {start_idx + 1}")
else:
    print("No existing Keycloak config found, appending fresh")

# Step 2: Write correct Ruby config with proper quoting
config_lines = [
    "",
    "# Keycloak OIDC Integration - Configured 2026-05-02",
    f'gitlab_rails[{q}omniauth_providers{q}] = [',
    "  {",
    f'    {q}name{q} => {q}openid_connect{q},',
    f'    {q}label{q} => {q}Keycloak{q},',
    f'    {q}icon{q} => {q}/assets/images/provider/keycloak.png{q},',
    f'    {q}args{q} => {{',
    f'      {q}name{q} => {q}openid_connect{q},',
    f'      {q}scope{q} => [{q}openid{q}, {q}profile{q}, {q}email{q}],',
    f'      {q}response_type{q} => {q}code{q},',
    f'      {q}issuer{q} => {q}{issuer}{q},',
    f'      {q}discovery{q} => true,',
    f'      {q}client_auth_method{q} => {q}query{q},',
    f'      {q}uid_field{q} => {q}sub{q},',
    f'      {q}allow_validate_issuer{q} => false,',
    f'      {q}pkce{q} => true,',
    f'      {q}client_options{q} => {{',
    f'        {q}identifier{q} => {q}gitlab{q},',
    f'        {q}secret{q} => {q}{client_secret}{q},',
    f'        {q}redirect_uri{q} => {q}{redirect_uri}{q}',
    "      }",
    "    }",
    "  }",
    "]",
    "",
    "# OIDC Authentication Settings",
    f'gitlab_rails[{q}omniauth_enabled{q}] = true',
    f'gitlab_rails[{q}omniauth_allow_single_sign_on{q}] = true',
    f'gitlab_rails[{q}omniauth_block_auto_created_users{q}] = true',
    f'gitlab_rails[{q}omniauth_auto_link_users{q}] = true',
    "",
]

with open(CONFIG_PATH, "w") as f:
    f.writelines(lines)
    f.write("\n".join(config_lines))

print(f"Wrote {len(config_lines)} config lines to {CONFIG_PATH}")
print(f"OIDC issuer: {issuer}")
print(f"Redirect URI: {redirect_uri}")
print("Done - ready for gitlab-ctl reconfigure")
