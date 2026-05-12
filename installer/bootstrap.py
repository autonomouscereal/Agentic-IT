#!/usr/bin/env python3
"""One-line bootstrapper for the agentic IT/SOC platform control plane.

This installer is intentionally conservative: it deploys the dashboard/control
plane, writes a local setup plan, and sends the operator into the setup wizard
where provider integrations and reference module deployments are tracked as
tickets with approvals. It does not store plaintext product credentials.
"""
import argparse
import json
import os
import re
import secrets
import shutil
import stat
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TARGET = Path(os.getenv("SOC_PLATFORM_HOME", Path.home() / "soc-platform"))


def parse_args():
    parser = argparse.ArgumentParser(description="Install the agentic IT/SOC control plane")
    parser.add_argument("--profile", choices=["minimal", "soc", "full-it"], default="soc")
    parser.add_argument("--target", default=str(DEFAULT_TARGET), help="Deployment directory")
    parser.add_argument("--source", default=str(ROOT), help="Source directory or copied release checkout")
    parser.add_argument("--dashboard-port", default="25480")
    parser.add_argument("--db-port", default="5433")
    parser.add_argument("--project-name", default=os.getenv("COMPOSE_PROJECT_NAME", ""))
    parser.add_argument("--ai-base-url", default=os.getenv("AGENT_LLM_BASE_URL", ""))
    parser.add_argument("--model", default=os.getenv("AGENT_MODEL", "qwen/qwen3.6-27b"))
    parser.add_argument("--itop-sync-enabled", default=os.getenv("ITOP_SYNC_ENABLED", "false"))
    parser.add_argument("--non-interactive", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-start", action="store_true")
    return parser.parse_args()


def project_name(target, explicit):
    if explicit:
        raw = explicit
    else:
        raw = f"soc-{Path(target).name}"
    name = re.sub(r"[^a-z0-9_-]+", "-", raw.lower()).strip("-_")
    return name or "soc-platform"


def log_event(target, event, details):
    state_dir = target / "install_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    record = {
        "time": datetime.now(timezone.utc).isoformat(),
        "event": event,
        "details": details,
    }
    with (state_dir / "install-log.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def copy_source(source, target, dry_run=False):
    source = Path(source).resolve()
    target = Path(target).resolve()
    if source == target:
        return
    if dry_run:
        return
    target.mkdir(parents=True, exist_ok=True)
    ignore = shutil.ignore_patterns(
        ".git", "__pycache__", "*.pyc", ".env", "docker-compose.override.yml",
        "agent_work", "data", "install_state", "runtime"
    )
    for item in source.iterdir():
        destination = target / item.name
        if item.name in {".env", "docker-compose.override.yml", "agent_work", "data", "install_state", "runtime"}:
            continue
        if item.is_dir():
            if destination.exists():
                shutil.rmtree(destination)
            shutil.copytree(item, destination, ignore=ignore)
        else:
            shutil.copy2(item, destination)


def write_env(target, args, dry_run=False):
    env_path = target / ".env"
    if env_path.exists():
        return "existing"
    db_password = secrets.token_urlsafe(32)
    agent_memory_db_password = secrets.token_urlsafe(32)
    compose_project = project_name(target, args.project_name)
    env = {
        "COMPOSE_PROJECT_NAME": compose_project,
        "DASHBOARD_PORT": args.dashboard_port,
        "SOC_DB_PORT": args.db_port,
        "SOC_DB_USER": "soc_user",
        "SOC_DB_PASSWORD": db_password,
        "AGENT_MEMORY_DB_PASSWORD": agent_memory_db_password,
        "AGENT_MEMORY_DB_PORT": "25490",
        "MEMORY_DB_HOST": "agent-memory-db",
        "MEMORY_DB_PORT": "5432",
        "MEMORY_DB_NAME": "agent_memory",
        "MEMORY_DB_USER": "agent_memory",
        "ITOP_SYNC_ENABLED": args.itop_sync_enabled,
        "ITOP_HOST": "",
        "ITOP_PORT": "25432",
        "ITOP_WEB_BASE": "",
        "ITOP_USER": "",
        "ITOP_PASSWORD": "",
        "ITOP_SECURITY_TEAM_ID": "65",
        "ITOP_DEFAULT_ORG_ID": "",
        "ITOP_DEFAULT_CALLER_ID": "",
        "SERVICENOW_INSTANCE_URL": "",
        "SERVICENOW_TOKEN": "",
        "SERVICENOW_USER": "",
        "SERVICENOW_PASSWORD": "",
        "SERVICENOW_ASSIGNMENT_GROUP": "",
        "SERVICENOW_REQUEST_TABLE": "sc_request",
        "JIRA_BASE_URL": "",
        "JIRA_EMAIL": "",
        "JIRA_API_TOKEN": "",
        "JIRA_PROJECT_KEY": "",
        "JIRA_ISSUE_TYPE": "Task",
        "GENERIC_TICKETING_WEBHOOK_URL": "",
        "GENERIC_TICKETING_WEBHOOK_TOKEN": "",
        "GENERIC_TICKETING_DRY_RUN": "false",
        "ITOP_DISCOVERY_INTERVAL": "2",
        "ITOP_FULL_SYNC_INTERVAL": "60",
        "HEALTH_CHECK_INTERVAL": "60",
        "MAX_CONCURRENT_AGENTS": "3",
        "AGENT_TIMEOUT_MINUTES": "0",
        "AGENT_AUDITOR_AUTO_RECOVER": "false",
        "AGENT_HARNESS": "claude-code",
        "AGENT_PERMISSION_MODE": "acceptEdits",
        "AGENT_ALLOWED_TOOLS": "Read,Write,Bash(curl *)",
        "AGENT_LLM_BASE_URL": args.ai_base_url,
        "AGENT_LLM_AUTH_TOKEN": os.getenv("AGENT_LLM_AUTH_TOKEN", "lmstudio"),
        "DASHBOARD_API_BASE": "http://localhost:8000",
        "TRACK_INTERVAL": "10",
        "STUCK_TIMEOUT_MINUTES": "60",
        "CLAUDE_CREDENTIALS_FILE": os.getenv("CLAUDE_CREDENTIALS_FILE", "./runtime/empty_credentials.json"),
        "CLAUDE_SETTINGS_FILE": os.getenv("CLAUDE_SETTINGS_FILE", "./runtime/claude_settings.json"),
        "CLAUDE_SKILLS_DIR": os.getenv("CLAUDE_SKILLS_DIR", "./reference_skills"),
        "AGENTS_SKILLS_DIR": os.getenv("AGENTS_SKILLS_DIR", "./reference_skills"),
    }
    if dry_run:
        return "would_create"
    with env_path.open("w", encoding="utf-8", newline="\n") as handle:
        for key, value in env.items():
            handle.write(f"{key}={value}\n")
    try:
        env_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass
    return "created"


def write_compose_override(target, args, dry_run=False):
    text = """# Reserved for site-specific compose overrides.
# The installer now writes ports and project name to .env so multiple installs
# can run side-by-side without fixed container names.
"""
    if dry_run:
        return
    (target / "docker-compose.override.yml").write_text(text, encoding="utf-8", newline="\n")


def read_manifest(target):
    manifest_path = target / "platform" / "manifest.json"
    with manifest_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_initial_plan(target, args, dry_run=False):
    manifest = read_manifest(target if not dry_run else ROOT)
    profile = manifest.get("profiles", {}).get(args.profile, {})
    selected = set(profile.get("modules", []))
    modules = [m for m in manifest.get("modules", []) if m.get("id") in selected]
    plan = {
        "profile": args.profile,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "ai_base_url": args.ai_base_url,
        "model": args.model,
        "operator_next_step": f"Open http://localhost:{args.dashboard_port} and use Setup to mark existing products or deploy gaps.",
        "modules": [
            {
                "id": module.get("id"),
                "name": module.get("name"),
                "category": module.get("category"),
                "default_action": "integrate_existing_or_deploy_reference",
                "skill": module.get("skill"),
            }
            for module in modules
        ],
    }
    if not dry_run:
        state_dir = target / "install_state"
        state_dir.mkdir(parents=True, exist_ok=True)
        (state_dir / "last-plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return plan


def run(command, cwd, dry_run=False):
    if dry_run:
        print("DRY RUN:", " ".join(command))
        return
    subprocess.run(command, cwd=str(cwd), check=True)


def apply_migrations(target, dry_run=False):
    migrations_dir = target / "api" / "migrations"
    if not migrations_dir.exists():
        return []
    applied = []
    for migration in sorted(migrations_dir.glob("*.sql")):
        if dry_run:
            print("DRY RUN: apply migration", migration.name)
            applied.append(migration.name)
            continue
        sql = migration.read_text(encoding="utf-8")
        subprocess.run(
            ["docker", "compose", "exec", "-T", "db", "sh", "-c", 'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB"'],
            cwd=str(target),
            input=sql,
            text=True,
            check=True,
        )
        applied.append(migration.name)
    return applied


def main():
    args = parse_args()
    source = Path(args.source).resolve()
    target = Path(args.target).resolve()

    if not args.ai_base_url and not args.dry_run:
        print("AGENT_LLM_BASE_URL is empty. The dashboard will install, but agent spawning needs an AI endpoint configured in .env or Setup.")

    if not args.dry_run:
        target.mkdir(parents=True, exist_ok=True)
    copy_source(source, target, args.dry_run)
    env_status = write_env(target, args, args.dry_run)
    write_compose_override(target, args, args.dry_run)
    plan = write_initial_plan(target, args, args.dry_run)

    if not args.dry_run:
        (target / "data" / "agent_logs").mkdir(parents=True, exist_ok=True)
        (target / "agent_work").mkdir(parents=True, exist_ok=True)
        runtime = target / "runtime"
        runtime.mkdir(parents=True, exist_ok=True)
        empty_creds = runtime / "empty_credentials.json"
        if not empty_creds.exists():
            empty_creds.write_text("{}", encoding="utf-8")
            try:
                empty_creds.chmod(stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass
        claude_settings = runtime / "claude_settings.json"
        if not claude_settings.exists():
            settings = {
                "env": {
                    "ANTHROPIC_BASE_URL": args.ai_base_url,
                    "ANTHROPIC_AUTH_TOKEN": os.getenv("AGENT_LLM_AUTH_TOKEN", "lmstudio"),
                },
                "model": args.model,
            }
            claude_settings.write_text(json.dumps(settings, indent=2), encoding="utf-8")
        active_agents = target / "data" / "active_agents.json"
        if not active_agents.exists():
            active_agents.write_text("{}", encoding="utf-8")
        log_event(target, "bootstrap_prepared", {
            "profile": args.profile,
            "env": env_status,
            "dashboard_port": args.dashboard_port,
            "db_port": args.db_port,
        })

    if not args.no_start:
        run(["docker", "compose", "up", "-d", "--build"], target, args.dry_run)
        migrations = apply_migrations(target, args.dry_run)
        if not args.dry_run:
            log_event(target, "docker_started", {"profile": args.profile, "migrations": migrations})

    print(json.dumps({
        "status": "dry_run" if args.dry_run else "installed",
        "target": str(target),
        "profile": args.profile,
        "dashboard_url": f"http://localhost:{args.dashboard_port}",
        "next_step": plan["operator_next_step"],
    }, indent=2))


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        print(f"Installer command failed with exit code {exc.returncode}: {exc.cmd}", file=sys.stderr)
        sys.exit(exc.returncode)
