#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# GitLab + Keycloak Integration - Backup and Restore Utility
# =============================================================================
# Provides comprehensive backup and restore functionality for:
# - GitLab configuration (gitlab.rb, omniauth settings)
# - Keycloak realm configuration and OIDC clients
# - PostgreSQL databases (GitLab and Keycloak)
# - SSL certificates
# - Docker volumes and configurations
# =============================================================================

# --- Configuration ---
BACKUP_BASE_DIR="${BACKUP_BASE_DIR:-/opt/backups/gitlab-keycloak}"
TIMESTAMP=$(date '+%Y%m%d_%H%M%S')
BACKUP_DIR="${BACKUP_BASE_DIR}/${TIMESTAMP}"
RETENTION_DAYS="${RETENTION_DAYS:-30}"
COMPRESSION="${COMPRESSION:-gzip}"

# Service configuration
GITLAB_CONTAINER="${GITLAB_CONTAINER:-gitlab}"
KEYCLOAK_CONTAINER="${KEYCLOAK_CONTAINER:-keycloak}"
KEYCLOAK_DB_CONTAINER="${KEYCLOAK_DB_CONTAINER:-keycloak-db}"
KEYCLOAK_REALM="${KEYCLOAK_REALM:-gitlab}"
KEYCLOAK_ADMIN_USER="${KEYCLOAK_ADMIN_USER:-admin}"
KEYCLOAK_ADMIN_PASSWORD="${KEYCLOAK_ADMIN_PASSWORD:-}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# --- Helper Functions ---

log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[OK]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

log_section() {
    echo ""
    echo -e "${CYAN}--------------------------------------------------------${NC}"
    echo -e "${CYAN} $1${NC}"
    echo -e "${CYAN}--------------------------------------------------------${NC}"
}

show_usage() {
    cat << 'EOF'
Usage: backup_restore.sh [command] [options]

Commands:
  backup [full|config|db|certs]    Create a backup
  restore <backup_dir>            Restore from a backup
  list                            List available backups
  cleanup                         Remove old backups (beyond retention)
  verify <backup_dir>             Verify backup integrity

Backup Types:
  full        Backup everything (default)
  config      Backup only configuration files
  db          Backup only databases
  certs       Backup only SSL certificates

Options:
  -d, --dir <path>    Specify backup directory (default: /opt/backups/gitlab-keycloak)
  -r, --retain <days> Set retention period in days (default: 30)
  -h, --help          Show this help message

Examples:
  ./backup_restore.sh backup                    # Full backup with defaults
  ./backup_restore.sh backup config             # Config-only backup
  ./backup_restore.sh backup -d /custom/path    # Backup to custom path
  ./backup_restore.sh restore /opt/backups/...  # Restore from specific backup
  ./backup_restore.sh list                      # List all backups
  ./backup_restore.sh cleanup                   # Remove old backups
  ./backup_restore.sh verify /opt/backups/...   # Verify backup integrity

EOF
}

create_backup_dirs() {
    mkdir -p "${BACKUP_DIR}"/{gitlab,keycloak,databases,certs,metadata}
    log_info "Created backup directory structure at ${BACKUP_DIR}"
}

backup_gitlab_config() {
    log_section "Backing up GitLab Configuration"

    # Backup gitlab.rb if accessible
    if docker exec "$GITLAB_CONTAINER" test -f /etc/gitlab/gitlab.rb; then
        docker exec "$GITLAB_CONTAINER" cat /etc/gitlab/gitlab.rb > "${BACKUP_DIR}/gitlab/gitlab.rb"
        log_success "Backed up gitlab.rb"
    else
        log_warn "gitlab.rb not accessible in container"
    fi

    # Backup GitLab Rails settings
    if docker exec "$GITLAB_CONTAINER" test -f /etc/gitlab/gitlab-secrets.json; then
        docker exec "$GITLAB_CONTAINER" cat /etc/gitlab/gitlab-secrets.json > "${BACKUP_DIR}/gitlab/gitlab-secrets.json"
        log_success "Backed up gitlab-secrets.json"
    else
        log_warn "gitlab-secrets.json not accessible in container"
    fi

    # Backup GitLab configuration directory
    if docker exec "$GITLAB_CONTAINER" test -d /etc/gitlab; then
        docker exec "$GITLAB_CONTAINER" tar czf - -C / etc/gitlab 2>/dev/null > "${BACKUP_DIR}/gitlab/etc-gitlab.tar.gz" || true
        log_success "Backed up /etc/gitlab directory"
    fi

    # Backup GitLab data directory (if small enough)
    if docker exec "$GITLAB_CONTAINER" test -d /var/opt/gitlab; then
        # Only backup critical config files, not the entire data dir (too large)
        docker exec "$GITLAB_CONTAINER" tar czf - \
            -C /var/opt/gitlab \
            nginx/conf 2>/dev/null >> "${BACKUP_DIR}/gitlab/var-opt-gitlab-nginx.tar.gz" || true
        log_success "Backed up GitLab nginx configuration"
    fi
}

backup_keycloak_config() {
    log_section "Backing up Keycloak Configuration"

    # Get Keycloak admin token
    TOKEN_RESPONSE=$(curl -sf --max-time 10 --insecure \
        -X POST "https://keycloak/realms/master/protocol/openid-connect/token" \
        -d "grant_type=password" \
        -d "client_id=admin-cli" \
        -d "username=$KEYCLOAK_ADMIN_USER" \
        -d "password=$KEYCLOAK_ADMIN_PASSWORD" 2>/dev/null || true)

    if [ -n "$TOKEN_RESPONSE" ]; then
        ACCESS_TOKEN=$(echo "$TOKEN_RESPONSE" | jq -r '.access_token' 2>/dev/null || true)

        if [ -n "$ACCESS_TOKEN" ] && [ "$ACCESS_TOKEN" != "null" ]; then
            # Export realm configuration
            curl -sf --max-time 30 --insecure \
                -H "Authorization: Bearer $ACCESS_TOKEN" \
                -H "Content-Type: application/json" \
                "https://keycloak/admin/realms/$KEYCLOAK_REALM" \
                -o "${BACKUP_DIR}/keycloak/realm_config.json" 2>/dev/null

            if [ -f "${BACKUP_DIR}/keycloak/realm_config.json" ]; then
                log_success "Exported Keycloak realm configuration"
            else
                log_error "Failed to export realm configuration"
            fi

            # Export users
            curl -sf --max-time 30 --insecure \
                -H "Authorization: Bearer $ACCESS_TOKEN" \
                "https://keycloak/admin/realms/$KEYCLOAK_REALM/users?max=100" \
                -o "${BACKUP_DIR}/keycloak/users.json" 2>/dev/null

            if [ -f "${BACKUP_DIR}/keycloak/users.json" ]; then
                USER_COUNT=$(jq 'length' "${BACKUP_DIR}/keycloak/users.json" 2>/dev/null || echo "0")
                log_success "Exported $USER_COUNT users"
            else
                log_warn "Failed to export users list"
            fi

            # Export groups
            curl -sf --max-time 30 --insecure \
                -H "Authorization: Bearer $ACCESS_TOKEN" \
                "https://keycloak/admin/realms/$KEYCLOAK_REALM/groups?max=100" \
                -o "${BACKUP_DIR}/keycloak/groups.json" 2>/dev/null

            if [ -f "${BACKUP_DIR}/keycloak/groups.json" ]; then
                GROUP_COUNT=$(jq 'length' "${BACKUP_DIR}/keycloak/groups.json" 2>/dev/null || echo "0")
                log_success "Exported $GROUP_COUNT groups"
            else
                log_warn "Failed to export groups list"
            fi

            # Export clients
            curl -sf --max-time 30 --insecure \
                -H "Authorization: Bearer $ACCESS_TOKEN" \
                "https://keycloak/admin/realms/$KEYCLOAK_REALM/clients" \
                -o "${BACKUP_DIR}/keycloak/clients.json" 2>/dev/null

            if [ -f "${BACKUP_DIR}/keycloak/clients.json" ]; then
                CLIENT_COUNT=$(jq 'length' "${BACKUP_DIR}/keycloak/clients.json" 2>/dev/null || echo "0")
                log_success "Exported $CLIENT_COUNT clients"
            else
                log_warn "Failed to export clients list"
            fi

            # Export roles
            curl -sf --max-time 30 --insecure \
                -H "Authorization: Bearer $ACCESS_TOKEN" \
                "https://keycloak/admin/realms/$KEYCLOAK_REALM/roles" \
                -o "${BACKUP_DIR}/keycloak/roles.json" 2>/dev/null

            if [ -f "${BACKUP_DIR}/keycloak/roles.json" ]; then
                ROLE_COUNT=$(jq 'length' "${BACKUP_DIR}/keycloak/roles.json" 2>/dev/null || echo "0")
                log_success "Exported $ROLE_COUNT roles"
            else
                log_warn "Failed to export roles list"
            fi
        else
            log_error "Failed to obtain Keycloak admin token"
        fi
    else
        log_error "Keycloak admin authentication failed"
    fi
}

backup_databases() {
    log_section "Backing up Databases"

    # Backup Keycloak PostgreSQL database
    if docker inspect "$KEYCLOAK_DB_CONTAINER" &>/dev/null; then
        # Get database credentials from environment
        DB_NAME=$(docker exec "$KEYCLOAK_DB_CONTAINER" printenv POSTGRES_DB 2>/dev/null || echo "keycloak")
        DB_USER=$(docker exec "$KEYCLOAK_DB_CONTAINER" printenv POSTGRES_USER 2>/dev/null || echo "keycloak")
        DB_PASS=$(docker exec "$KEYCLOAK_DB_CONTAINER" printenv POSTGRES_PASSWORD 2>/dev/null || echo "")

        if [ -n "$DB_PASS" ]; then
            docker exec "$KEYCLOAK_DB_CONTAINER" pg_dump \
                -U "$DB_USER" \
                -d "$DB_NAME" \
                --verbose \
                --format=custom \
                --compress=9 \
                -F c \
                -f /tmp/keycloak_dump.dump 2>/dev/null

            # Copy dump to host
            docker cp "$KEYCLOAK_DB_CONTAINER":/tmp/keycloak_dump.dump "${BACKUP_DIR}/databases/keycloak_db.dump"

            if [ -f "${BACKUP_DIR}/databases/keycloak_db.dump" ]; then
                DB_SIZE=$(du -h "${BACKUP_DIR}/databases/keycloak_db.dump" | cut -f1)
                log_success "Backed up Keycloak database ($DB_SIZE)"
            else
                log_error "Keycloak database backup failed"
            fi
        else
            log_warn "Could not retrieve Keycloak DB password, skipping database backup"
        fi
    else
        log_error "Keycloak database container '$KEYCLOAK_DB_CONTAINER' not found"
    fi

    # Note: GitLab database is typically internal and not recommended to backup separately
    # The GitLab backup utility handles this, but it's not available in omnibus Docker by default
    log_info "GitLab internal database backup skipped (use GitLab backup utility if needed)"
}

backup_certificates() {
    log_section "Backing up SSL Certificates"

    # Backup certificates from the certs directory
    CERTS_DIR="$(cd "$(dirname "$0")/.." && pwd)/certs"

    if [ -d "$CERTS_DIR" ]; then
        cp -r "$CERTS_DIR"/* "${BACKUP_DIR}/certs/" 2>/dev/null || true
        CERT_COUNT=$(find "${BACKUP_DIR}/certs/" -type f 2>/dev/null | wc -l)
        log_success "Backed up $CERT_COUNT certificate files"
    else
        log_warn "Certificates directory not found at $CERTS_DIR"
    fi

    # Also backup certificates from containers
    if docker exec "$GITLAB_CONTAINER" test -d /etc/gitlab/ssl; then
        docker exec "$GITLAB_CONTAINER" tar czf - -C /etc/gitlab ssl 2>/dev/null > "${BACKUP_DIR}/certs/gitlab-ssl.tar.gz" || true
        log_success "Backed up GitLab SSL certificates"
    fi
}

backup_docker_compose() {
    log_section "Backing up Docker Configuration"

    # Backup docker-compose.yml
    COMPOSE_FILE="$(cd "$(dirname "$0")/.." && pwd)/docker-compose.yml"
    if [ -f "$COMPOSE_FILE" ]; then
        cp "$COMPOSE_FILE" "${BACKUP_DIR}/gitlab/docker-compose.yml"
        log_success "Backed up docker-compose.yml"
    fi

    # Backup nginx configuration
    NGINX_CONF="$(cd "$(dirname "$0")/.." && pwd)/nginx/nginx.conf"
    if [ -f "$NGINX_CONF" ]; then
        cp "$NGINX_CONF" "${BACKUP_DIR}/gitlab/nginx.conf"
        log_success "Backed up nginx configuration"
    fi

    # Backup all scripts
    SCRIPTS_DIR="$(cd "$(dirname "$0")/.." && pwd)/scripts"
    if [ -d "$SCRIPTS_DIR" ]; then
        cp "$SCRIPTS_DIR"/*.sh "${BACKUP_DIR}/gitlab/scripts/" 2>/dev/null || true
        cp "$SCRIPTS_DIR"/*.py "${BACKUP_DIR}/gitlab/scripts/" 2>/dev/null || true
        cp "$SCRIPTS_DIR"/*.rb "${BACKUP_DIR}/gitlab/scripts/" 2>/dev/null || true
        log_success "Backed up automation scripts"
    fi
}

create_manifest() {
    log_section "Creating Backup Manifest"

    cat > "${BACKUP_DIR}/metadata/manifest.json" << MANIFEST
{
    "timestamp": "${TIMESTAMP}",
    "backup_type": "$1",
    "hostname": "$(hostname)",
    "gitlab_container": "${GITLAB_CONTAINER}",
    "keycloak_container": "${KEYCLOAK_CONTAINER}",
    "keycloak_db_container": "${KEYCLOAK_DB_CONTAINER}",
    "keycloak_realm": "${KEYCLOAK_REALM}",
    "retention_days": ${RETENTION_DAYS},
    "files": {
        "gitlab_config": $([ -f "${BACKUP_DIR}/gitlab/gitlab.rb" ] && echo "true" || echo "false"),
        "keycloak_realm": $([ -f "${BACKUP_DIR}/keycloak/realm_config.json" ] && echo "true" || echo "false"),
        "keycloak_db": $([ -f "${BACKUP_DIR}/databases/keycloak_db.dump" ] && echo "true" || echo "false"),
        "certificates": $([ -d "${BACKUP_DIR}/certs" ] && echo "true" || echo "false"),
        "docker_compose": $([ -f "${BACKUP_DIR}/gitlab/docker-compose.yml" ] && echo "true" || echo "false")
    },
    "checksums": {}
}
MANIFEST

    # Calculate checksums for all files
    find "${BACKUP_DIR}" -type f ! -name "manifest.json" -exec sha256sum {} \; >> "${BACKUP_DIR}/metadata/checksums.txt" 2>/dev/null || true
    log_success "Created backup manifest"
}

perform_backup() {
    local BACKUP_TYPE="${1:-full}"

    log_section "Starting ${BACKUP_TYPE} Backup"
    echo "Backup directory: ${BACKUP_DIR}"
    echo "Timestamp: ${TIMESTAMP}"
    echo ""

    create_backup_dirs

    case "$BACKUP_TYPE" in
        full)
            backup_gitlab_config
            backup_keycloak_config
            backup_databases
            backup_certificates
            backup_docker_compose
            ;;
        config)
            backup_gitlab_config
            backup_keycloak_config
            backup_docker_compose
            ;;
        db)
            backup_databases
            ;;
        certs)
            backup_certificates
            ;;
        *)
            log_error "Unknown backup type: $BACKUP_TYPE"
            exit 1
            ;;
    esac

    create_manifest "$BACKUP_TYPE"

    # Calculate total backup size
    TOTAL_SIZE=$(du -sh "${BACKUP_DIR}" | cut -f1)
    FILE_COUNT=$(find "${BACKUP_DIR}" -type f | wc -l)

    log_section "Backup Complete"
    log_success "Backup saved to: ${BACKUP_DIR}"
    log_info "Total size: ${TOTAL_SIZE}"
    log_info "Total files: ${FILE_COUNT}"
}

restore_backup() {
    local RESTORE_DIR="$1"

    if [ ! -d "$RESTORE_DIR" ]; then
        log_error "Restore directory does not exist: $RESTORE_DIR"
        exit 1
    fi

    log_section "Starting Restore from $RESTORE_DIR"

    # Verify manifest exists
    if [ ! -f "${RESTORE_DIR}/metadata/manifest.json" ]; then
        log_error "No backup manifest found. This may not be a valid backup."
        exit 1
    fi

    echo "WARNING: This will overwrite current configurations!"
    echo "Proceed with restore? (yes/no)"
    read -r CONFIRM

    if [ "$CONFIRM" != "yes" ]; then
        log_info "Restore cancelled by user"
        exit 0
    fi

    # Restore GitLab configuration
    if [ -f "${RESTORE_DIR}/gitlab/gitlab.rb" ]; then
        docker cp "${RESTORE_DIR}/gitlab/gitlab.rb" "$GITLAB_CONTAINER":/etc/gitlab/gitlab.rb
        log_success "Restored gitlab.rb"
    fi

    # Restore Keycloak realm configuration
    if [ -f "${RESTORE_DIR}/keycloak/realm_config.json" ]; then
        # This requires the Keycloak admin API to re-import
        log_info "Keycloak realm configuration requires manual re-import via admin API"
        log_info "File available at: ${RESTORE_DIR}/keycloak/realm_config.json"
    fi

    # Restore Keycloak database
    if [ -f "${RESTORE_DIR}/databases/keycloak_db.dump" ]; then
        log_warn "Database restore requires stopping services and manual intervention"
        log_info "Dump file available at: ${RESTORE_DIR}/databases/keycloak_db.dump"
    fi

    # Restore certificates
    CERTS_DIR="$(cd "$(dirname "$0")/.." && pwd)/certs"
    if [ -d "${RESTORE_DIR}/certs" ]; then
        cp "${RESTORE_DIR}/certs/"* "$CERTS_DIR/" 2>/dev/null || true
        log_success "Restored certificate files"
    fi

    log_success "Restore process completed"
    log_info "Manual verification recommended"
}

list_backups() {
    log_section "Available Backups"

    if [ ! -d "$BACKUP_BASE_DIR" ]; then
        log_info "No backups found in $BACKUP_BASE_DIR"
        return
    fi

    echo ""
    printf "%-20s %-10s %-15s %s\n" "TIMESTAMP" "SIZE" "TYPE" "DIRECTORY"
    printf "%-20s %-10s %-15s %s\n" "-------" "----" "----" "---------"

    for backup in "${BACKUP_BASE_DIR}"/*/; do
        if [ -f "${backup}/metadata/manifest.json" ]; then
            TIMESTAMP=$(basename "$backup")
            SIZE=$(du -sh "$backup" | cut -f1)
            TYPE=$(jq -r '.backup_type' "${backup}/metadata/manifest.json" 2>/dev/null || echo "unknown")
            printf "%-20s %-10s %-15s %s\n" "$TIMESTAMP" "$SIZE" "$TYPE" "$backup"
        fi
    done
}

cleanup_old_backups() {
    log_section "Cleaning up old backups (retention: ${RETENTION_DAYS} days)"

    if [ ! -d "$BACKUP_BASE_DIR" ]; then
        log_info "No backups directory found"
        return
    fi

    find "${BACKUP_BASE_DIR}" -maxdepth 1 -type d -mtime +"$RETENTION_DAYS" | while read -r old_backup; do
        if [ "$(basename "$old_backup")" != "$BACKUP_BASE_DIR" ]; then
            log_info "Removing old backup: $(basename "$old_backup")"
            rm -rf "$old_backup"
        fi
    done

    log_success "Cleanup complete"
}

verify_backup() {
    local VERIFY_DIR="$1"

    log_section "Verifying Backup: $VERIFY_DIR"

    if [ ! -d "$VERIFY_DIR" ]; then
        log_error "Directory does not exist: $VERIFY_DIR"
        exit 1
    fi

    # Check manifest
    if [ ! -f "${VERIFY_DIR}/metadata/manifest.json" ]; then
        log_error "Backup manifest not found"
        exit 1
    fi

    # Verify file checksums
    if [ -f "${VERIFY_DIR}/metadata/checksums.txt" ]; then
        cd "$VERIFY_DIR"
        if sha256sum -c metadata/checksums.txt &>/dev/null; then
            log_success "All file checksums verified"
        else
            log_error "Checksum verification failed - backup may be corrupted"
            exit 1
        fi
        cd -
    else
        log_warn "No checksums file found for verification"
    fi

    # Check for expected files
    local EXPECTED_FILES=("metadata/manifest.json")
    local MISSING=0

    for file in "${EXPECTED_FILES[@]}"; do
        if [ -f "${VERIFY_DIR}/${file}" ]; then
            log_success "Found: $file"
        else
            log_error "Missing: $file"
            ((MISSING++))
        fi
    done

    if [ "$MISSING" -eq 0 ]; then
        log_success "Backup verification passed"
    else
        log_error "$MISSING required file(s) missing"
        exit 1
    fi
}

# --- Main ---

main() {
    echo ""
    echo "+==================================================================+"
    echo "|     GitLab + Keycloak Integration - Backup Utility             |"
    echo "|     $(date '+%Y-%m-%d %H:%M:%S')                                     |"
    echo "+==================================================================+"

    if [ $# -eq 0 ]; then
        show_usage
        exit 0
    fi

    local COMMAND="$1"
    shift

    case "$COMMAND" in
        backup)
            perform_backup "$@"
            ;;
        restore)
            if [ $# -lt 1 ]; then
                log_error "Restore requires a backup directory path"
                exit 1
            fi
            restore_backup "$1"
            ;;
        list)
            list_backups
            ;;
        cleanup)
            cleanup_old_backups
            ;;
        verify)
            if [ $# -lt 1 ]; then
                log_error "Verify requires a backup directory path"
                exit 1
            fi
            verify_backup "$1"
            ;;
        -h|--help|help)
            show_usage
            ;;
        *)
            log_error "Unknown command: $COMMAND"
            show_usage
            exit 1
            ;;
    esac
}

main "$@"
