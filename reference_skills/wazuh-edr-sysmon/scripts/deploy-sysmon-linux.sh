#!/bin/bash
# ============================================================
# SysmonForLinux Deployment Script
# Installs and configures SysmonForLinux for Wazuh integration
# Usage: bash deploy-sysmon-linux.sh [sysmon_config_path]
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SYSMON_CONFIG="${1:-${SCRIPT_DIR}/../configs/sysmon_config_linux.xml}"
SYSMON_LOG="/var/log/sysmon/sysmon.log"
SYSMON_VERSION="18.26.2"

log() { echo "[$(date '+%H:%M:%S')] $*"; }
err() { echo "[$(date '+%H:%M:%S')] ERROR: $*" >&2; exit 1; }

# Check if running as root
[ "$(id -u)" -eq 0 ] || err "This script must be run as root (use sudo)"

log "=== SysmonForLinux Deployment ==="

# Step 1: Install dependencies
log "Installing dependencies..."
apt-get update -qq
apt-get install -y -qq systemd jq rsyslog || err "Failed to install dependencies"

# Step 2: Download SysmonForLinux
log "Downloading SysmonForLinux v${SYSMON_VERSION}..."
SYSMON_DIR="/opt/sysmon"
mkdir -p "$SYSMON_DIR"

if [ ! -f "${SYSMON_DIR}/sysmon" ]; then
    curl -sL "https://github.com/microsoft/sysmon-for-linux/releases/download/${SYSMON_VERSION}/sysmon-${SYSMON_VERSION}.tar.gz" \
      -o "/tmp/sysmon.tar.gz" || err "Failed to download SysmonForLinux"
    tar -xzf "/tmp/sysmon.tar.gz" -C "/tmp/" || err "Failed to extract SysmonForLinux"
    cp "/tmp/sysmon-${SYSMON_VERSION}/sysmon" "${SYSMON_DIR}/sysmon"
    rm -f "/tmp/sysmon.tar.gz" "/tmp/sysmon-${SYSMON_VERSION}"
    rm -rf "/tmp/sysmon-${SYSMON_VERSION}"
    chmod +x "${SYSMON_DIR}/sysmon"
    log "  -> SysmonForLinux installed at ${SYSMON_DIR}/sysmon"
else
    log "  -> SysmonForLinux already installed"
fi

# Step 3: Deploy configuration
if [ -f "$SYSMON_CONFIG" ]; then
    cp "$SYSMON_CONFIG" "${SYSMON_DIR}/sysmon_config.xml"
    log "  -> Sysmon config deployed"
else
    log "  -> Using existing config at ${SYSMON_DIR}/sysmon_config.xml"
fi

# Step 4: Install or update the Sysmon service and configuration.
log "Configuring SysmonForLinux service..."
install -d -m 0775 -o syslog -g adm "$(dirname "$SYSMON_LOG")"
touch "$SYSMON_LOG"
chown syslog:adm "$SYSMON_LOG"
chmod 0664 "$SYSMON_LOG"

SYSMON_UNINSTALL_LOG="$(mktemp /var/tmp/sysmon-uninstall.XXXXXX.log)"
SYSMON_INSTALL_LOG="$(mktemp /var/tmp/sysmon-install.XXXXXX.log)"
systemctl stop sysmon >/dev/null 2>&1 || true
"${SYSMON_DIR}/sysmon" -u force >"$SYSMON_UNINSTALL_LOG" 2>&1 || true
"${SYSMON_DIR}/sysmon" -i "${SYSMON_DIR}/sysmon_config.xml" >"$SYSMON_INSTALL_LOG" 2>&1 || {
    cat "$SYSMON_INSTALL_LOG" >&2
    err "Failed to install SysmonForLinux service"
}

systemctl daemon-reload
systemctl enable sysmon >/dev/null 2>&1 || true
systemctl restart sysmon || {
    systemctl status sysmon --no-pager -l >&2 || true
    err "SysmonForLinux failed to restart"
}
log "  -> SysmonForLinux systemd service installed/updated and started"

# Step 4.5: Forward Sysmon journald/syslog records into the hot file Wazuh reads.
# Keep this rule early so a broader stop rule cannot swallow Sysmon events first.
rm -f /etc/rsyslog.d/99-sysmon-forward.conf
cat > /etc/rsyslog.d/10-sysmon-forward.conf << EOF
if (\$programname == 'sysmon') then {
  action(type="omfile" file="$SYSMON_LOG")
  stop
}
EOF
systemctl restart rsyslog
log "  -> rsyslog Sysmon file forwarding installed"

# Step 4.6: Install a small logrotate policy so Wazuh does not get stuck behind
# an oversized historical Sysmon file in demo or lab environments.
cat > /etc/logrotate.d/sysmon-edr << EOF
$SYSMON_LOG {
    daily
    rotate 7
    size 256M
    missingok
    notifempty
    copytruncate
    compress
}
EOF
log "  -> Sysmon logrotate policy installed for $SYSMON_LOG"

# Step 5: Verify
sleep 2
if systemctl is-active --quiet sysmon; then
    log "  -> SysmonForLinux is RUNNING"
else
    err "SysmonForLinux failed to start"
fi

# Step 6: Verify log generation
sleep 5
if [ -f "$SYSMON_LOG" ] || journalctl -u sysmon --no-pager -n 5 &>/dev/null; then
    log "  -> SysmonForLinux is generating events"
else
    log "  -> WARNING: No log events yet, check journalctl -u sysmon"
fi

log "=== SysmonForLinux deployment complete ==="
log "Log location: $SYSMON_LOG"
log "Verify: journalctl -u sysmon -f"
