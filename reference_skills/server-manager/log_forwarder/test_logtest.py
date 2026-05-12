#!/usr/bin/env python3
"""Test wazuh-logtest to verify Zeek/Suricata rules are loading."""
import subprocess, json, sys

zeek_log = json.dumps({
    "ts": 1714156800,
    "uid": "CzAbCdEf",
    "id.orig_h": "10.0.0.5",
    "id.orig_p": 12345,
    "id.resp_h": "10.0.0.6",
    "id.resp_p": 80,
    "proto": "tcp",
    "conn_state": "REJ",
    "duration": 0.5,
    "orig_bytes": 100,
    "resp_bytes": 0
})

suricata_log = json.dumps({
    "timestamp": "2026-04-27T01:00:00.000000+0000",
    "event_type": "alert",
    "src_ip": "10.0.0.5",
    "dest_ip": "10.0.0.6",
    "alert": {
        "signature": "ET TEST Suricata Alert Test",
        "severity": 4
    }
})

def run_logtest(log_line, label):
    print(f"\n{'='*60}")
    print(f"Testing: {label}")
    print(f"Input: {log_line[:100]}...")
    print(f"{'='*60}")
    try:
        result = subprocess.run(
            ["/var/ossec/bin/wazuh-logtest"],
            input=log_line + "\n",
            capture_output=True,
            text=True,
            timeout=30
        )
        # Show last 30 lines of output
        lines = result.stdout.strip().split("\n")
        for line in lines[-30:]:
            if line.strip():
                print(line)
        if result.stderr.strip():
            print(f"STDERR: {result.stderr[:500]}")
        print(f"Return code: {result.returncode}")
    except subprocess.TimeoutExpired:
        print("TIMEOUT after 30s")
    except Exception as e:
        print(f"ERROR: {e}")

if __name__ == "__main__":
    run_logtest(zeek_log, "Zeek Rejected Connection")
    run_logtest(suricata_log, "Suricata Alert")
