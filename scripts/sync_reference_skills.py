#!/usr/bin/env python3
"""Synchronize production skills into or out of the portable reference bundle.

The bundle is deliberately allowlisted and sanitized. It exists so dashboard
agents can read the same skills used by the harness, while Git can track the
deployable platform contract without copying vaults, venvs, logs, caches, or
unrelated media tooling.
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import text_hygiene


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "platform" / "skill_sync_config.json"
DEFAULT_BUNDLE = ROOT / "reference_skills"


def load_config():
    with CONFIG_PATH.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def split_paths(raw):
    return [Path(item.strip()).expanduser() for item in raw.split(os.pathsep) if item.strip()]


def source_roots(config, explicit):
    roots = []
    if explicit:
        roots.extend(split_paths(explicit))
    env_roots = os.getenv("PLATFORM_SKILL_SOURCE_ROOTS")
    if env_roots and not explicit:
        roots.extend(split_paths(env_roots))
    if not explicit and not env_roots:
        roots.extend(Path(item).expanduser() for item in config.get("default_source_roots", []))
        home = Path.home()
        roots.extend([
            home / ".agents" / "skills",
            home / ".claude" / "skills",
        ])
    unique = []
    seen = set()
    for root in roots:
        key = str(root)
        try:
            exists = root.exists()
        except OSError:
            exists = False
        if key not in seen and exists:
            seen.add(key)
            unique.append(root)
    return unique


def is_excluded(path, config):
    parts = set(path.parts)
    if parts.intersection(set(config.get("exclude_names", []))):
        return True
    if path.name in set(config.get("exclude_exact_files", [])):
        return True
    lower = path.name.lower()
    return any(lower.endswith(suffix.lower()) for suffix in config.get("exclude_suffixes", []))


def sha256(path):
    digest = hashlib.sha256()
    digest.update(sanitized_bytes(path))
    return digest.hexdigest()


def should_sanitize(path):
    return text_hygiene.is_text_file(path)


def sanitized_bytes(path):
    if should_sanitize(path):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return path.read_bytes()
        text = text_hygiene.fix_text(text, include_lab_values=True)
        return text.encode("utf-8")
    return path.read_bytes()


def skill_manifest(skill_dir):
    files = []
    for path in sorted(skill_dir.rglob("*")):
        if path.is_file():
            if is_excluded(path.relative_to(skill_dir), load_config()) or is_excluded(path, load_config()):
                continue
            rel = path.relative_to(skill_dir).as_posix()
            files.append({
                "path": rel,
                "size": path.stat().st_size,
                "sha256": sha256(path),
            })
    return files


def find_skill(skill, roots):
    for root in roots:
        candidate = root / skill
        if (candidate / "SKILL.md").exists():
            return candidate
    return None


def assert_inside(child, parent):
    child = child.resolve()
    parent = parent.resolve()
    if child != parent and parent not in child.parents:
        raise RuntimeError(f"Refusing to modify {child}; expected it under {parent}")


def copy_skill(src, dest, config):
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True, exist_ok=True)
    copied = 0
    skipped = 0
    for path in src.rglob("*"):
        rel = path.relative_to(src)
        if is_excluded(rel, config) or is_excluded(path, config):
            skipped += 1
            continue
        target = dest / rel
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            if should_sanitize(path):
                try:
                    text = path.read_text(encoding="utf-8")
                    text = text_hygiene.fix_text(text, include_lab_values=True)
                    target.write_text(text, encoding="utf-8", newline="\n")
                    shutil.copystat(path, target, follow_symlinks=True)
                except UnicodeDecodeError:
                    shutil.copy2(path, target)
            else:
                shutil.copy2(path, target)
            copied += 1
    return copied, skipped


def write_bundle_manifest(bundle, records):
    manifest = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "config": str(CONFIG_PATH),
        "skills": records,
    }
    bundle.mkdir(parents=True, exist_ok=True)
    (bundle / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8", newline="\n")
    return manifest


def manifest(args, config):
    bundle = Path(args.bundle).resolve()
    assert_inside(bundle, ROOT)
    records = []
    missing = []
    for skill in config["skills"]:
        skill_dir = bundle / skill
        if not (skill_dir / "SKILL.md").exists():
            missing.append(skill)
            continue
        records.append({
            "name": skill,
            "source": "bundle",
            "files": skill_manifest(skill_dir),
        })
    write_bundle_manifest(bundle, records)
    print(json.dumps({
        "status": "manifest",
        "bundle": str(bundle),
        "skills": len(records),
        "missing": missing,
    }, indent=2))
    return 1 if missing else 0


def stage(args, config):
    bundle = Path(args.bundle).resolve()
    assert_inside(bundle, ROOT)
    roots = source_roots(config, args.source_roots)
    records = []
    missing = []
    for skill in config["skills"]:
        src = find_skill(skill, roots)
        if not src:
            missing.append(skill)
            continue
        dest = bundle / skill
        copied, skipped = copy_skill(src, dest, config)
        records.append({
            "name": skill,
            "source": str(src),
            "files": skill_manifest(dest),
            "copied_files": copied,
            "skipped_paths": skipped,
        })
    manifest = write_bundle_manifest(bundle, records)
    result = {"status": "staged", "bundle": str(bundle), "skills": len(records), "missing": missing}
    print(json.dumps(result, indent=2))
    if missing:
        return 2
    return 0


def check(args, config):
    bundle = Path(args.bundle).resolve()
    roots = source_roots(config, args.source_roots)
    drift = []
    missing = []
    for skill in config["skills"]:
        src = find_skill(skill, roots)
        dest = bundle / skill
        if not src or not dest.exists():
            missing.append(skill)
            continue
        src_files = {item["path"]: item["sha256"] for item in skill_manifest(src) if not is_excluded(Path(item["path"]), config)}
        dest_files = {item["path"]: item["sha256"] for item in skill_manifest(dest)}
        if src_files != dest_files:
            drift.append(skill)
    print(json.dumps({"status": "ok" if not drift and not missing else "drift", "drift": drift, "missing": missing}, indent=2))
    return 1 if drift or missing else 0


def install(args, config):
    bundle = Path(args.bundle).resolve()
    destination = Path(args.destination).expanduser().resolve()
    if not destination:
        raise RuntimeError("--destination is required for install mode")
    records = []
    for skill in config["skills"]:
        src = bundle / skill
        if not (src / "SKILL.md").exists():
            continue
        dest = destination / skill
        copied, skipped = copy_skill(src, dest, config)
        records.append({"name": skill, "destination": str(dest), "copied_files": copied, "skipped_paths": skipped})
    print(json.dumps({"status": "installed", "destination": str(destination), "skills": records}, indent=2))
    return 0


def main():
    parser = argparse.ArgumentParser(description="Sync platform reference skills")
    parser.add_argument("mode", choices=["stage", "check", "install", "manifest"])
    parser.add_argument("--bundle", default=str(DEFAULT_BUNDLE))
    parser.add_argument("--source-roots", default="", help=f"Optional {os.pathsep}-separated source roots")
    parser.add_argument("--destination", default="", help="Destination skill root for install mode")
    args = parser.parse_args()
    config = load_config()
    if args.mode == "manifest":
        return manifest(args, config)
    if args.mode == "stage":
        return stage(args, config)
    if args.mode == "check":
        return check(args, config)
    if args.mode == "install":
        return install(args, config)
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
