#!/usr/bin/env bash
# Shared GitLab PAT resolver. Reads env first, then optional token file, then
# the encrypted server-manager vault via credman.py.

load_gitlab_pat() {
    local vault_key="${1:-${GITLAB_PAT_VAULT_KEY:-gitlab_manager_pat}}"
    local token_file="${GITLAB_PAT_FILE:-${TOKEN_FILE:-/home/cereal/gitlab/.gitlab-token}}"
    local credman_candidates=()

    if [ -n "${GITLAB_PAT:-}" ]; then
        printf '%s' "$GITLAB_PAT"
        return 0
    fi

    if [ -f "$token_file" ]; then
        tr -d '\r\n' < "$token_file"
        return 0
    fi

    if [ -n "${CREDMAN_PATH:-}" ]; then
        credman_candidates+=("$CREDMAN_PATH")
    fi
    credman_candidates+=(
        "/home/cereal/.claude/skills/server-manager/credman.py"
        "/home/cereal/.agents/skills/server-manager/credman.py"
        "C:/Users/cereal/.claude/skills/server-manager/credman.py"
        "C:/Users/cereal/.agents/skills/server-manager/credman.py"
    )

    for credman in "${credman_candidates[@]}"; do
        if [ -f "$credman" ]; then
            python "$credman" get "$vault_key" 2>/dev/null && return 0
        fi
    done

    return 1
}
