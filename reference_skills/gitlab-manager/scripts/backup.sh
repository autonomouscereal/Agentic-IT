#!/usr/bin/env bash
# backup.sh - GitLab Backup Management
#
# Usage: bash backup.sh [--create | --list | --restore BACKUP_ID | --config-backup]

set -euo pipefail

DEPLOY_DIR="${DEPLOY_DIR:-/opt/agentic-it/gitlab}"
BACKUP_DIR="/var/opt/gitlab/backups"

log_info() { echo "[INFO] $*"; }
log_ok()   { echo "[OK] $*"; }
log_err()  { echo "[ERROR] $*"; }

create_backup() {
    log_info "Creating GitLab backup..."
    log_info "This may take several minutes depending on data size."

    # Stop application to ensure consistent backup
    docker exec gitlab gitlab-ctl stop unicorn
    docker exec gitlab gitlab-ctl stop sidekiq

    # Create backup
    docker exec gitlab gitlab-backup create 2>&1

    # Restart services
    docker exec gitlab gitlab-ctl start unicorn
    docker exec gitlab gitlab-ctl start sidekiq

    # Show backup created
    local backup_file
    backup_file=$(docker exec gitlab ls -t /var/opt/gitlab/backups/*.tar 2>/dev/null | head -1)
    log_ok "Backup created: ${backup_file}"
}

list_backups() {
    echo "=== Available Backups ==="
    docker exec gitlab ls -lh /var/opt/gitlab/backups/*.tar 2>/dev/null || echo "No backups found."
}

restore_backup() {
    local backup_id="$1"
    log_warn "Restoring backup: ${backup_id}"
    log_warn "This will STOP all services and OVERWRITE current data!"
    log_info "Proceeding..."

    docker exec gitlab gitlab-ctl stop unicorn
    docker exec gitlab gitlab-ctl stop sidekiq

    docker exec gitlab gitlab-backup restore BACKUP="${backup_id}"

    docker exec gitlab gitlab-ctl start unicorn
    docker exec gitlab gitlab-ctl start sidekiq

    log_ok "Restore complete. Reconfiguring..."
    docker exec gitlab gitlab-ctl reconfigure
}

backup_config() {
    log_info "Backing up GitLab configuration..."
    local timestamp
    timestamp=$(date +%Y%m%d_%H%M%S)
    local backup_file="${DEPLOY_DIR}/config-backup-${timestamp}.tar.gz"

    docker exec gitlab tar czf "/var/opt/gitlab/backups/config-${timestamp}.tar.gz" \
        -C /etc/gitlab \
        gitlab-secrets.json \
        gitlab.rb \
        2>/dev/null

    log_ok "Config backup created inside container."
    log_info "To extract: docker exec gitlab tar xzf /var/opt/gitlab/backups/config-${timestamp}.tar.gz -C /tmp/"
}

case "${1:-}" in
    --create)
        create_backup
        ;;
    --list)
        list_backups
        ;;
    --restore)
        if [ -z "${2:-}" ]; then
            log_err "Backup ID required. Usage: $0 --restore BACKUP_ID"
            exit 1
        fi
        restore_backup "$2"
        ;;
    --config-backup)
        backup_config
        ;;
    *)
        echo "GitLab Backup Management"
        echo ""
        echo "Usage: $0 [OPTION]"
        echo ""
        echo "Options:"
        echo "  --create            Create a full GitLab backup"
        echo "  --list              List available backups"
        echo "  --restore BACKUP_ID Restore a specific backup"
        echo "  --config-backup     Backup configuration files (secrets, gitlab.rb)"
        ;;
esac
