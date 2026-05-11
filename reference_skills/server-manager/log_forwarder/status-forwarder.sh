#!/bin/bash
# Check log forwarder status
PID_FILE="/tmp/forwarder.pid"

if [ ! -f "$PID_FILE" ]; then
    echo "Status: STOPPED (no PID file)"
    exit 1
fi

PID=$(cat "$PID_FILE")
if kill -0 "$PID" 2>/dev/null; then
    echo "Status: RUNNING (PID $PID)"
    echo "---"
    tail -20 /tmp/forwarder.log 2>/dev/null
    exit 0
else
    echo "Status: DEAD (stale PID file)"
    rm -f "$PID_FILE"
    exit 1
fi
