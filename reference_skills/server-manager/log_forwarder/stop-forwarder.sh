#!/bin/bash
# Stop the log forwarder
PID_FILE="/tmp/forwarder.pid"

if [ ! -f "$PID_FILE" ]; then
    echo "No PID file found. Forwarder may not be running."
    exit 0
fi

PID=$(cat "$PID_FILE")
if kill -0 "$PID" 2>/dev/null; then
    kill "$PID"
    echo "Log forwarder stopped (PID $PID)"
else
    echo "Forwarder process $PID not running. Cleaning up."
fi
rm -f "$PID_FILE"
