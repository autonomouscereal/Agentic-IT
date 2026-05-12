#!/usr/bin/env python3
"""
Modular Log Forwarder for SOC Components

Reads JSON logs from Zeek and/or Suricata and forwards them to Wazuh via TCP.
Fully standalone - does not depend on any component being running.
If Wazuh is down, logs are queued in memory and retried with backoff.
If a log source disappears, the forwarder skips it and keeps running.

Configuration via environment variables (or forwarder_config.env file):
    WAZUH_HOST      - SIEM host (default: 127.0.0.1)
    WAZUH_PORT      - SIEM TCP port (default: 26151)
    ZEEK_LOG_DIR    - Path to Zeek logs (default: /opt/soc-testing/logs/zeek)
    ZEEK_ENABLED    - Enable Zeek forwarding (default: true)
    SURICATA_LOG    - Path to Suricata eve.json (default: /opt/soc-testing/logs/suricata/eve.json)
    SURICATA_ENABLED - Enable Suricata forwarding (default: true)
    POSITION_FILE   - State file for tracking file positions (default: /tmp/forwarder_positions.json)
    POLL_INTERVAL   - Seconds between log polls (default: 1)
    MAX_QUEUE       - Max buffered lines before dropping oldest (default: 10000)
    RECONNECT_DELAY - Base seconds to wait before reconnecting (default: 5)
"""

import glob
import json
import os
import socket
import sys
import time
import signal

# -- Configuration ------------------------------------------------------------

def load_config():
    config = {
        'wazuh_host': os.environ.get('WAZUH_HOST', '127.0.0.1'),
        'wazuh_port': int(os.environ.get('WAZUH_PORT', '26151')),
        'zeek_log_dir': os.environ.get('ZEEK_LOG_DIR', '/opt/soc-testing/logs/zeek'),
        'zeek_enabled': os.environ.get('ZEEK_ENABLED', 'true').lower() == 'true',
        'suricata_log': os.environ.get('SURICATA_LOG', '/opt/soc-testing/logs/suricata/eve.json'),
        'suricata_enabled': os.environ.get('SURICATA_ENABLED', 'true').lower() == 'true',
        'position_file': os.environ.get('POSITION_FILE', '/tmp/forwarder_positions.json'),
        'poll_interval': float(os.environ.get('POLL_INTERVAL', '1')),
        'max_queue': int(os.environ.get('MAX_QUEUE', '10000')),
        'reconnect_delay': int(os.environ.get('RECONNECT_DELAY', '5')),
    }
    return config


def load_env_file(path=None):
    """Load environment variables from a .env file if it exists."""
    path = path or os.environ.get('FORWARDER_ENV_FILE', '/opt/soc-testing/log_forwarder/forwarder_config.env')
    try:
        with open(path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip())
    except FileNotFoundError:
        pass


# -- Position Tracking --------------------------------------------------------

class PositionTracker:
    """Persist file read positions to /tmp so restarts don't re-send old logs."""

    def __init__(self, position_file):
        self.position_file = position_file
        self.positions = self._load()

    def _load(self):
        try:
            with open(self.position_file, 'r') as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            return {}

    def save(self):
        try:
            with open(self.position_file, 'w') as f:
                json.dump(self.positions, f)
        except OSError:
            pass

    def get(self, filepath):
        return self.positions.get(filepath, 0)

    def set(self, filepath, pos):
        self.positions[filepath] = pos


# -- TCP Sender ---------------------------------------------------------------

class TCPSender:
    """Maintains a TCP connection to Wazuh with reconnect logic."""

    def __init__(self, host, port, reconnect_delay):
        self.host = host
        self.port = port
        self.reconnect_delay = reconnect_delay
        self.sock = None
        self.connected = False

    def connect(self):
        if self.connected and self._is_alive():
            return True
        self.close()
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(5)
            self.sock.connect((self.host, self.port))
            self.sock.settimeout(None)
            self.connected = True
            return True
        except (socket.timeout, socket.error, OSError):
            self.connected = False
            return False

    def _is_alive(self):
        try:
            if not self.sock:
                return False
            self.sock.sendall(b'')
            return True
        except (socket.error, OSError):
            return False

    def send(self, line):
        if not self.connected:
            if not self.connect():
                return False
        try:
            if not line.endswith(b'\n'):
                line = line + b'\n'
            self.sock.sendall(line)
            return True
        except (socket.error, OSError):
            self.connected = False
            self.sock = None
            return False

    def close(self):
        try:
            if self.sock:
                self.sock.close()
        except (socket.error, OSError):
            pass
        self.sock = None
        self.connected = False

    def reconnect_with_backoff(self):
        for attempt in range(1, 6):
            time.sleep(self.reconnect_delay * attempt)
            if self.connect():
                return True
        return False


# -- Log Tailers --------------------------------------------------------------

class LogTail:
    """Tail a single log file, resuming from a saved position."""

    def __init__(self, filepath, tracker):
        self.filepath = filepath
        self.tracker = tracker
        self._fd = None
        self._rotated = True

    def open(self):
        if self._fd or self._rotated:
            try:
                if self._fd:
                    self._fd.close()
                stat = os.stat(self.filepath)
                if self._rotated or stat.st_size < self.tracker.get(self.filepath):
                    self._rotated = False
                    pos = 0
                else:
                    pos = self.tracker.get(self.filepath)
                self._fd = open(self.filepath, 'r')
                self._fd.seek(pos)
            except (OSError, IOError):
                self._fd = None
                self._rotated = True
                return False
        return self._fd is not None

    def read_lines(self):
        if not self.open():
            return []
        lines = []
        for line in self._fd:
            stripped = line.strip()
            if stripped:
                lines.append(stripped)
        if lines:
            self.tracker.set(self.filepath, self._fd.tell())
        return lines

    def close(self):
        if self._fd:
            self._fd.close()
            self._fd = None


class ZeekTail:
    """Tail all .log files in the Zeek log directory."""

    def __init__(self, log_dir, tracker):
        self.log_dir = log_dir
        self.tracker = tracker
        self.tailers = {}
        self._scan()

    def _scan(self):
        pattern = os.path.join(self.log_dir, '*.log')
        current_files = set(glob.glob(pattern))
        for old_path in list(self.tailers):
            if old_path not in current_files:
                self.tailers[old_path].close()
                del self.tailers[old_path]
        for path in current_files:
            if path not in self.tailers:
                self.tailers[path] = LogTail(path, self.tracker)

    def read_all(self):
        self._scan()
        lines = []
        for path, tailer in self.tailers.items():
            lines.extend(tailer.read_lines())
        return lines

    def close(self):
        for tailer in self.tailers.values():
            tailer.close()


# -- Main Loop ----------------------------------------------------------------

running = True

def signal_handler(signum, frame):
    global running
    running = False

def main():
    global running
    load_env_file()
    config = load_config()

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

    sender = TCPSender(config['wazuh_host'], config['wazuh_port'], config['reconnect_delay'])
    tracker = PositionTracker(config['position_file'])
    queue = []
    zeek_tail = None

    if config['zeek_enabled']:
        zeek_tail = ZeekTail(config['zeek_log_dir'], tracker)

    suricata_tail = None
    if config['suricata_enabled']:
        suricata_tail = LogTail(config['suricata_log'], tracker)

    sources_active = config['zeek_enabled'] or config['suricata_enabled']
    if not sources_active:
        print("ERROR: No log sources enabled. Set ZEEK_ENABLED=true or SURICATA_ENABLED=true")
        sys.exit(1)

    print(f"Log Forwarder started")
    print(f"  Target: {config['wazuh_host']}:{config['wazuh_port']}")
    print(f"  Zeek: {'enabled' if config['zeek_enabled'] else 'disabled'}")
    print(f"  Suricata: {'enabled' if config['suricata_enabled'] else 'disabled'}")
    print(f"  Poll interval: {config['poll_interval']}s")
    print(f"  Position file: {config['position_file']}")

    reconnect_attempted = False

    while running:
        new_lines = []

        if config['zeek_enabled'] and zeek_tail:
            try:
                new_lines.extend(zeek_tail.read_all())
            except Exception as e:
                print(f"  Zeek read error: {e}")

        if config['suricata_enabled'] and suricata_tail:
            try:
                new_lines.extend(suricata_tail.read_lines())
            except Exception as e:
                print(f"  Suricata read error: {e}")

        for line in new_lines:
            if len(queue) >= config['max_queue']:
                queue.pop(0)
            queue.append(line.encode('utf-8', errors='replace'))

        while queue:
            line = queue.pop(0)
            if sender.send(line):
                reconnect_attempted = False
            else:
                if not reconnect_attempted:
                    print(f"  Wazuh connection lost, reconnecting...")
                    sender.reconnect_with_backoff()
                    reconnect_attempted = True
                if not sender.connected:
                    queue.insert(0, line)
                    break

        tracker.save()
        time.sleep(config['poll_interval'])

    if zeek_tail:
        zeek_tail.close()
    if suricata_tail:
        suricata_tail.close()
    sender.close()
    tracker.save()
    print("Log Forwarder stopped.")


if __name__ == '__main__':
    main()
