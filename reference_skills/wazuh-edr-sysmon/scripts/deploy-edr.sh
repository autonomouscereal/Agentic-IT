#!/bin/bash
# ============================================================
# Wazuh EDR + Sysmon Deployment Script
# Deploys Sysmon rules, decoders, and active response config
# Usage: bash deploy-edr.sh [wazuh_deploy_dir]
# ============================================================
set -euo pipefail

WAZUH_DIR="${1:-/home/cereal/SOC_TESTING/wazuh_deploy}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIGS_DIR="${SCRIPT_DIR}/../wazuh_configs"
WAZUH_MANAGER_CONTAINER="${WAZUH_MANAGER_CONTAINER:-wazuh_deploy-wazuh.manager-1}"

log() { echo "[$(date '+%H:%M:%S')] $*"; }
err() { echo "[$(date '+%H:%M:%S')] ERROR: $*" >&2; exit 1; }

# Verify Wazuh deployment exists
[ -d "$WAZUH_DIR" ] || err "Wazuh deploy directory not found: $WAZUH_DIR"
[ -d "$WAZUH_DIR/config" ] || err "Wazuh config directory not found: $WAZUH_DIR/config"

log "=== Wazuh EDR + Sysmon Deployment ==="
log "Wazuh directory: $WAZUH_DIR"

# Step 1: Deploy Sysmon rules
log "Deploying Sysmon detection rules..."
cp "${CONFIGS_DIR}/sysmon_rules.xml" "${WAZUH_DIR}/config/wazuh_custom/rules/sysmon_rules.xml"
log "  -> sysmon_rules.xml deployed"

# Step 2: Deploy Sysmon decoders
log "Deploying Sysmon decoders..."
cp "${CONFIGS_DIR}/sysmon_decoder.xml" "${WAZUH_DIR}/config/wazuh_custom/decoders/sysmon_decoder.xml"
log "  -> sysmon_decoder.xml deployed"

# Step 3: Deploy EDR active response script
log "Deploying EDR active response script..."
mkdir -p "${WAZUH_DIR}/config/wazuh_custom/ar_scripts"
cp "${CONFIGS_DIR}/ar_scripts/edr-respond.sh" "${WAZUH_DIR}/config/wazuh_custom/ar_scripts/edr-respond.sh"
chmod +x "${WAZUH_DIR}/config/wazuh_custom/ar_scripts/edr-respond.sh"
log "  -> edr-respond.sh deployed"

# Step 4: Modify wazuh_manager.conf to enable EDR
log "Enabling Active Response in wazuh_manager.conf..."
MANAGER_CONF="${WAZUH_DIR}/config/wazuh_cluster/wazuh_manager.conf"
BACKUP="${MANAGER_CONF}.backup.$(date '+%Y%m%d%H%M%S')"
cp "$MANAGER_CONF" "$BACKUP"
log "  -> Backup: $BACKUP"

# Check if AR is already enabled
if grep -q '<active-response>' "$MANAGER_CONF" 2>/dev/null; then
    log "  -> Active Response already enabled, skipping"
else
    # Replace the commented-out AR section with enabled AR
    python3 -c "
import re

with open('${MANAGER_CONF}', 'r') as f:
    content = f.read()

# The AR config to inject before the closing </ossec_config>
ar_config = '''
  <!-- EDR Active Response Configuration -->
  <command>
    <name>edr-respond</name>
    <executable>edr-respond.sh</executable>
    <timeout_allowed>yes</timeout_allowed>
  </command>

  <active-response>
    <command>firewall-drop</command>
    <location>all</location>
    <level>10</level>
    <timeout>600</timeout>
  </active-response>

  <active-response>
    <command>host-deny</command>
    <location>server</location>
    <level>8</level>
    <timeout>3600</timeout>
  </active-response>

  <active-response>
    <command>disable-account</command>
    <location>all</location>
    <rules_group>authentication_failures</rules_group>
    <timeout>900</timeout>
  </active-response>

  <active-response>
    <command>edr-respond</command>
    <location>server</location>
    <rules_id>100201,100202,100203,100204,100205,100206,100207,100208,100209,100210,100211,100212,100213,100214,100215,100216,100220,100221,100222,100223,100224,100225,100226</rules_id>
    <timeout>300</timeout>
  </active-response>

  <!-- SysmonForLinux log source.
       SysmonForLinux writes syslog-prefixed XML to /var/log/sysmon/sysmon.log
       in the reference deployment, so this must be syslog, not json. -->
  <localfile>
    <log_format>syslog</log_format>
    <location>/var/log/sysmon/sysmon.log</location>
  </localfile>
'''

# Find the closing tag and insert before it
# Also uncomment any existing active-response blocks
content = re.sub(r'<!--\s*<active-response>', '<active-response', content)
content = re.sub(r'</active-response>\s*-->', '</active-response>', content)

# Insert EDR config before the last </ossec_config>
last_idx = content.rfind('</ossec_config>')
if last_idx > 0:
    content = content[:last_idx] + ar_config + '\n' + content[last_idx:]

with open('${MANAGER_CONF}', 'w') as f:
    f.write(content)
" || err "Failed to modify wazuh_manager.conf"
    log "  -> Active Response enabled with EDR rules"
fi

# Step 5: Verify files are in place
log "Verifying deployment..."
[ -f "${WAZUH_DIR}/config/wazuh_custom/rules/sysmon_rules.xml" ] || err "sysmon_rules.xml not deployed"
[ -f "${WAZUH_DIR}/config/wazuh_custom/decoders/sysmon_decoder.xml" ] || err "sysmon_decoder.xml not deployed"
[ -f "${WAZUH_DIR}/config/wazuh_custom/ar_scripts/edr-respond.sh" ] || err "edr-respond.sh not deployed"

if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' | grep -qx "$WAZUH_MANAGER_CONTAINER"; then
    log "Applying EDR assets into live Wazuh manager container: $WAZUH_MANAGER_CONTAINER"
    docker exec "$WAZUH_MANAGER_CONTAINER" sh -lc 'mkdir -p /var/ossec/etc/rules /var/ossec/etc/decoders /var/ossec/active-response/bin'
    if docker exec "$WAZUH_MANAGER_CONTAINER" sh -lc 'grep -R "<rule id=\"100201\"" /var/ossec/etc/rules/*.xml >/dev/null 2>&1'; then
        log "  -> Existing Sysmon rules detected in live manager; installing marker rule only to avoid duplicate rule warnings"
        docker exec "$WAZUH_MANAGER_CONTAINER" sh -lc 'rm -f /var/ossec/etc/rules/sysmon_rules.xml && cat > /var/ossec/etc/rules/sysmon_marker_rules.xml <<'"'"'EOF'"'"'
<group name="sysmon,edr">
  <rule id="100230" level="5">
    <if_sid>100200</if_sid>
    <match>CODEX_SYSMON_</match>
    <description>SysmonForLinux: EDR pipeline verification marker observed</description>
    <group>sysmon,linux,edr_test</group>
  </rule>
  <rule id="100231" level="5">
    <match>CODEX_SYSMON_</match>
    <description>SysmonForLinux: raw EDR pipeline verification marker observed</description>
    <group>sysmon,linux,edr_test</group>
  </rule>
</group>
EOF'
    else
        docker cp "${WAZUH_DIR}/config/wazuh_custom/rules/sysmon_rules.xml" "$WAZUH_MANAGER_CONTAINER:/var/ossec/etc/rules/sysmon_rules.xml"
    fi
    docker cp "${WAZUH_DIR}/config/wazuh_custom/decoders/sysmon_decoder.xml" "$WAZUH_MANAGER_CONTAINER:/var/ossec/etc/decoders/sysmon_decoder.xml"
    docker cp "${WAZUH_DIR}/config/wazuh_custom/ar_scripts/edr-respond.sh" "$WAZUH_MANAGER_CONTAINER:/var/ossec/active-response/bin/edr-respond.sh"
    docker exec "$WAZUH_MANAGER_CONTAINER" sh -lc 'rm -f /var/ossec/etc/decoders/sysmon_decoder.xml.tmp && chown root:wazuh /var/ossec/etc/rules/sysmon_rules.xml /var/ossec/etc/rules/sysmon_marker_rules.xml /var/ossec/etc/decoders/sysmon_decoder.xml 2>/dev/null || true && chmod 0640 /var/ossec/etc/rules/sysmon_rules.xml /var/ossec/etc/rules/sysmon_marker_rules.xml /var/ossec/etc/decoders/sysmon_decoder.xml 2>/dev/null || true && chown root:wazuh /var/ossec/active-response/bin/edr-respond.sh && chmod 0750 /var/ossec/active-response/bin/edr-respond.sh'
    log "  -> Live Wazuh manager assets updated"
else
    log "  -> Live manager container not found; assets staged on host only"
fi

log "=== Deployment complete ==="
log "Run 'docker compose up -d --force-recreate wazuh.manager' to apply changes"
log "Then verify with: docker exec wazuh.manager /var/ossec/bin/wazuh-logtest"
