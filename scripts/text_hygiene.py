#!/usr/bin/env python3
"""Check and fix common text hygiene problems in repository files."""

from __future__ import annotations

import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

SKIP_PARTS = {
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}

TEXT_SUFFIXES = {
    ".css",
    ".env",
    ".example",
    ".html",
    ".js",
    ".json",
    ".md",
    ".py",
    ".rb",
    ".sh",
    ".sql",
    ".toml",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}

# Keys are written with escapes so this script does not contain the bad text
# it is designed to block.
MOJIBAKE_REPLACEMENTS = {
    "\u00e2\u20ac\u201d": "-",
    "\u00e2\u20ac\u201c": "-",
    "\u00e2\u20ac\u2018": "-",
    "\u00e2\u20ac": "-",
    "\u00e2\u20ac\u2122": "'",
    "\u00e2\u20ac\u02dc": "'",
    "\u00e2\u20ac\u0153": '"',
    "\u00e2\u20ac\ufffd": '"',
    "\u00e2\u20ac\u00a6": "...",
    "\u00e2\u20ac\u00a2": "-",
    "\u00e2\u2020\u2019": "->",
    "\u00e2\u2020\u201c": "v",
    "\u00e2\u201d\u20ac": "-",
    "\u00e2\u201d\u201a": "|",
    "\u00e2\u201d\u0153": "|",
    "\u00e2\u201d\u201d": "`",
    "\u00e2\u201e\u00a2": "(TM)",
    "\u00c3\u2014": "x",
    "\u00c3\u00a9": "e",
    "\u00c3\u00a8": "e",
    "\u00c3\u00b1": "n",
    "\ufffd": "?",
    "\u2014": "-",
    "\u2013": "-",
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2026": "...",
    "\u2022": "-",
    "\u2192": "->",
    "\u2193": "v",
    "\u2500": "-",
    "\u2501": "-",
    "\u2502": "|",
    "\u250c": "+",
    "\u2510": "+",
    "\u251c": "|",
    "\u2514": "`",
    "\u2518": "'",
    "\u2524": "|",
    "\u252c": "+",
    "\u2550": "=",
    "\u2551": "|",
    "\u2554": "+",
    "\u2557": "+",
    "\u255a": "+",
    "\u255d": "+",
    "\u2122": "(TM)",
    "\u00d7": "x",
    "\u25ba": ">",
    "\u25b6": ">",
    "\u25bc": "v",
    "\U0001f916": "",
}

FORBIDDEN_FRAGMENTS = sorted(MOJIBAKE_REPLACEMENTS)

LAB_VALUE_REPLACEMENTS = {
    "192.168." + "50.0/24": "<trusted-subnet-cidr>",
    "192.168." + "50.222": "127.0.0.1",
    "192.168." + "50.250": "127.0.0.1",
    "C:/Users/" + "cereal": "C:/Users/me",
    "C:\\Users\\" + "cereal": "C:\\Users\\me",
    "/home/" + "cereal": "/opt/agentic-it",
}

LAB_SCAN_ROOTS = {
    "reference_skills",
    "scripts",
    "docs",
    "deploy",
    "frontend",
    "api",
    "installer",
    "platform",
}

ROOT_LAB_FILES = {
    ".env.example",
    "README.md",
    "docker-compose.yml",
    "install.ps1",
    "install.sh",
}


def is_text_file(path: Path) -> bool:
    if path == Path(__file__).resolve():
        return False
    if any(part in SKIP_PARTS for part in path.parts):
        return False
    if not path.is_file():
        return False
    if path.name in {".env.example", ".env.template"}:
        return True
    return path.suffix.lower() in TEXT_SUFFIXES


def iter_files():
    for path in ROOT.rglob("*"):
        if is_text_file(path):
            yield path


def fix_text(text: str, include_lab_values: bool) -> str:
    fixed = text
    for old, new in MOJIBAKE_REPLACEMENTS.items():
        fixed = fixed.replace(old, new)
    if include_lab_values:
        for old, new in LAB_VALUE_REPLACEMENTS.items():
            fixed = fixed.replace(old, new)
    return fixed


def scan_text(path: Path, text: str, include_lab_values: bool):
    findings = []
    for marker in FORBIDDEN_FRAGMENTS:
        if marker in text:
            findings.append(f"{path.relative_to(ROOT)}: contains mojibake marker {marker!r}")
    rel_parts = path.relative_to(ROOT).parts
    should_check_lab = rel_parts and (
        rel_parts[0] in LAB_SCAN_ROOTS or path.relative_to(ROOT).as_posix() in ROOT_LAB_FILES
    )
    if include_lab_values and should_check_lab:
        for marker in LAB_VALUE_REPLACEMENTS:
            if marker in text:
                findings.append(f"{path.relative_to(ROOT)}: contains lab-specific value {marker!r}")
    return findings


def main():
    parser = argparse.ArgumentParser(description="Check or fix repository text hygiene.")
    parser.add_argument("--fix", action="store_true", help="Rewrite files in place.")
    parser.add_argument("--check-lab-values", action="store_true", help="Also check for lab host/user path literals.")
    args = parser.parse_args()

    findings = []
    changed = []
    for path in iter_files():
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        if args.fix:
            fixed = fix_text(text, args.check_lab_values)
            if fixed != text:
                path.write_text(fixed, encoding="utf-8", newline="\n")
                changed.append(path.relative_to(ROOT).as_posix())
            text = fixed

        findings.extend(scan_text(path, text, args.check_lab_values))

    if args.fix:
        for item in changed:
            print(f"fixed {item}")

    if findings:
        for finding in findings:
            print(finding)
        raise SystemExit(1)

    print("text hygiene check passed")


if __name__ == "__main__":
    main()
