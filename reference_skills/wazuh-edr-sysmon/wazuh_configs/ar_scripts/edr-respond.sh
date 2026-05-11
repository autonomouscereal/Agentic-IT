#!/bin/bash
# ============================================================
# EDR Active Response Script for Wazuh
# Receives alert JSON via STDIN, logs action, performs response
# Location: /var/ossec/active-response/bin/edr-respond.sh
# ============================================================

LOCAL="$(dirname "$0")"
LOG_FILE="/var/ossec/logs/active-responses.log"

log_msg() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - EDR-RESPOND: $1" >> "$LOG_FILE"
}

# Read JSON from stdin
INPUT_JSON="$(cat)"

if [ -z "$INPUT_JSON" ]; then
    log_msg "ERROR: No input received"
    exit 1
fi

# Extract fields using python (available in Wazuh container)
COMMAND=$(python3 -c "import sys,json; d=json.loads('''$INPUT_JSON'''); print(d.get('command',''))" 2>/dev/null)
RULE_ID=$(python3 -c "import sys,json; d=json.loads('''$INPUT_JSON'''); print(d.get('parameters',{}).get('alert',{}).get('rule',{}).get('id',''))" 2>/dev/null)
RULE_LEVEL=$(python3 -c "import sys,json; d=json.loads('''$INPUT_JSON'''); print(d.get('parameters',{}).get('alert',{}).get('rule',{}).get('level',''))" 2>/dev/null)
SRCIP=$(python3 -c "import sys,json; d=json.loads('''$INPUT_JSON'''); print(d.get('parameters',{}).get('alert',{}).get('data',{}).get('srcip',d.get('parameters',{}).get('alert',{}).get('data',{}).get('SourceIp','')))" 2>/dev/null)
DESTIP=$(python3 -c "import sys,json; d=json.loads('''$INPUT_JSON'''); print(d.get('parameters',{}).get('alert',{}).get('data',{}).get('dstip',d.get('parameters',{}).get('alert',{}).get('data',{}).get('DestinationIp','')))" 2>/dev/null)
AGENT_NAME=$(python3 -c "import sys,json; d=json.loads('''$INPUT_JSON'''); print(d.get('parameters',{}).get('alert',{}).get('agent',{}).get('name','server'))" 2>/dev/null)
DESCRIPTION=$(python3 -c "import sys,json; d=json.loads('''$INPUT_JSON'''); print(d.get('parameters',{}).get('alert',{}).get('rule',{}).get('description',''))" 2>/dev/null)

if [ "$COMMAND" = "add" ]; then
    log_msg "ACTION: Rule=$RULE_ID Level=$RULE_LEVEL Agent=$AGENT_NAME SrcIP=$SRCIP DstIP=$DESTIP Desc=$DESCRIPTION"

    # Block source IP if available (iptables for Linux, Windows Firewall for Windows)
    if [ -n "$SRCIP" ] && [ "$SRCIP" != "" ]; then
        if command -v iptables &>/dev/null; then
            iptables -A INPUT -s "$SRCIP" -j DROP 2>/dev/null
            log_msg "BLOCKED: $SRCIP via iptables (rule $RULE_ID level $RULE_LEVEL)"
        fi
    fi

    # For level 13+ alerts, also block destination IP if it's internal
    if [ -n "$RULE_LEVEL" ] && [ "$RULE_LEVEL" -ge 13 ] 2>/dev/null; then
        log_msg "CRITICAL: Level $RULE_LEVEL alert from agent $AGENT_NAME - automatic containment triggered"
    fi

elif [ "$COMMAND" = "delete" ]; then
    if [ -n "$SRCIP" ] && command -v iptables &>/dev/null; then
        iptables -D INPUT -s "$SRCIP" -j DROP 2>/dev/null
        log_msg "UNBLOCKED: $SRCIP via iptables (rule $RULE_ID)"
    fi
    log_msg "REVERT: Rule=$RULE_ID Agent=$AGENT_NAME"
fi

exit 0
