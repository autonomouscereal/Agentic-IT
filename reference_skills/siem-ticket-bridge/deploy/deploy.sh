#!/bin/bash
# SIEM-Ticketing Bridge — One-shot deployment script
# Deploys the bridge as a systemd service on the AI Server.
#
# Usage: bash deploy.sh [--test]
#   --test  Run in test mode (no persistent service, single poll)

set -euo pipefail

DEPLOY_DIR="/home/cereal/SOC_TESTING/siem-ticket-bridge"
LOG_DIR="/var/log/siem-ticket-bridge"
STATE_DIR="/var/lib/siem-ticket-bridge"
ENV_FILE="${DEPLOY_DIR}/.env"
SERVICE_FILE="${DEPLOY_DIR}/deploy/systemd/siem-ticket-bridge.service"
LOGROTATE_FILE="${DEPLOY_DIR}/deploy/logrotate/siem-ticket-bridge"
SUPPRESSION_EXAMPLE="${DEPLOY_DIR}/deploy/suppression_rules.example.json"
SUPPRESSION_DIR="/etc/siem-ticket-bridge"
SUPPRESSION_FILE="${SUPPRESSION_DIR}/suppression_rules.json"

TEST_MODE=false
if [[ "${1:-}" == "--test" ]]; then
    TEST_MODE=true
fi

echo "=== SIEM-Ticketing Bridge Deployment ==="
echo "Deploy directory: ${DEPLOY_DIR}"
echo "Test mode: ${TEST_MODE}"

# Create directories
echo "[1/6] Creating directories..."
mkdir -p "${LOG_DIR}" "${STATE_DIR}" "${SUPPRESSION_DIR}"
chown cereal:adm "${LOG_DIR}" 2>/dev/null || true
chmod 0750 "${LOG_DIR}" 2>/dev/null || true
if [ ! -f "${SUPPRESSION_FILE}" ] && [ -f "${SUPPRESSION_EXAMPLE}" ]; then
    cp "${SUPPRESSION_EXAMPLE}" "${SUPPRESSION_FILE}"
    chmod 0640 "${SUPPRESSION_FILE}"
fi

# Install Python dependencies (stdlib only, no pip needed)
echo "[2/6] Checking Python..."
python3 --version

# Validate .env file exists
echo "[3/6] Validating configuration..."
if [ ! -f "${ENV_FILE}" ]; then
    echo "ERROR: .env file not found at ${ENV_FILE}"
    echo "Copy .env.example to .env and fill in credentials."
    exit 1
fi

# Source env for validation
set -a
source "${ENV_FILE}"
set +a

# Check required variables
REQUIRED_VARS=("BRIDGE_SIEM_TYPE" "BRIDGE_SIEM_HOST" "BRIDGE_TICKETING_TYPE" "BRIDGE_TICKETING_HOST")
MISSING=0
for var in "${REQUIRED_VARS[@]}"; do
    if [ -z "${!var:-}" ]; then
        echo "WARNING: ${var} is not set in .env"
        MISSING=1
    fi
done

if [ "${MISSING}" -eq 1 ]; then
    echo "ERROR: Required environment variables are missing. Check .env file."
    exit 1
fi

echo "  SIEM type: ${BRIDGE_SIEM_TYPE}"
echo "  SIEM host: ${BRIDGE_SIEM_HOST}"
echo "  Ticketing type: ${BRIDGE_TICKETING_TYPE}"
echo "  Ticketing host: ${BRIDGE_TICKETING_HOST}"

# Run connectivity test
echo "[4/6] Testing connectivity..."
cd "${DEPLOY_DIR}"
set -a
source "${ENV_FILE}"
set +a

if python3 -m siem_ticket_bridge.bridge --test-connection; then
    echo "  Connectivity: OK"
else
    echo "  WARNING: Connectivity test failed. Bridge will retry on each poll cycle."
fi

# Test single poll
echo "[5/6] Running test poll..."
if python3 -m siem_ticket_bridge.bridge --once; then
    echo "  Test poll: OK"
else
    echo "  WARNING: Test poll returned errors. Check logs."
fi

# Install systemd service (skip in test mode)
echo "[6/6] Installing service..."
if [ "${TEST_MODE}" == "true" ]; then
    echo "  Test mode: skipping systemd service installation"
    echo "  Bridge deployed to ${DEPLOY_DIR}"
    echo "  Run manually: cd ${DEPLOY_DIR} && source .env && python3 -m siem_ticket_bridge.bridge"
else
    if [ -f "${LOGROTATE_FILE}" ]; then
        cp "${LOGROTATE_FILE}" /etc/logrotate.d/siem-ticket-bridge
        chmod 0644 /etc/logrotate.d/siem-ticket-bridge
    fi

    # Update service file with correct paths
    sed "s|{{DEPLOY_DIR}}|${DEPLOY_DIR}|g; s|{{LOG_DIR}}|${LOG_DIR}|g; s|{{USER}}|cereal|g" \
        "${SERVICE_FILE}" > /etc/systemd/system/siem-ticket-bridge.service

    systemctl daemon-reload
    systemctl enable siem-ticket-bridge
    systemctl restart siem-ticket-bridge

    echo "  Service installed and started"
    echo "  Status: systemctl status siem-ticket-bridge"
    echo "  Logs: journalctl -u siem-ticket-bridge -f"
fi

echo ""
echo "=== Deployment Complete ==="
