#!/usr/bin/env python3
"""
Wazuh EDR + Sysmon End-to-End Test Suite
Tests the complete pipeline: Sysmon -> Wazuh -> Bridge -> iTop
"""
import json
import os
import ssl
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
from datetime import datetime, timedelta


class E2ETestResult:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.results = []

    def record(self, name, passed, message=""):
        status = "PASS" if passed else "FAIL"
        if message:
            status += f" - {message}"
        self.results.append((name, passed))
        if passed:
            self.passed += 1
        else:
            self.failed += 1
        print(f"  [{status}] {name}")

    def summary(self):
        total = self.passed + self.failed + self.skipped
        print(f"\n{'='*50}")
        print(f" E2E Test Results: {self.passed}/{total} passed, "
              f"{self.failed} failed, {self.skipped} skipped")
        print(f"{'='*50}")
        return self.failed == 0


def container_env(container, key):
    """Read one environment value from a local Docker container without printing it."""
    try:
        result = subprocess.run(
            [
                "docker", "inspect",
                "-f", "{{range .Config.Env}}{{println .}}{{end}}",
                container,
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception:
        return ""
    if result.returncode != 0:
        return ""
    prefix = f"{key}="
    for line in result.stdout.splitlines():
        if line.startswith(prefix):
            return line[len(prefix):]
    return ""


def load_env_file(path):
    """Load a simple KEY=VALUE env file for local deployed test credentials."""
    values = {}
    try:
        with open(path, encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                values[key] = value.strip().strip('"').strip("'")
    except OSError:
        return values
    return values


# Configuration (from environment variables or deployed local service env only).
WAZUH_HOST = os.environ.get("WAZUH_HOST", "127.0.0.1")
WAZUH_PORT = int(os.environ.get("WAZUH_PORT", "26500"))
WAZUH_MANAGER_CONTAINER = os.environ.get("WAZUH_MANAGER_CONTAINER", "wazuh_deploy-wazuh.manager-1")
WAZUH_API_USER = (
    os.environ.get("WAZUH_API_USER")
    or container_env(WAZUH_MANAGER_CONTAINER, "API_USERNAME")
    or "wazuh-wui"
)
WAZUH_API_PASSWORD = (
    os.environ.get("WAZUH_API_PASSWORD")
    or container_env(WAZUH_MANAGER_CONTAINER, "API_PASSWORD")
)
INDEXER_PORT = int(os.environ.get("INDEXER_PORT", "26920"))
INDEXER_USER = (
    os.environ.get("INDEXER_USER")
    or container_env(WAZUH_MANAGER_CONTAINER, "INDEXER_USERNAME")
    or "admin"
)
INDEXER_PASSWORD = (
    os.environ.get("INDEXER_PASSWORD")
    or container_env(WAZUH_MANAGER_CONTAINER, "INDEXER_PASSWORD")
)
ITOP_HOST = os.environ.get("ITOP_HOST", "127.0.0.1")
ITOP_PORT = int(os.environ.get("ITOP_PORT", "25432"))
DASHBOARD_ENV = load_env_file(os.environ.get("DASHBOARD_ENV_FILE", "/opt/agentic-it/SOC_TESTING/soc-dashboard/.env"))
ITOP_USER = os.environ.get("ITOP_USER") or DASHBOARD_ENV.get("ITOP_USER", "admin")
ITOP_PASSWORD = os.environ.get("ITOP_PASSWORD") or DASHBOARD_ENV.get("ITOP_PASSWORD", "")


def wazuh_auth():
    """Authenticate with Wazuh Manager API and return JWT token."""
    url = f"https://{WAZUH_HOST}:{WAZUH_PORT}/security/user/authenticate?raw=true"
    creds = f"{WAZUH_API_USER}:{WAZUH_API_PASSWORD}".encode()
    import base64
    auth = base64.b64encode(creds).decode()

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"Basic {auth}")

    try:
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            return resp.read().decode().strip()
    except Exception as e:
        return None


def wazuh_request(token, method, endpoint, data=None):
    """Make authenticated request to Wazuh API."""
    url = f"https://{WAZUH_HOST}:{WAZUH_PORT}{endpoint}"
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    body = None
    if data:
        body = json.dumps(data).encode()

    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            text = resp.read().decode()
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"raw": text}
    except Exception as e:
        return {"error": str(e)}


def indexer_request(endpoint, data=None, method=None):
    """Make request to Wazuh Indexer."""
    url = f"https://{WAZUH_HOST}:{INDEXER_PORT}{endpoint}"
    creds = f"{INDEXER_USER}:{INDEXER_PASSWORD}".encode()
    import base64
    auth = base64.b64encode(creds).decode()

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    body = None
    if data:
        body = json.dumps(data).encode()

    req = urllib.request.Request(url, data=body, method=method or ("POST" if data else "GET"))
    req.add_header("Authorization", f"Basic {auth}")
    req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=10, context=ctx) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"error": str(e)}


def itop_request(operation, fields):
    """Make request to iTop REST API."""
    import base64
    url = f"http://{ITOP_HOST}:{ITOP_PORT}/webservices/rest.php"
    creds = f"{ITOP_USER}:{ITOP_PASSWORD}".encode()
    auth = base64.b64encode(creds).decode()

    payload = {"version": "1.4", "json_output": 1, "operation": operation, "user": ITOP_USER,
               "password": ITOP_PASSWORD}
    payload.update(fields)

    body = f"version=1.4&json_output=1&json_data={urllib.parse.quote(json.dumps(payload))}".encode()

    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", f"Basic {auth}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")

    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read().decode())
    except Exception as e:
        return {"code": -1, "error": str(e)}


def test_wazuh_api(result):
    """Test 1: Wazuh Manager API is responsive."""
    token = wazuh_auth()
    result.record("Wazuh Manager API authentication", token is not None,
                  "Got JWT token" if token else "Auth failed")
    return token


def test_manager_status(token, result):
    """Test 2: Wazuh Manager processes running."""
    if not token:
        result.record("Wazuh Manager status", False, "No auth token")
        return
    resp = wazuh_request(token, "GET", "/manager/status")
    data = resp.get("data", {})
    if isinstance(data, dict) and isinstance(data.get("affected_items"), list):
        items = data.get("affected_items")
        data = items[0] if items else {}
    running_count = sum(1 for value in data.values() if str(value).lower() == "running") if isinstance(data, dict) else 0
    result.record("Wazuh Manager processes running", running_count > 0,
                  f"{running_count} running processes" if running_count else str(resp)[:120])


def test_agents_list(token, result):
    """Test 3: Wazuh agents endpoint accessible."""
    if not token:
        result.record("Wazuh agents list", False, "No auth token")
        return
    resp = wazuh_request(token, "GET", "/agents?limit=5")
    has_data = "data" in resp or "affected_items" in resp
    result.record("Wazuh agents endpoint accessible", has_data)


def test_sysmon_rules_loaded(token, result):
    """Test 4: Sysmon rules are loaded in Wazuh."""
    if not token:
        result.record("Sysmon rules loaded", False, "No auth token")
        return
    resp = wazuh_request(token, "GET", "/rules?limit=100&search=sysmon")
    total = resp.get("data", {}).get("total_affected_items", 0)
    result.record("Sysmon rules loaded and searchable", total > 0,
                  f"{total} sysmon rules found" if total > 0 else "No rules found")


def test_live_sysmon_config_shape(result):
    """Verify the live manager has Wazuh 4.14-safe Sysmon decoder/rule XML."""
    try:
        proc = subprocess.run(
            [
                "docker", "exec", WAZUH_MANAGER_CONTAINER, "sh", "-lc",
                "cat /var/ossec/etc/decoders/sysmon_decoder.xml; "
                "printf '\\n---RULE---\\n'; "
                "cat /var/ossec/etc/rules/sysmon_marker_rules.xml",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except Exception as exc:
        result.record("Live Sysmon decoder/rule shape", False, str(exc)[:120])
        return
    if proc.returncode != 0:
        result.record("Live Sysmon decoder/rule shape", False, proc.stderr[:120])
        return
    decoder, _sep, marker_rule = proc.stdout.partition("---RULE---")
    valid_decoder = "<decoder name=\"sysmon-reference\">" in decoder and "<location>" not in decoder
    xml_marker_child = (
        "<rule id=\"100230\"" in marker_rule
        and "CODEX_SYSMON_" in marker_rule
        and "<if_sid>100200</if_sid>" in marker_rule
    )
    raw_marker_fallback = (
        "<rule id=\"100231\"" in marker_rule
        and "CODEX_SYSMON_" in marker_rule
    )
    result.record(
        "Live Sysmon decoder/rule shape",
        valid_decoder and xml_marker_child and raw_marker_fallback,
        "decoder has no <location>; XML marker child and raw marker fallback present"
        if valid_decoder and xml_marker_child and raw_marker_fallback else "invalid live Sysmon decoder or marker rule",
    )


def test_indexer_health(result):
    """Test 5: Wazuh Indexer is healthy."""
    resp = indexer_request("/_cluster/health")
    status = resp.get("status", "unknown")
    result.record("Wazuh Indexer cluster healthy",
                  status in ("green", "yellow"), f"Status: {status}")


def test_indexer_indices(result):
    """Test 6: Wazuh alert indices exist."""
    resp = indexer_request("/_cat/indices?format=json")
    has_indices = isinstance(resp, list) or "raw" in resp or ("error" not in resp and bool(resp))
    result.record("Indexer indices accessible", has_indices)


def test_search_alerts(result):
    """Test 7: Can search alerts in indexer."""
    query = {
        "query": {"match_all": {}},
        "size": 5
    }
    resp = indexer_request("/wazuh-alerts-4.x-*/_search", query)
    hits = resp.get("hits", {}).get("total", {}).get("value", -1)
    result.record("Alert search works", hits >= 0,
                  f"{hits} alerts found" if hits >= 0 else "Search failed")


def test_live_sysmon_alert_flow(result):
    """Generate a unique harmless marker and verify that exact alert in Wazuh."""
    marker = f"CODEX_SYSMON_E2E_{int(time.time())}"
    subprocess.run(
        ["/usr/bin/logger", "-t", "sysmon", marker],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=5,
    )
    subprocess.run(
        ["/usr/bin/bash", "-lc", f"printf '%s\\n' '{marker}' >/tmp/{marker}.txt"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
        timeout=5,
    )
    time.sleep(int(os.environ.get("SYSMON_ALERT_WAIT_SECONDS", "90")))
    query = {
        "size": 5,
        "sort": [{"timestamp": {"order": "desc"}}],
        "query": {
            "bool": {
                "filter": [{"range": {"timestamp": {"gte": "now-15m"}}}],
                "must": [{"match_phrase": {"full_log": marker}}],
            }
        },
    }
    resp = indexer_request("/wazuh-alerts-4.x-*/_search", query)
    hits = resp.get("hits", {}).get("total", {}).get("value", 0)
    result.record("Fresh Sysmon exact-marker alert flow", hits > 0,
                  f"{hits} alert(s) for {marker}" if hits > 0 else str(resp)[:160])


def test_itop_connectivity(result):
    """Test 8: iTop REST API accessible."""
    resp = itop_request("core/check_credentials", {})
    code = resp.get("code", -1)
    result.record("iTop API authentication", code == 0,
                  f"code={code}" if code != 0 else "Authenticated")


def test_itop_create_incident(result):
    """Test 9: Can create test incident in iTop."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    resp = itop_request("core/create", {
        "class": "Incident",
        "fields": {
            "title": f"EDR E2E Test Incident {datetime.now().isoformat()}",
            "description": "End-to-end test for EDR+Sysmon pipeline",
            "impact": 2,
            "urgency": 2,
            "org_id": 1,
            "caller_id": 1
        },
        "comment": "EDR E2E test"
    })
    code = resp.get("code", -1)
    result.record("iTop test incident creation", code == 0,
                  f"code={code}" if code != 0 else "Created successfully")
    return resp


def test_sysmon_for_linux(result):
    """Test 10: SysmonForLinux service status (via file check)."""
    import os
    service_active = os.path.exists("/etc/systemd/system/sysmon.service")
    result.record("SysmonForLinux systemd unit exists", service_active)


def test_edr_ar_config(result):
    """Test 11: EDR active response config present."""
    import os
    conf_path = "/opt/agentic-it/SOC_TESTING/wazuh_deploy/config/wazuh_cluster/wazuh_manager.conf"
    if os.path.exists(conf_path):
        with open(conf_path) as f:
            content = f.read()
        has_ar = "<active-response>" in content
        has_edr = "edr-respond" in content
        result.record("Active Response enabled in config", has_ar)
        result.record("EDR AR script configured", has_edr)
    else:
        result.record("EDR config file exists", False, "Config not found")


def test_bridge_service(result):
    """Test 12: SIEM-Ticketing bridge state file."""
    import os
    state_path = "/var/lib/siem-ticket-bridge/state.json"
    if os.path.exists(state_path):
        with open(state_path) as f:
            state = json.load(f)
        result.record("Bridge state file valid",
                      "processed_alerts" in state or "alert_count" in state)
    else:
        result.record("Bridge state file exists", False, "State file missing")


def test_modular_isolation(result):
    """Test 13: Verify modular isolation - Wazuh works independently."""
    token = wazuh_auth()
    if token:
        # Wazuh should work regardless of bridge/iTop status
        resp = wazuh_request(token, "GET", "/manager/status")
        ok = not resp.get("error")
        result.record("Wazuh operates independently (modular)", ok,
                      str(resp)[:120] if not ok else "manager status reachable")
    else:
        result.record("Modular isolation test", False, "Wazuh unavailable")


def main():
    print("=" * 50)
    print(" Wazuh EDR + Sysmon E2E Test Suite")
    print(f" {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)
    print()

    result = E2ETestResult()

    # Connectivity tests
    print("--- Connectivity ---")
    token = test_wazuh_api(result)
    test_manager_status(token, result)
    test_agents_list(token, result)
    test_indexer_health(result)
    test_indexer_indices(result)
    test_search_alerts(result)
    test_live_sysmon_alert_flow(result)
    test_itop_connectivity(result)

    # Configuration tests
    print("\n--- Configuration ---")
    test_sysmon_rules_loaded(token, result) if token else None
    test_live_sysmon_config_shape(result)
    test_edr_ar_config(result)

    # Integration tests
    print("\n--- Integration ---")
    test_itop_create_incident(result)
    test_sysmon_for_linux(result)
    test_bridge_service(result)

    # Modularity tests
    print("\n--- Modularity ---")
    test_modular_isolation(result)

    # Summary
    success = result.summary()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
