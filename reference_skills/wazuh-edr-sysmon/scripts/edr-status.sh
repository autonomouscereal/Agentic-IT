#!/bin/bash
# ============================================================
# EDR System Health Check
# Checks all components: Wazuh, Sysmon, Bridge, iTop
# Usage: bash edr-status.sh
# ============================================================

WAZUH_DIR="/opt/agentic-it/SOC_TESTING/wazuh_deploy"
PASS=0
FAIL=0
WARN=0

check() {
    local name="$1"
    local result="$2"
    if [ "$result" -eq 0 ]; then
        echo "[PASS] $name"
        ((PASS++))
    elif [ "$result" -eq 1 ]; then
        echo "[WARN] $name"
        ((WARN++))
    else
        echo "[FAIL] $name"
        ((FAIL++))
    fi
}

echo "=========================================="
echo " EDR System Health Check"
echo " $(date)"
echo "=========================================="
echo ""

# 1. Wazuh containers
echo "--- Wazuh SIEM ---"
cd "$WAZUH_DIR" 2>/dev/null || { echo "[FAIL] Wazuh deploy dir missing"; exit 1; }

docker compose ps --format json 2>/dev/null | grep -q "Up" && rc=0 || rc=2
check "Wazuh containers running" "$rc"

# 2. Wazuh API
curl -sk --connect-timeout 5 -o /dev/null -w "%{http_code}" \
  "https://127.0.0.1:26500/" 2>/dev/null | grep -q "200\|401" && rc=0 || rc=2
check "Wazuh Manager API responsive" "$rc"

# 3. Wazuh Indexer
curl -sk --connect-timeout 5 -o /dev/null -w "%{http_code}" \
  "https://127.0.0.1:26920/" 2>/dev/null | grep -q "200\|401" && rc=0 || rc=2
check "Wazuh Indexer responsive" "$rc"

# 4. Active Response enabled
grep -q '<active-response>' "${WAZUH_DIR}/config/wazuh_cluster/wazuh_manager.conf" 2>/dev/null && rc=0 || rc=1
check "Active Response enabled in config" "$rc"

# 5. Sysmon rules loaded
[ -f "${WAZUH_DIR}/config/wazuh_custom/rules/sysmon_rules.xml" ] && rc=0 || rc=1
check "Sysmon rules file present" "$rc"

# 6. Sysmon decoders loaded
[ -f "${WAZUH_DIR}/config/wazuh_custom/decoders/sysmon_decoder.xml" ] && rc=0 || rc=1
check "Sysmon decoders file present" "$rc"

# 7. EDR AR script
[ -f "${WAZUH_DIR}/config/wazuh_custom/ar_scripts/edr-respond.sh" ] && rc=0 || rc=1
check "EDR AR script present" "$rc"

echo ""
echo "--- SysmonForLinux ---"
systemctl is-active --quiet sysmon 2>/dev/null && rc=0 || rc=2
check "SysmonForLinux service running" "$rc"

echo ""
echo "--- SIEM-Ticketing Bridge ---"
systemctl is-active --quiet siem-ticket-bridge 2>/dev/null && rc=0 || rc=1
check "Bridge service running" "$rc"

[ -f "/var/lib/siem-ticket-bridge/state.json" ] && rc=0 || rc=1
check "Bridge state file exists" "$rc"

echo ""
echo "--- iTop ITSM ---"
curl -sk --connect-timeout 5 -o /dev/null -w "%{http_code}" \
  "http://127.0.0.1:25432/" 2>/dev/null | grep -q "200\|302" && rc=0 || rc=2
check "iTop web interface responsive" "$rc"

echo ""
echo "--- Summary ---"
echo "PASS: $PASS | WARN: $WARN | FAIL: $FAIL"

if [ "$FAIL" -gt 0 ]; then
    exit 1
fi
exit 0
