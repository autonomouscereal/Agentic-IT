#!/usr/bin/env bash
# deploy.sh - Full GitLab CE + GitLab Runner Deployment Script
# GitLab 17.x compatible (session API removed, PAT-based auth)
#
# Usage: bash deploy.sh [--fresh | --reconfigure | --status | --stop | --start | --update | --credentials]

set -euo pipefail

DEPLOY_DIR="${DEPLOY_DIR:-/home/cereal/gitlab}"
GITLAB_VERSION="${GITLAB_VERSION:-17.11.3-ce.0}"
RUNNER_VERSION="${RUNNER_VERSION:-v17.11.0}"
GITLAB_HOSTNAME="${GITLAB_HOSTNAME:-192.168.50.222}"
GITLAB_HTTP_PORT="${GITLAB_HTTP_PORT:-80}"
GITLAB_SSH_PORT="${GITLAB_SSH_PORT:-2222}"
GITLAB_TIMEZONE="${GITLAB_TIMEZONE:-UTC}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log_info() { echo -e "${BLUE}[INFO]${NC} $*"; }
log_ok()   { echo -e "${GREEN}[OK]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_err()  { echo -e "${RED}[ERROR]${NC} $*"; }

generate_secure_password() {
    openssl rand -base64 32 | tr -d '/+=' | head -c 32
}

generate_pat() {
    # Generate a PAT via the GitLab API (requires root password first)
    local root_pass="$1"
    curl -sf --request POST \
        "http://${GITLAB_HOSTNAME}/api/v4/personal_access_tokens" \
        --header "PRIVATE-TOKEN: $(echo "$root_pass" | docker exec -i gitlab gitlab-rails "puts User.find_by(username: 'root').personal_access_tokens.create(name: 'deploy-pat', scopes: ['api', 'read_api', 'write_repository']).token")" \
        2>/dev/null | grep -o '"token":"[^"]*"' | cut -d'"' -f4 || true
}

wait_for_gitlab() {
    local max_attempts=60
    local attempt=0
    log_info "Waiting for GitLab to become healthy..."
    log_info "(This can take 3-7 minutes on first boot)"

    until [ $attempt -ge $max_attempts ]; do
        if docker exec gitlab curl -sf http://localhost/-/health >/dev/null 2>&1; then
            log_ok "GitLab is healthy!"
            return 0
        fi
        attempt=$((attempt + 1))
        echo -n "."
        sleep 10
    done

    echo ""
    log_err "GitLab did not become healthy within $((max_attempts * 10)) seconds."
    log_info "Check logs with: docker compose -f ${DEPLOY_DIR}/docker-compose.yml logs gitlab"
    return 1
}

get_root_password() {
    if [ -f "${DEPLOY_DIR}/.env" ]; then
        local pass
        pass=$(grep '^GITLAB_ROOT_PASSWORD=' "${DEPLOY_DIR}/.env" 2>/dev/null | cut -d'=' -f2-)
        if [ -n "$pass" ]; then
            echo "$pass"
            return 0
        fi
    fi
    log_err "Could not retrieve root password from .env."
    return 1
}

get_pat() {
    # Try .gitlab-token file first, then .env
    if [ -f "${DEPLOY_DIR}/.gitlab-token" ]; then
        cat "${DEPLOY_DIR}/.gitlab-token"
        return 0
    fi
    if [ -f "${DEPLOY_DIR}/.env" ]; then
        grep '^GITLAB_PAT=' "${DEPLOY_DIR}/.env" 2>/dev/null | cut -d'=' -f2- || true
    fi
}

register_runner() {
    log_info "=== Registering GitLab Runner ==="

    if ! docker exec gitlab curl -sf http://localhost/-/health >/dev/null 2>&1; then
        log_err "GitLab is not healthy. Cannot register runner."
        return 1
    fi

    local pat
    pat=$(get_pat)
    if [ -z "${pat:-}" ]; then
        log_err "No PAT found. Create one in GitLab UI or place it in ${DEPLOY_DIR}/.gitlab-token"
        return 1
    fi

    # GitLab 17.x CE: runner authentication tokens API not available.
    # Register at instance level using the registration token from settings,
    # or register at project/group level with a PAT.
    local reg_token
    reg_token=$(curl -sf \
        "http://${GITLAB_HOSTNAME}/api/v4/application/settings/registration" \
        --header "PRIVATE-TOKEN: ${pat}" \
        2>/dev/null | python3 -c "import sys,json;print(json.load(sys.stdin).get('registration_token',''))" 2>/dev/null || echo "")

    if [ -z "${reg_token:-}" ]; then
        log_warn "Could not get registration token via API, trying direct runner register..."
        # Fallback: use PAT to register runner at admin level
        docker exec gitlab-runner gitlab-runner register \
            --non-interactive \
            --url "http://${GITLAB_HOSTNAME}" \
            --token "${pat}" \
            --executor "docker" \
            --description "Primary Docker Runner" \
            --tag-list "docker,linux,general" \
            --docker-image "alpine:latest" \
            --run-untagged="true" \
            --locked="false" 2>&1 || {
                log_warn "Direct registration failed, trying with registration token from settings..."
                return 1
            }
    else
        log_ok "Registration token obtained."
        docker run --rm \
            --network gitlab-net \
            -v runner-config:/etc/gitlab-runner \
            gitlab/gitlab-runner:${RUNNER_VERSION} \
            register \
            --non-interactive \
            --url "http://gitlab" \
            --token "${reg_token}" \
            --executor "docker" \
            --description "Primary Docker Runner" \
            --tag-list "docker,linux,general" \
            --docker-image "alpine:latest" \
            --docker-volumes "/cache:/cache" \
            --run-untagged="true" \
            --locked="false"
    fi

    log_ok "GitLab Runner registered successfully!"
}

print_credentials() {
    log_info "=== GitLab Credentials ==="
    local root_pass
    root_pass=$(get_root_password) || root_pass="<check .env>"
    local pat
    pat=$(get_pat) || pat="<create in UI>"

    echo ""
    echo "  URL:        http://${GITLAB_HOSTNAME}"
    echo "  Username:   root"
    echo "  Password:   ${root_pass}"
    echo "  SSH Port:   ${GITLAB_SSH_PORT}"
    echo "  PAT:        ${pat}"
    echo ""
    log_warn "Change the root password after first login!"
    echo ""
}

deploy_fresh() {
    log_info "=== Fresh GitLab Deployment ==="
    log_info "Deploy directory: ${DEPLOY_DIR}"

    mkdir -p "${DEPLOY_DIR}"
    log_ok "Directory created."

    if [ ! -f "${DEPLOY_DIR}/.env" ]; then
        log_info "Generating secure .env file..."
        local root_pass
        root_pass=$(generate_secure_password)

        cat > "${DEPLOY_DIR}/.env" <<ENVEOF
# GitLab Deployment Environment
# Generated: $(date -u '+%Y-%m-%d %H:%M:%S UTC')
# WARNING: This file contains secrets. Do not share.
GITLAB_VERSION=${GITLAB_VERSION}
GITLAB_RUNNER_VERSION=${RUNNER_VERSION}
GITLAB_HOSTNAME=${GITLAB_HOSTNAME}
GITLAB_HTTP_PORT=${GITLAB_HTTP_PORT}
GITLAB_SSH_PORT=${GITLAB_SSH_PORT}
GITLAB_ROOT_PASSWORD=${root_pass}
GITLAB_TIMEZONE=${GITLAB_TIMEZONE}
ENVEOF
        chmod 600 "${DEPLOY_DIR}/.env"
        log_ok ".env created with secure root password (chmod 600)."
    else
        log_info ".env already exists, reusing existing credentials."
    fi

    set -a
    source "${DEPLOY_DIR}/.env"
    set +a

    if [ ! -f "${DEPLOY_DIR}/docker-compose.yml" ]; then
        log_err "docker-compose.yml not found at ${DEPLOY_DIR}/docker-compose.yml"
        return 1
    fi

    log_info "Stopping any existing GitLab containers..."
    cd "${DEPLOY_DIR}"
    docker compose down 2>/dev/null || true
    log_ok "Cleanup complete."

    log_info "Pulling Docker images..."
    docker compose pull
    log_ok "Images pulled."

    log_info "Starting GitLab and Runner containers..."
    docker compose up -d
    log_ok "Containers started."

    wait_for_gitlab

    register_runner

    print_credentials

    log_info "=== Deployment Status ==="
    docker compose ps

    log_ok "=== GitLab Deployment Complete ==="
}

# ─── Main ─────────────────────────────────────────────────────────────────────
case "${1:-}" in
    --fresh)         deploy_fresh ;;
    --reconfigure)
        cd "${DEPLOY_DIR}"
        docker exec gitlab gitlab-ctl reconfigure
        log_ok "Reconfiguration complete."
        ;;
    --status)
        cd "${DEPLOY_DIR}"
        docker compose ps
        echo ""
        log_info "GitLab Health (inside container):"
        docker exec gitlab curl -sf http://localhost/-/health || log_warn "Health check failed"
        echo ""
        log_info "Runner Status:"
        docker exec gitlab-runner gitlab-runner verify 2>&1 || log_warn "Runner verify failed"
        ;;
    --stop)          cd "${DEPLOY_DIR}" && docker compose stop && log_ok "Stopped." ;;
    --start)         cd "${DEPLOY_DIR}" && docker compose start && log_ok "Started." ;;
    --update)
        cd "${DEPLOY_DIR}"
        docker compose pull && docker compose up -d
        wait_for_gitlab
        docker exec gitlab gitlab-ctl reconfigure
        log_ok "Update complete."
        ;;
    --register-runner) register_runner ;;
    --credentials)   print_credentials ;;
    --reset-password)
        log_info "Use reset_password.sh script to reset the root password."
        log_info "Or run: docker exec -it gitlab gitlab-rake 'gitlab:password:reset[root]'"
        ;;
    *)
        echo "GitLab CE 17.x + Runner Deployment Script"
        echo ""
        echo "Usage: $0 [OPTION]"
        echo ""
        echo "Options:"
        echo "  --fresh            Fresh deployment (stop existing, start new)"
        echo "  --reconfigure      Re-run GitLab reconfigure"
        echo "  --status           Show container status and health"
        echo "  --stop             Stop all containers"
        echo "  --start            Start all containers"
        echo "  --update           Pull latest images and restart"
        echo "  --register-runner  Register/re-register the GitLab Runner"
        echo "  --credentials      Show GitLab credentials"
        echo ""
        echo "Note: Health endpoints (/-/health etc.) only respond from inside"
        echo "      the container (localhost). Use docker exec for health checks."
        ;;
esac
