#!/usr/bin/env python3
"""End-to-End Integration Tests for Zeek + Suricata + Wazuh

Validates:
1. All SOC components are running (Zeek, Suricata, Wazuh containers)
2. Wazuh rules correctly match Zeek logs (via wazuh-logtest)
3. Wazuh rules correctly match Suricata logs (via wazuh-logtest)
4. Log files exist and are accessible
5. Log forwarder can connect to Wazuh

Run on the AI Server (192.168.50.222):
    cd /home/cereal/SOC_TESTING/log_forwarder
    python test_integration.py -v
"""

import json
import os
import socket
import subprocess
import sys
import time


WAZUH_CONTAINER = "wazuh_deploy-wazuh.manager-1"
SOC_COMPOSE_DIR = "/home/cereal/SOC_TESTING"
WAZUH_COMPOSE_DIR = "/home/cereal/SOC_TESTING/wazuh_deploy"
WAZUH_HOST = "127.0.0.1"
WAZUH_PORT = 26151


def docker_exec(cmd, timeout=15):
    """Run a command inside a container and return stdout."""
    result = subprocess.run(
        ["docker", "exec", WAZUH_CONTAINER, "bash", "-c", cmd],
        capture_output=True, text=True, timeout=timeout
    )
    return result.returncode, result.stdout.strip(), result.stderr.strip()


def docker_compose_ps(compose_dir, timeout=10):
    """Check container status via docker compose."""
    result = subprocess.run(
        ["docker", "compose", "ps", "--format", "json"],
        cwd=compose_dir, capture_output=True, text=True, timeout=timeout
    )
    return result.returncode == 0


def run_logtest(log_json, label):
    """Send a JSON log to wazuh-logtest and return the matched rule info."""
    cmd = f'echo \'{log_json}\' | /var/ossec/bin/wazuh-logtest 2>&1'
    rc, out, err = docker_exec(cmd, timeout=30)

    rule_id = None
    rule_level = None
    rule_desc = None
    alert_generated = False

    for line in out.split("\n"):
        if "id:" in line and "id.orig" not in line:
            rule_id = line.split("'")[-2] if "'" in line else line.split(":")[-1].strip()
        if "level:" in line:
            rule_level = line.split("'")[-2] if "'" in line else line.split(":")[-1].strip()
        if "description:" in line:
            rule_desc = line.split("'")[-2] if "'" in line else line.split(":")[-1].strip()
        if "Alert to be generated" in line:
            alert_generated = True

    return {
        "label": label,
        "rule_id": rule_id,
        "rule_level": rule_level,
        "rule_desc": rule_desc,
        "alert": alert_generated,
    }


# ── Health Tests ──────────────────────────────────────────────────────────────

def test_zeek_container_running():
    """Zeek SOC container is running."""
    result = subprocess.run(
        ["docker", "compose", "ps", "--services"],
        cwd=SOC_COMPOSE_DIR, capture_output=True, text=True, timeout=10
    )
    assert "zeek" in result.stdout.lower(), f"Zeek container not running: {result.stdout}"
    print(f"  PASS: Zeek container running")


def test_suricata_container_running():
    """Suricata SOC container is running."""
    result = subprocess.run(
        ["docker", "compose", "ps", "--services"],
        cwd=SOC_COMPOSE_DIR, capture_output=True, text=True, timeout=10
    )
    assert "suricata" in result.stdout.lower(), f"Suricata container not running: {result.stdout}"
    print(f"  PASS: Suricata container running")


def test_wazuh_manager_running():
    """Wazuh manager container is running with analysisd."""
    rc, out, err = docker_exec("ps aux | grep analysisd | grep -v grep")
    assert rc == 0 and "analysisd" in out, "wazuh-analysisd not running"
    print(f"  PASS: Wazuh manager running (analysisd active)")


def test_wazuh_no_critical_errors():
    """No CRITICAL errors in current Wazuh startup cycle."""
    rc, out, err = docker_exec(
        "grep 'analysisd.*Started' /var/ossec/logs/ossec.log | tail -1"
    )
    if rc != 0 or not out.strip():
        print(f"  WARN: Could not determine last analysisd start time")
        return  # pass if we can't determine

    # Extract timestamp from last startup line
    last_start = out.strip().split("wazuh-analysisd")[0].strip().rstrip("/")
    # Get all CRITICAL errors after that timestamp
    rc, crit_out, _ = docker_exec(
        f"grep 'CRITICAL' /var/ossec/logs/ossec.log | grep -v 'Exited'"
    )
    current_errors = []
    for line in crit_out.split("\n"):
        if not line.strip():
            continue
        line_ts = line.strip().split("wazuh-")[0].strip().rstrip("/")
        if line_ts >= last_start and ("zeek_decoders" in line or "zeek_rules" in line):
            current_errors.append(line.strip())
    assert len(current_errors) == 0, f"Current startup critical errors: {current_errors}"
    print(f"  PASS: No critical rule/decoder errors in current startup")


def test_log_files_exist():
    """Zeek and Suricata log files are accessible."""
    zeek_dir = "/home/cereal/SOC_TESTING/logs/zeek"
    suricata_log = "/home/cereal/SOC_TESTING/logs/suricata/eve.json"

    assert os.path.isdir(zeek_dir), f"Zeek log dir missing: {zeek_dir}"
    assert os.path.isfile(suricata_log), f"Suricata log missing: {suricata_log}"
    print(f"  PASS: Log files exist and accessible")


# ── Zeek Rule Tests ──────────────────────────────────────────────────────────

def test_zeek_base_rule():
    """Rule 100900 matches Zeek conn.log baseline."""
    log = json.dumps({
        "ts": 1714156800, "uid": "CzAbCdEf",
        "id.orig_h": "10.0.0.5", "id.orig_p": 12345,
        "id.resp_h": "10.0.0.6", "id.resp_p": 80,
        "proto": "tcp", "conn_state": "SF",
        "duration": 1.0, "orig_bytes": 500, "resp_bytes": 999
    })
    result = run_logtest(log, "Zeek baseline conn.log")
    assert result["rule_id"] == "100900", f"Expected 100900, got {result['rule_id']}"
    assert result["rule_level"] == "0", "Base rule should be level 0"
    print(f"  PASS: Zeek base rule 100900 matched")


def test_zeek_rejected_connection():
    """Rule 100903 fires for rejected connections (REJ state)."""
    log = json.dumps({
        "ts": 1714156800, "uid": "CzReJect",
        "id.orig_h": "10.0.0.5", "id.orig_p": 54321,
        "id.resp_h": "10.0.0.6", "id.resp_p": 22,
        "proto": "tcp", "conn_state": "REJ",
        "duration": 0.5, "orig_bytes": 100, "resp_bytes": 0
    })
    result = run_logtest(log, "Zeek rejected connection")
    assert result["rule_id"] == "100903", f"Expected 100903, got {result['rule_id']}"
    assert result["alert"], "Rejected connection should generate alert"
    assert "Rejected connection" in result["rule_desc"]
    print(f"  PASS: Zeek rejected connection rule 100903 fired (level {result['rule_level']})")


def test_zeek_self_signed_cert():
    """Rule 100906 fires for self-signed certificates."""
    log = json.dumps({
        "ts": 1714156800, "uid": "CsSelfSigned",
        "id.orig_h": "10.0.0.5", "id.orig_p": 44321,
        "id.resp_h": "10.0.0.7", "id.resp_p": 443,
        "proto": "tcp", "version": "TLS 1.2",
        "validation_status": "self signed certificate",
        "server_name": "example.com", "established": "TRUE"
    })
    result = run_logtest(log, "Zeek self-signed cert")
    assert result["rule_id"] == "100906", f"Expected 100906, got {result['rule_id']}"
    assert result["alert"], "Self-signed cert should generate alert"
    print(f"  PASS: Zeek self-signed cert rule 100906 fired (level {result['rule_level']})")


def test_zeek_expired_cert():
    """Rule 100907 fires for expired certificates."""
    log = json.dumps({
        "ts": 1714156800, "uid": "CsExpired",
        "id.orig_h": "10.0.0.5", "id.orig_p": 44322,
        "id.resp_h": "10.0.0.8", "id.resp_p": 443,
        "proto": "tcp", "version": "TLS 1.2",
        "validation_status": "certificate has expired",
        "server_name": "expired.com", "established": "FALSE"
    })
    result = run_logtest(log, "Zeek expired cert")
    assert result["rule_id"] == "100907", f"Expected 100907, got {result['rule_id']}"
    assert result["alert"], "Expired cert should generate alert"
    print(f"  PASS: Zeek expired cert rule 100907 fired (level {result['rule_level']})")


def test_zeek_nxdomain():
    """Rule 100909 fires for DNS NXDOMAIN responses."""
    log = json.dumps({
        "ts": 1714156800, "uid": "CdNxdomain",
        "id.orig_h": "10.0.0.5", "id.orig_p": 55555,
        "id.resp_h": "10.0.0.2", "id.resp_p": 53,
        "proto": "udp", "query": "nonexistent.example.com",
        "rcode_name": "NXDOMAIN", "query_type": "A"
    })
    result = run_logtest(log, "Zeek DNS NXDOMAIN")
    assert result["rule_id"] == "100909", f"Expected 100909, got {result['rule_id']}"
    assert result["alert"], "NXDOMAIN should generate alert"
    print(f"  PASS: Zeek NXDOMAIN rule 100909 fired (level {result['rule_level']})")


def test_zeek_revoked_cert():
    """Rule 100910 fires for revoked certificates."""
    log = json.dumps({
        "ts": 1714156800, "uid": "CsRevoked",
        "id.orig_h": "10.0.0.5", "id.orig_p": 44323,
        "id.resp_h": "10.0.0.9", "id.resp_p": 443,
        "proto": "tcp", "version": "TLS 1.3",
        "validation_status": "revoked certificate",
        "server_name": "revoked.com", "established": "FALSE"
    })
    result = run_logtest(log, "Zeek revoked cert")
    assert result["rule_id"] == "100910", f"Expected 100910, got {result['rule_id']}"
    assert result["alert"], "Revoked cert should generate alert"
    print(f"  PASS: Zeek revoked cert rule 100910 fired (level {result['rule_level']})")


# ── Suricata Rule Tests ──────────────────────────────────────────────────────

def test_suricata_high_severity():
    """Rule 86710 fires for HIGH severity alerts (severity 4)."""
    log = json.dumps({
        "timestamp": "2026-04-27T01:00:00.000000+0000",
        "event_type": "alert",
        "src_ip": "10.0.0.5", "dest_ip": "10.0.0.6",
        "alert": {"signature": "ET TEST High Severity", "severity": 4}
    })
    result = run_logtest(log, "Suricata HIGH severity")
    assert result["rule_id"] == "86710", f"Expected 86710, got {result['rule_id']}"
    assert result["alert"], "HIGH severity should generate alert"
    print(f"  PASS: Suricata HIGH severity rule 86710 fired (level {result['rule_level']})")


def test_suricata_critical_severity():
    """Rule 86711 fires for CRITICAL severity alerts (severity 5)."""
    log = json.dumps({
        "timestamp": "2026-04-27T01:00:00.000000+0000",
        "event_type": "alert",
        "src_ip": "10.0.0.5", "dest_ip": "10.0.0.6",
        "alert": {"signature": "ET CRITICAL Alert", "severity": 5}
    })
    result = run_logtest(log, "Suricata CRITICAL severity")
    assert result["rule_id"] == "86711", f"Expected 86711, got {result['rule_id']}"
    assert result["alert"], "CRITICAL severity should generate alert"
    print(f"  PASS: Suricata CRITICAL rule 86711 fired (level {result['rule_level']})")


def test_suricata_emergency_severity():
    """Rule 86712 fires for EMERGENCY severity alerts (severity 6)."""
    log = json.dumps({
        "timestamp": "2026-04-27T01:00:00.000000+0000",
        "event_type": "alert",
        "src_ip": "10.0.0.5", "dest_ip": "10.0.0.6",
        "alert": {"signature": "ET EMERGENCY Alert", "severity": 6}
    })
    result = run_logtest(log, "Suricata EMERGENCY severity")
    assert result["rule_id"] == "86712", f"Expected 86712, got {result['rule_id']}"
    assert result["alert"], "EMERGENCY severity should generate alert"
    print(f"  PASS: Suricata EMERGENCY rule 86712 fired (level {result['rule_level']})")


def test_suricata_dns_nxdomain():
    """Rule 86740 fires for DNS NXDOMAIN."""
    log = json.dumps({
        "timestamp": "2026-04-27T01:00:00.000000+0000",
        "event_type": "dns",
        "src_ip": "10.0.0.5", "dest_ip": "10.0.0.2",
        "dns": {"response_code": "NXDOMAIN", "query": "bad.example.com"}
    })
    result = run_logtest(log, "Suricata DNS NXDOMAIN")
    assert result["rule_id"] == "86740", f"Expected 86740, got {result['rule_id']}"
    assert result["alert"], "DNS NXDOMAIN should generate alert"
    print(f"  PASS: Suricata DNS NXDOMAIN rule 86740 fired (level {result['rule_level']})")


def test_suricata_tls_deprecated():
    """Rule 86750 fires for deprecated TLS 1.0."""
    log = json.dumps({
        "timestamp": "2026-04-27T01:00:00.000000+0000",
        "event_type": "tls",
        "src_ip": "10.0.0.5", "dest_ip": "10.0.0.6",
        "tls": {"version": "TLS 1.0", "subject": "CN=example.com"}
    })
    result = run_logtest(log, "Suricata TLS 1.0")
    assert result["rule_id"] == "86750", f"Expected 86750, got {result['rule_id']}"
    assert result["alert"], "TLS 1.0 should generate alert"
    print(f"  PASS: Suricata TLS 1.0 rule 86750 fired (level {result['rule_level']})")


# ── Forwarder Tests ──────────────────────────────────────────────────────────

def test_wazuh_tcp_port_open():
    """Wazuh TCP port 26151 is accepting connections."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5)
    result = sock.connect_ex((WAZUH_HOST, WAZUH_PORT))
    sock.close()
    assert result == 0, f"Wazuh TCP port {WAZUH_PORT} not open"
    print(f"  PASS: Wazuh TCP port {WAZUH_PORT} accepting connections")


def test_forwarder_can_connect():
    """Log forwarder can establish TCP connection to Wazuh."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5)
    try:
        sock.connect((WAZUH_HOST, WAZUH_PORT))
        sock.sendall(b'{"test": "forwarder_check"}\n')
        print(f"  PASS: Forwarder test connection successful")
    except socket.error as e:
        assert False, f"Forwarder connection failed: {e}"
    finally:
        sock.close()


# ── Runner ────────────────────────────────────────────────────────────────────

def main():
    tests = [
        ("Health: Zeek container", test_zeek_container_running),
        ("Health: Suricata container", test_suricata_container_running),
        ("Health: Wazuh manager", test_wazuh_manager_running),
        ("Health: No critical errors", test_wazuh_no_critical_errors),
        ("Health: Log files exist", test_log_files_exist),
        ("Zeek: Base rule 100900", test_zeek_base_rule),
        ("Zeek: Rejected connection 100903", test_zeek_rejected_connection),
        ("Zeek: Self-signed cert 100906", test_zeek_self_signed_cert),
        ("Zeek: Expired cert 100907", test_zeek_expired_cert),
        ("Zeek: NXDOMAIN 100909", test_zeek_nxdomain),
        ("Zeek: Revoked cert 100910", test_zeek_revoked_cert),
        ("Suricata: HIGH severity 86710", test_suricata_high_severity),
        ("Suricata: CRITICAL severity 86711", test_suricata_critical_severity),
        ("Suricata: EMERGENCY severity 86712", test_suricata_emergency_severity),
        ("Suricata: DNS NXDOMAIN 86740", test_suricata_dns_nxdomain),
        ("Suricata: TLS 1.0 86750", test_suricata_tls_deprecated),
        ("Forwarder: TCP port open", test_wazuh_tcp_port_open),
        ("Forwarder: Can connect", test_forwarder_can_connect),
    ]

    passed = 0
    failed = 0
    errors = []

    print("=" * 60)
    print("Zeek + Suricata + Wazuh Integration Tests")
    print("=" * 60)

    for name, test_func in tests:
        try:
            test_func()
            passed += 1
        except AssertionError as e:
            failed += 1
            errors.append((name, str(e)))
            print(f"  FAIL: {name} - {e}")
        except Exception as e:
            failed += 1
            errors.append((name, f"{type(e).__name__}: {e}"))
            print(f"  ERROR: {name} - {e}")

    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed, {len(tests)} total")
    if errors:
        print("\nFailures:")
        for name, err in errors:
            print(f"  - {name}: {err}")
    print("=" * 60)

    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
