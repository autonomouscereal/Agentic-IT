#!/usr/bin/env python3
"""Smoke test the agent auditor control-plane endpoints."""
import json
import sys
import urllib.request


BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:25480").rstrip("/")


def request(method, path, body=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def require(condition, message):
    if not condition:
        raise SystemExit(message)


def main():
    run = request("POST", "/api/agents/audits/run", {})
    require(run.get("status") == "ok", f"audit run failed: {run}")
    audits = request("GET", "/api/agents/audits?limit=25")
    require("audits" in audits, f"audit list failed: {audits}")
    print(json.dumps({"ok": True, "audited": run.get("audited"), "recent": len(audits.get("audits", []))}))


if __name__ == "__main__":
    main()
