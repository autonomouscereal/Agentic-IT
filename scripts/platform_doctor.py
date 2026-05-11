#!/usr/bin/env python3
"""Operator-facing health check for the modular agentic IT/SOC platform.

The doctor is intentionally non-destructive. It checks the control plane, UI
sorting contract, setup manifest hygiene, and reference integration surfaces
without printing secrets.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class Doctor:
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.warned = 0
        self.results = []

    def record(self, name, status, detail=""):
        if status == "pass":
            self.passed += 1
            label = "PASS"
        elif status == "warn":
            self.warned += 1
            label = "WARN"
        else:
            self.failed += 1
            label = "FAIL"
        message = f"[{label}] {name}"
        if detail:
            message += f" - {detail}"
        print(message)
        self.results.append({"name": name, "status": status, "detail": detail})

    def summary(self):
        print(json.dumps({
            "passed": self.passed,
            "warned": self.warned,
            "failed": self.failed,
        }, sort_keys=True))
        return self.failed == 0


def http_request(url, method="GET", headers=None, body=None, timeout=20):
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers = dict(headers or {})
        headers.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        return resp.status, raw, dict(resp.headers)


def json_request(base, path, method="GET", body=None):
    status, raw, _headers = http_request(base.rstrip("/") + path, method=method, body=body)
    text = raw.decode("utf-8")
    return status, json.loads(text) if text else {}


def load_env_file(path):
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


def check_dashboard(doctor, base):
    try:
        _status, data = json_request(base, "/health")
        doctor.record("Dashboard health endpoint", "pass" if data.get("status") == "ok" else "fail", str(data))
    except Exception as exc:
        doctor.record("Dashboard health endpoint", "fail", str(exc))

    try:
        _status, data = json_request(base, "/api/setup/manifest")
        module_ids = {m.get("id") for m in data.get("modules", [])}
        excluded = {m.get("id") for m in data.get("excluded_modules", [])}
        required = {"soc-dashboard", "local-ticketing", "itop", "wazuh", "mailcow", "gitlab"}
        missing = sorted(required - module_ids)
        banned = sorted(module_ids & {"comfyui", "torrent", "media"})
        if missing:
            doctor.record("Setup manifest required modules", "fail", "missing " + ", ".join(missing))
        else:
            doctor.record("Setup manifest required modules", "pass", f"{len(module_ids)} modules")
        doctor.record("Setup manifest excludes non-IT modules", "pass" if not banned and "comfyui" in excluded else "fail")
    except Exception as exc:
        doctor.record("Setup manifest", "fail", str(exc))

    try:
        _status, asc = json_request(base, "/api/tickets?sort_by=id&sort_dir=asc&limit=5")
        _status, desc = json_request(base, "/api/tickets?sort_by=id&sort_dir=desc&limit=5")
        asc_ids = [item.get("id") for item in asc.get("tickets", [])]
        desc_ids = [item.get("id") for item in desc.get("tickets", [])]
        ok = asc_ids == sorted(asc_ids) and desc_ids == sorted(desc_ids, reverse=True)
        detail = f"asc={asc_ids[:3]} desc={desc_ids[:3]}"
        doctor.record("Ticket API sorting", "pass" if ok else "fail", detail)
    except Exception as exc:
        doctor.record("Ticket API sorting", "fail", str(exc))


def check_itop_ui(doctor, env):
    host = os.environ.get("ITOP_HOST") or env.get("ITOP_HOST") or "127.0.0.1"
    port = os.environ.get("ITOP_PORT") or env.get("ITOP_PORT") or "25432"
    base = f"http://{host}:{port}"
    try:
        status, raw, _headers = http_request(base + "/pages/UI.php", timeout=20)
        ok = status == 200 and b"iTop" in raw[:20000]
        doctor.record("iTop UI", "pass" if ok else "warn", f"HTTP {status}")
    except urllib.error.HTTPError as exc:
        doctor.record("iTop UI", "fail", f"HTTP {exc.code}")
    except Exception as exc:
        doctor.record("iTop UI", "fail", str(exc))


def check_mailcow_api(doctor):
    key_file = Path(os.environ.get("MAILCOW_API_KEY_FILE", "/home/cereal/Mailcow/deploy/api-nginx/.api_key"))
    base = os.environ.get("MAILCOW_API_BASE", "http://127.0.0.1:8081").rstrip("/")
    if not key_file.exists():
        doctor.record("Mailcow HTTP API key file", "warn", "optional shim not deployed")
        return
    api_key = key_file.read_text(encoding="utf-8").strip()
    if not api_key:
        doctor.record("Mailcow HTTP API key file", "fail", "empty key file")
        return
    try:
        http_request(base + "/api/v1/get/mailbox/all", headers={"X-API-Key": "invalid"}, timeout=15)
        doctor.record("Mailcow HTTP API invalid-key rejection", "fail", "invalid key accepted")
    except urllib.error.HTTPError as exc:
        doctor.record("Mailcow HTTP API invalid-key rejection", "pass" if exc.code == 401 else "fail", f"HTTP {exc.code}")
    except Exception as exc:
        doctor.record("Mailcow HTTP API invalid-key rejection", "warn", str(exc))

    try:
        status, raw, _headers = http_request(
            base + "/api/v1/get/mailbox/all",
            headers={"X-API-Key": api_key, "Sec-Fetch-Dest": "script"},
            timeout=20,
        )
        if not raw:
            doctor.record("Mailcow HTTP API mailbox endpoint", "warn", "empty body; keep direct MySQL bridge as canonical")
            return
        json.loads(raw.decode("utf-8"))
        doctor.record("Mailcow HTTP API mailbox endpoint", "pass", f"HTTP {status}")
    except Exception as exc:
        doctor.record("Mailcow HTTP API mailbox endpoint", "warn", f"{exc}; keep direct MySQL bridge as canonical")


def check_file_bundles(doctor):
    expected = {
        "CI/CD scanner runner": ROOT / "scripts" / "run_cicd_security_pipeline.py",
        "Semgrep skill": ROOT / "reference_skills" / "semgrep-scanner" / "SKILL.md",
        "Trivy skill": ROOT / "reference_skills" / "trivy-scanner" / "SKILL.md",
        "OWASP ZAP skill": ROOT / "reference_skills" / "owasp-zap-scanner" / "SKILL.md",
        "Nuclei skill": ROOT / "reference_skills" / "nuclei-scanner" / "SKILL.md",
        "Wazuh EDR Sysmon test": ROOT / "reference_skills" / "wazuh-edr-sysmon" / "tests" / "test_edr_sysmon_e2e.py",
        "AI proxy skill": ROOT / "reference_skills" / "ai-proxy" / "SKILL.md",
        "SearXNG skill": ROOT / "reference_skills" / "searxng-deployment" / "SKILL.md",
    }
    for name, path in expected.items():
        doctor.record(name, "pass" if path.exists() else "fail", str(path.relative_to(ROOT)))


def main():
    parser = argparse.ArgumentParser(description="Run non-destructive platform diagnostics")
    parser.add_argument("--base", default=os.environ.get("DASHBOARD_URL", "http://localhost:25480"))
    parser.add_argument("--env-file", default=os.environ.get("DASHBOARD_ENV_FILE", str(ROOT / ".env")))
    args = parser.parse_args()

    doctor = Doctor()
    env = load_env_file(args.env_file)
    check_dashboard(doctor, args.base)
    check_itop_ui(doctor, env)
    check_mailcow_api(doctor)
    check_file_bundles(doctor)
    sys.exit(0 if doctor.summary() else 1)


if __name__ == "__main__":
    main()
