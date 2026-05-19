#!/bin/bash
# Start the log forwarder as a background process
FORWARDER_DIR="/opt/agentic-it/SOC_TESTING/log_forwarder"
PID_FILE="/tmp/forwarder.pid"

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "Log forwarder already running (PID $(cat "$PID_FILE"))"
    exit 0
fi

cd "$FORWARDER_DIR"
nohup python3 "$FORWARDER_DIR/log_forwarder.py" > /tmp/forwarder.log 2>&1 &
echo $! > "$PID_FILE"
echo "Log forwarder started (PID $!)"
