#!/usr/bin/env python3
"""Audit the Codex migration state for harness skills and bridge scripts.

The goal is intentionally narrow: catch migration regressions that make agents
fall back to old Claude-only paths, retired server-manager flags, or plaintext
SSH/upload helpers. This script does not prove every provider works; it proves
the portable bundle is clean enough to run the real smoke suites.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REFERENCE_SKILLS = ROOT / "reference_skills"
SYNC_SCRIPT = ROOT / "scripts" / "sync_reference_skills.py"

TEXT_SUFFIXES = {
    ".cfg",
    ".conf",
    ".env",
    ".example",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".rb",
    ".service",
    ".sh",
    ".sql",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}

FORBIDDEN_FILES = {
    ".cred_key",
    ".cred_vault.json",
    ".credentials.json",
    ".env",
    ".env.local",
    ".env.production",
    ".server_state",
    "credentials.json",
    "server_config.json",
    "servers.json",
    "token.json",
}

LEGACY_PATTERNS = [
    (re.compile(r"C:[/\\]Users[/\\]cereal[/\\]\.Codex[/\\]skills", re.I), "legacy .Codex skill path"),
    (re.compile(r"(?<![\w-])--ai(?![\w-])"), "retired server-manager --ai flag"),
    (re.compile(r"\.claude[/\\]skills[/\\]server-manager", re.I), "Claude-only server-manager path"),
    (re.compile(r"REMOTE_PASS\s*=", re.I), "raw SSH password variable"),
    (re.compile(r"the-ai-server-password", re.I), "example password literal"),
    (re.compile(r"ssh\.connect\([^)]*password\s*=", re.I | re.S), "raw Paramiko password connect"),
]

SECRET_LITERAL_PATTERNS = [
    (re.compile(r"sk-[A-Za-z0-9]{20,}"), "API key literal"),
    (re.compile(r"(?im)^\s*(?!#)(?:export\s+)?([A-Z0-9_]*(?:PASSWORD|API[_-]?KEY|TOKEN|SECRET)[A-Z0-9_]*)[ \t]*=[ \t]*['\"](?!<|\$|\{|\(|from vault|vault|dummy|lmstudio|test|changeme|example|placeholder)([^'\"\n]{6,})['\"]"), "secret-like assignment"),
]


def is_text_file(path):
    if path.name in {"Dockerfile", "Makefile"}:
        return True
    return path.suffix.lower() in TEXT_SUFFIXES or any(path.name.endswith(suffix) for suffix in [".env.example"])


def scan_files(paths):
    issues = []
    for base in paths:
        if not base.exists():
            issues.append({"path": str(base), "kind": "missing_path", "match": "path does not exist"})
            continue
        for path in base.rglob("*"):
            if path.is_dir():
                continue
            rel = path.relative_to(ROOT) if ROOT in path.parents else path
            if path.name in FORBIDDEN_FILES:
                issues.append({"path": str(rel), "kind": "forbidden_file", "match": path.name})
                continue
            if not is_text_file(path):
                continue
            if path == Path(__file__).resolve():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for regex, label in LEGACY_PATTERNS + SECRET_LITERAL_PATTERNS:
                for match in regex.finditer(text):
                    if "$2b$" in match.group(0) or r"\$2b\$" in match.group(0):
                        continue
                    if label == "secret-like assignment":
                        lhs = match.group(1).upper()
                        if lhs.endswith(("_ENV", "_FILE", "_PATH")):
                            continue
                    line = text.count("\n", 0, match.start()) + 1
                    snippet = text[match.start():match.end()].replace("\n", "\\n")[:160]
                    issues.append({"path": str(rel), "line": line, "kind": label, "match": snippet})
    return issues


def run_sync_check(source_roots):
    cmd = [sys.executable, str(SYNC_SCRIPT), "check"]
    if source_roots:
        cmd.extend(["--source-roots", source_roots])
    result = subprocess.run(cmd, cwd=ROOT, text=True, capture_output=True)
    payload = {"exit_code": result.returncode, "stdout": result.stdout.strip(), "stderr": result.stderr.strip()}
    try:
        payload["json"] = json.loads(result.stdout)
    except json.JSONDecodeError:
        pass
    return payload


def main():
    parser = argparse.ArgumentParser(description="Audit Codex migration hygiene")
    parser.add_argument("--source-roots", default="", help="Optional source roots for sync_reference_skills.py check")
    parser.add_argument("--skip-sync-check", action="store_true")
    parser.add_argument("--json", action="store_true", help="Emit JSON only")
    args = parser.parse_args()

    scan_paths = [REFERENCE_SKILLS, ROOT / "scripts", ROOT / "api", ROOT / "platform", ROOT / "docs", ROOT / "README.md"]
    issues = scan_files(scan_paths)
    sync_result = None if args.skip_sync_check else run_sync_check(args.source_roots)
    sync_ok = True if sync_result is None else sync_result["exit_code"] == 0

    result = {
        "status": "pass" if not issues and sync_ok else "fail",
        "issues": issues,
        "sync_check": sync_result,
    }

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Codex migration audit: {result['status'].upper()}")
        if sync_result is not None:
            print(f"sync_reference_skills.py check exit={sync_result['exit_code']}")
            if sync_result.get("stdout"):
                print(sync_result["stdout"])
            if sync_result.get("stderr"):
                print(sync_result["stderr"], file=sys.stderr)
        if issues:
            print("\nIssues:")
            for item in issues:
                line = f":{item['line']}" if "line" in item else ""
                print(f"- {item['path']}{line} [{item['kind']}] {item['match']}")
        else:
            print("No legacy harness paths, retired flags, plaintext helper credentials, or forbidden bundle files found.")

    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    sys.exit(main())
