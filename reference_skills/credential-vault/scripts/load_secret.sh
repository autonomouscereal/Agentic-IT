#!/usr/bin/env bash
# Shared secret resolver for platform scripts. Resolution order:
# env var -> env-named file -> default file -> encrypted credential vault.

credential_vault_credman_candidates() {
    if [ -n "${CREDMAN_PATH:-}" ]; then
        printf '%s\n' "$CREDMAN_PATH"
    fi
    if [ -n "${CREDENTIAL_VAULT_DIR:-}" ]; then
        printf '%s\n' "${CREDENTIAL_VAULT_DIR%/}/scripts/credman.py"
    fi

    printf '%s\n' \
        "./reference_skills/server-manager/credman.py" \
        "../server-manager/credman.py" \
        "../../server-manager/credman.py" \
        "$HOME/.agents/skills/server-manager/credman.py"
}

load_secret() {
    local vault_key="${1:?vault key is required}"
    local env_name="${2:-}"
    local file_env_name="${3:-}"
    local default_file="${4:-}"
    local env_value=""
    local file_path=""
    local credman=""

    if [ -n "$env_name" ]; then
        eval "env_value=\${$env_name:-}"
        if [ -n "$env_value" ]; then
            printf '%s' "$env_value"
            return 0
        fi
    fi

    if [ -n "$file_env_name" ]; then
        eval "file_path=\${$file_env_name:-}"
        if [ -n "$file_path" ] && [ -f "$file_path" ]; then
            tr -d '\r\n' < "$file_path"
            return 0
        fi
    fi

    if [ -n "$default_file" ] && [ -f "$default_file" ]; then
        tr -d '\r\n' < "$default_file"
        return 0
    fi

    while IFS= read -r credman; do
        if [ -f "$credman" ]; then
            python "$credman" get "$vault_key" 2>/dev/null && return 0
        fi
    done <<EOF
$(credential_vault_credman_candidates)
EOF

    return 1
}
