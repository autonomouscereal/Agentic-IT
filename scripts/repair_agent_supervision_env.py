#!/usr/bin/env python3
"""Idempotently set safe agent supervision defaults in a deployed .env file."""
import argparse
from pathlib import Path


DEFAULTS = {
    "AGENT_TIMEOUT_MINUTES": "0",
    "AGENT_AUDITOR_AUTO_RECOVER": "false",
}


def update_env(path):
    path = Path(path)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    seen = set()
    output = []
    for line in lines:
        if not line or line.lstrip().startswith("#") or "=" not in line:
            output.append(line)
            continue
        key, _value = line.split("=", 1)
        if key in DEFAULTS:
            output.append(f"{key}={DEFAULTS[key]}")
            seen.add(key)
        else:
            output.append(line)
    for key, value in DEFAULTS.items():
        if key not in seen:
            output.append(f"{key}={value}")
    path.write_text("\n".join(output) + "\n", encoding="utf-8")
    return {key: DEFAULTS[key] for key in DEFAULTS}


def main():
    parser = argparse.ArgumentParser(description="Repair deployed agent supervision env defaults")
    parser.add_argument("--env-file", default=".env")
    args = parser.parse_args()
    values = update_env(args.env_file)
    print(values)


if __name__ == "__main__":
    main()
