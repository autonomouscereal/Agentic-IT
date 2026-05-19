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
import ssl
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
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
    parser.add_argument("--https-port", default=os.getenv("DASHBOARD_HTTPS_PORT", "25443"))
    parser.add_argument("--disable-https", action="store_true")
    parser.add_argument("--tls-common-name", default=os.getenv("DASHBOARD_TLS_COMMON_NAME", "agentic-operations.local"))
    parser.add_argument("--tls-days", default=os.getenv("DASHBOARD_TLS_DAYS", "825"))
    parser.add_argument("--db-port", default="5433")
    parser.add_argument("--memory-db-port", default=os.getenv("AGENT_MEMORY_DB_PORT", "25490"))
    parser.add_argument("--project-name", default=os.getenv("COMPOSE_PROJECT_NAME", ""))
    parser.add_argument("--ai-base-url", default=os.getenv("AGENT_LLM_BASE_URL", ""))
    parser.add_argument("--harness", choices=["auto", "hermes", "claude-code"], default=os.getenv("AGENT_HARNESS", "auto"))
    parser.add_argument("--proxy-mode", choices=["deploy", "external"], default=os.getenv("AI_PROXY_MODE", "deploy"))
    parser.add_argument("--proxy-port", default=os.getenv("AI_PROXY_PORT", "4001"))
    parser.add_argument("--provider", choices=["openai", "anthropic", "nous", "lmstudio", "custom"], default=os.getenv("AGENT_PROVIDER", "nous"))
    parser.add_argument("--provider-base-url", default=os.getenv("PROVIDER_BASE_URL", ""))
    parser.add_argument("--model", default=os.getenv("AGENT_MODEL", "deepseek/deepseek-v4-flash"))
    parser.add_argument("--spawn-setup-agent", action="store_true")
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


def detect_host_ip():
    override = os.getenv("SOC_PLATFORM_HOST")
    if override:
        return override
    try:
        completed = subprocess.run(
            ["hostname", "-I"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        for item in completed.stdout.split():
            if "." in item and not item.startswith("127."):
                return item
    except Exception:
        pass
    return "localhost"


def prompt_default(question, default, choices=None):
    suffix = f" [{default}]"
    while True:
        value = input(f"{question}{suffix}: ").strip() or default
        if not choices or value in choices:
            return value
        print(f"Choose one of: {', '.join(choices)}")


def configure_interactive(args):
    if args.non_interactive or args.dry_run:
        return args
    args.proxy_mode = prompt_default("Proxy mode", args.proxy_mode, ["deploy", "external"])
    args.harness = prompt_default("Agent harness", args.harness, ["auto", "hermes", "claude-code"])
    args.provider = prompt_default("Default provider", args.provider, ["openai", "anthropic", "nous", "lmstudio", "custom"])
    args.model = prompt_default("Default model", args.model)
    if args.proxy_mode == "external" and not args.ai_base_url:
        args.ai_base_url = prompt_default("External proxy base URL", "http://localhost:4001")
    if not args.spawn_setup_agent:
        spawn = prompt_default("Spawn setup agent after install", "no", ["yes", "no"])
        args.spawn_setup_agent = spawn == "yes"
    return args


def hermes_available():
    hermes_bin = os.getenv("HERMES_BIN", "/home/cereal/.hermes/hermes-agent/venv/bin/hermes")
    return Path(hermes_bin).exists() or bool(shutil.which("hermes"))


def selected_harness(args):
    if args.harness != "auto":
        return args.harness
    return "hermes" if hermes_available() else "claude-code"


def agent_base_url(args):
    if args.proxy_mode == "external":
        return args.ai_base_url or os.getenv("AGENT_LLM_BASE_URL", "")
    return "http://ai-proxy:4001"


def operator_proxy_url(args, host):
    if args.proxy_mode == "external" and args.ai_base_url:
        return args.ai_base_url
    # The built-in proxy is bound to 127.0.0.1 by default. Keep the printed
    # operator URL honest and local-only; spawned agents use agent_base_url().
    return f"http://localhost:{args.proxy_port}"


def local_proxy_url(args):
    if args.proxy_mode == "external":
        return args.ai_base_url or os.getenv("AGENT_LLM_BASE_URL", "")
    return f"http://localhost:{args.proxy_port}"


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
    harness = selected_harness(args)
    llm_base_url = agent_base_url(args)
    env = {
        "COMPOSE_PROJECT_NAME": compose_project,
        "DASHBOARD_PORT": args.dashboard_port,
        "DASHBOARD_BIND": "127.0.0.1",
        "DASHBOARD_HTTPS_PORT": args.https_port,
        "DASHBOARD_HTTPS_BIND": "0.0.0.0",
        "DASHBOARD_TLS_DIR": "./runtime/tls",
        "DASHBOARD_TLS_COMMON_NAME": args.tls_common_name,
        "DASHBOARD_TLS_DAYS": args.tls_days,
        "SOC_DB_PORT": args.db_port,
        "SOC_DB_BIND": "127.0.0.1",
        "AGENT_MEMORY_DB_BIND": "127.0.0.1",
        "AI_PROXY_BIND": "127.0.0.1",
        "AI_PROXY_MODE": args.proxy_mode,
        "AI_PROXY_PORT": args.proxy_port,
        "PROXY_CONFIG_PATH": "./runtime/proxy_config.json",
        "LM_STUDIO_BASE": os.getenv("LM_STUDIO_BASE", "http://host.docker.internal:1234"),
        "LM_STUDIO_TOKEN": os.getenv("LM_STUDIO_TOKEN", "lmstudio"),
        "ANTHROPIC_BASE": os.getenv("ANTHROPIC_BASE", "https://api.anthropic.com"),
        "NOUS_BASE": os.getenv("NOUS_BASE", "https://inference-api.nousresearch.com/v1"),
        "OPENAI_BASE": os.getenv("OPENAI_BASE", "https://api.openai.com/v1"),
        "CUSTOM_PROVIDER_BASE": args.provider_base_url if args.provider == "custom" else os.getenv("CUSTOM_PROVIDER_BASE", ""),
        "NOUS_API_KEY": "",
        "OPENAI_API_KEY": "",
        "ANTHROPIC_API_KEY": "",
        "CUSTOM_PROVIDER_API_KEY": "",
        "SOC_DB_USER": "soc_user",
        "SOC_DB_PASSWORD": db_password,
        "AGENT_MEMORY_DB_PASSWORD": agent_memory_db_password,
        "AGENT_MEMORY_DB_PORT": args.memory_db_port,
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
        "MAX_CONCURRENT_AGENTS": "1",
        "AGENT_TIMEOUT_MINUTES": "0",
        "AGENT_NO_OUTPUT_STALL_SECONDS": "3600",
        "AUTO_ASSIGNMENT_MAX_ACTIVE_PER_RULE": "1",
        "AGENT_AUDITOR_AUTO_RECOVER": "false",
        "AGENT_HARNESS": harness,
        "AGENT_DEFAULT_MODEL": args.model,
        "AGENT_PERMISSION_MODE": "acceptEdits",
        "AGENT_ALLOWED_TOOLS": "Read,Write,Bash(curl *)",
        "AGENT_LLM_BASE_URL": llm_base_url,
        "AGENT_LLM_AUTH_TOKEN": os.getenv("AGENT_LLM_AUTH_TOKEN", ""),
        "HERMES_BIN": os.getenv("HERMES_BIN", "/home/cereal/.hermes/hermes-agent/venv/bin/hermes"),
        "HERMES_HOME": os.getenv("HERMES_HOME", "/home/cereal/.hermes"),
        "HERMES_HOME_DIR": os.getenv("HERMES_HOME_DIR", "./runtime/hermes"),
        "HERMES_UV_PYTHON_DIR": os.getenv("HERMES_UV_PYTHON_DIR", "./runtime/hermes-uv-python"),
        "HERMES_DEFAULT_PROVIDER": os.getenv("HERMES_DEFAULT_PROVIDER", "nous"),
        "HERMES_LOCAL_PROVIDER": os.getenv("HERMES_LOCAL_PROVIDER", "dashboard-proxy"),
        "HERMES_TOOLSETS": os.getenv("HERMES_TOOLSETS", "terminal,file"),
        "HERMES_RUN_AS_UID": os.getenv("HERMES_RUN_AS_UID", "1000"),
        "HERMES_RUN_AS_GID": os.getenv("HERMES_RUN_AS_GID", "1000"),
        "DASHBOARD_API_BASE": "http://localhost:8000",
        "DASHBOARD_AUTH_MODE": "header",
        "DASHBOARD_AUTH_ENFORCEMENT": "enforce",
        "DASHBOARD_TRUSTED_AUTH_SECRET": secrets.token_urlsafe(48),
        "DASHBOARD_SERVICE_TOKEN": secrets.token_urlsafe(48),
        "DASHBOARD_SESSION_SECRET": secrets.token_urlsafe(64),
        "DASHBOARD_COOKIE_SECURE": "true",
        "DASHBOARD_PROTECT_UI": "true",
        "DASHBOARD_PUBLIC_HEALTH": "false",
        "DASHBOARD_CORS_ORIGINS": "",
        "DASHBOARD_HSTS": "true",
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


def read_env_file(target):
    values = {}
    env_path = target / ".env"
    if not env_path.exists():
        return values
    for line in env_path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def write_compose_override(target, args, dry_run=False):
    text = """# Reserved for site-specific compose overrides.
# The installer now writes ports and project name to .env so multiple installs
# can run side-by-side without fixed container names.
"""
    if dry_run:
        return
    (target / "docker-compose.override.yml").write_text(text, encoding="utf-8", newline="\n")


def provider_base(args, provider):
    if args.provider == provider and args.provider_base_url:
        return args.provider_base_url.rstrip("/")
    defaults = {
        "lmstudio": os.getenv("LM_STUDIO_BASE", "http://host.docker.internal:1234"),
        "nous": os.getenv("NOUS_BASE", "https://inference-api.nousresearch.com/v1"),
        "anthropic": os.getenv("ANTHROPIC_BASE", "https://api.anthropic.com"),
        "openai": os.getenv("OPENAI_BASE", "https://api.openai.com/v1"),
        "custom": os.getenv("CUSTOM_PROVIDER_BASE", ""),
    }
    return defaults.get(provider, "").rstrip("/")


def write_proxy_config(target, args, dry_run=False):
    config = {
        "version": 1,
        "default_provider": args.provider,
        "default_model": args.model,
        "local_models": [
            {"id": "qwen/qwen3.6-27b", "weight": 3},
            {"id": "qwen/qwen3.6-27b2", "weight": 1},
            {"id": "qwen/qwen3.6-27b3", "weight": 1},
        ],
        "providers": {
            "lmstudio": {
                "base_url": provider_base(args, "lmstudio"),
                "token_env": "LM_STUDIO_TOKEN",
                "models": ["qwen/qwen3.6-27b", "qwen/qwen3.6-27b2", "qwen/qwen3.6-27b3"],
            },
            "nous": {
                "base_url": provider_base(args, "nous"),
                "token_env": "NOUS_API_KEY",
                "models": ["deepseek/deepseek-v4-flash", "deepseek-v4-flash"],
            },
            "anthropic": {
                "base_url": provider_base(args, "anthropic"),
                "token_env": "ANTHROPIC_API_KEY",
                "models": ["claude-opus-4-7", "claude-sonnet-4-6", "claude-haiku-4-5-20251001"],
            },
            "openai": {
                "base_url": provider_base(args, "openai"),
                "token_env": "OPENAI_API_KEY",
                "models": ["gpt-5.2", "gpt-5.2-mini"],
            },
            "custom": {
                "base_url": provider_base(args, "custom"),
                "token_env": "CUSTOM_PROVIDER_API_KEY",
                "models": [args.model] if args.provider == "custom" else [],
            },
        },
    }
    if args.provider == "lmstudio" and args.model not in [m["id"] for m in config["local_models"]]:
        config["local_models"].insert(0, {"id": args.model, "weight": 1})
        config["providers"]["lmstudio"]["models"].insert(0, args.model)
    if args.provider == "nous" and args.model not in config["providers"]["nous"]["models"]:
        config["providers"]["nous"]["models"].insert(0, args.model)
    if args.provider == "openai" and args.model not in config["providers"]["openai"]["models"]:
        config["providers"]["openai"]["models"].insert(0, args.model)
    if args.provider == "anthropic" and args.model not in config["providers"]["anthropic"]["models"]:
        config["providers"]["anthropic"]["models"].insert(0, args.model)
    if dry_run:
        print("DRY RUN: write runtime/proxy_config.json")
        return config
    runtime = target / "runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    (runtime / "proxy_config.json").write_text(json.dumps(config, indent=2), encoding="utf-8", newline="\n")
    return config


def write_agent_models(target, args, dry_run=False):
    models_path = (target if not dry_run else ROOT) / "agent_models.json"
    try:
        data = json.loads(models_path.read_text(encoding="utf-8"))
    except Exception:
        data = {"models": [], "default": args.model}
    models = list(data.get("models") or [])
    if args.model not in models:
        models.insert(0, args.model)
    data["models"] = models
    data["default"] = args.model
    if dry_run:
        print("DRY RUN: update agent_models.json default", args.model)
        return data
    models_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")
    return data


def ensure_tls_assets(target, args, host, dry_run=False):
    if args.disable_https:
        return {"status": "disabled"}
    if dry_run:
        print("DRY RUN: generate runtime/tls dashboard local CA and server certificate")
        return {"status": "dry_run", "https_port": args.https_port}
    env = dict(os.environ)
    existing_ips = [item.strip() for item in env.get("DASHBOARD_TLS_EXTRA_IPS", "").split(",") if item.strip()]
    env["DASHBOARD_TLS_EXTRA_IPS"] = ",".join(sorted(set(existing_ips + [host])))
    env["DASHBOARD_TLS_COMMON_NAME"] = args.tls_common_name
    env["DASHBOARD_TLS_DAYS"] = str(args.tls_days)
    subprocess.run(
        [
            sys.executable,
            "scripts/generate_dashboard_tls.py",
            "--out-dir",
            "runtime/tls",
            "--common-name",
            args.tls_common_name,
            "--days",
            str(args.tls_days),
        ],
        cwd=str(target),
        check=True,
        env=env,
    )
    return {"status": "ready", "cert": "runtime/tls/dashboard.crt", "ca_cert": "runtime/tls/dashboard-ca.crt", "key": "runtime/tls/dashboard.key"}


def read_manifest(target):
    manifest_path = target / "platform" / "manifest.json"
    with manifest_path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def write_initial_plan(target, args, dry_run=False):
    manifest = read_manifest(target if not dry_run else ROOT)
    profile = manifest.get("profiles", {}).get(args.profile, {})
    selected = set(profile.get("modules", []))
    modules = [m for m in manifest.get("modules", []) if m.get("id") in selected]
    dashboard_entrypoint = f"http://localhost:{args.dashboard_port}" if args.disable_https else f"https://localhost:{args.https_port}"
    plan = {
        "profile": args.profile,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "proxy_mode": args.proxy_mode,
        "ai_base_url": agent_base_url(args),
        "operator_proxy_url": operator_proxy_url(args, detect_host_ip()),
        "operator_dashboard_url": dashboard_entrypoint,
        "harness": selected_harness(args),
        "provider": args.provider,
        "model": args.model,
        "spawn_setup_agent": bool(args.spawn_setup_agent),
        "operator_next_step": (
            f"Open {dashboard_entrypoint}; the setup ticket is the handoff "
            "for agentic onboarding, provider integration, approval gates, and smoke tests."
        ),
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


def http_json(url, method="GET", payload=None, timeout=10, verify_tls=True, headers=None):
    data = None
    final_headers = dict(headers or {})
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        final_headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=final_headers, method=method)
    context = None
    if url.startswith("https://") and not verify_tls:
        context = ssl._create_unverified_context()
    with urllib.request.urlopen(req, timeout=timeout, context=context) as response:
        body = response.read().decode("utf-8", errors="replace")
        return json.loads(body) if body else {}


def wait_health(url, name, dry_run=False, attempts=30, verify_tls=True, headers=None):
    if dry_run:
        print("DRY RUN: health check", name, url)
        return {"status": "dry_run"}
    last_error = ""
    for _ in range(attempts):
        try:
            result = http_json(url, timeout=5, verify_tls=verify_tls, headers=headers)
            if result.get("status") in ("ok", "healthy"):
                return result
            last_error = json.dumps(result)[:300]
        except Exception as exc:
            last_error = str(exc)
        time.sleep(2)
    raise RuntimeError(f"{name} health check failed at {url}: {last_error}")


def service_headers(env_values):
    token = (env_values or {}).get("DASHBOARD_SERVICE_TOKEN") or os.getenv("DASHBOARD_SERVICE_TOKEN", "")
    if not token:
        return {}
    return {
        "X-Dashboard-Service-Token": token,
        "X-Dashboard-Service-User": "installer-bootstrap",
    }


def create_agentic_setup_ticket(args, host, env_values=None, dry_run=False):
    base = f"http://localhost:{args.dashboard_port}"
    payload = {
        "profile": args.profile,
        "existing_tools": [],
        "deploy_missing": True,
        "ai_base_url": agent_base_url(args),
        "model": args.model,
        "spawn_agent": bool(args.spawn_setup_agent),
        "sync_provider": False,
        "proxy_mode": args.proxy_mode,
        "proxy_url": operator_proxy_url(args, host),
        "harness": selected_harness(args),
        "provider": args.provider,
        "notes": (
            "Installer planted the platform seed. Agentic onboarding task: inspect installed modules; "
            "verify dashboard, proxy, harness, and model health; run a model smoke test; validate agent spawn; "
            "identify missing integrations; request credential/access approvals as needed; and update setup notes, "
            "postmortems, skills, and reusable workflows before marking onboarding complete."
        ),
    }
    if dry_run:
        print("DRY RUN: create setup ticket", json.dumps(payload, sort_keys=True))
        return {"status": "dry_run", "payload": payload}
    return http_json(
        f"{base}/api/setup/ticket",
        method="POST",
        payload=payload,
        timeout=30,
        headers=service_headers(env_values),
    )


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
    args = configure_interactive(args)
    source = Path(args.source).resolve()
    target = Path(args.target).resolve()
    host = detect_host_ip()

    if args.proxy_mode == "external" and not args.ai_base_url:
        print("External proxy mode selected without --ai-base-url. The dashboard will install, but agent spawning needs AGENT_LLM_BASE_URL configured.")

    if not args.dry_run:
        target.mkdir(parents=True, exist_ok=True)
    copy_source(source, target, args.dry_run)
    env_status = write_env(target, args, args.dry_run)
    deployment_env = read_env_file(target) if not args.dry_run else {}
    write_compose_override(target, args, args.dry_run)
    proxy_config = write_proxy_config(target, args, args.dry_run)
    write_agent_models(target, args, args.dry_run)
    tls_status = ensure_tls_assets(target, args, host, args.dry_run)
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
                    "ANTHROPIC_BASE_URL": agent_base_url(args),
                    "ANTHROPIC_AUTH_TOKEN": os.getenv("AGENT_LLM_AUTH_TOKEN", ""),
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
            "dashboard_https_port": args.https_port,
            "tls": tls_status,
            "db_port": args.db_port,
            "memory_db_port": args.memory_db_port,
            "proxy_mode": args.proxy_mode,
            "proxy_url": operator_proxy_url(args, host),
            "harness": selected_harness(args),
            "model": args.model,
        })

    setup_ticket = {"status": "skipped", "reason": "no_start"}
    dashboard_health = {"status": "skipped"}
    dashboard_https_health = {"status": "skipped"}
    proxy_health = {"status": "skipped"}
    proxy_models = {"status": "skipped"}
    if not args.no_start:
        run(["docker", "compose", "up", "-d", "--build"], target, args.dry_run)
        migrations = apply_migrations(target, args.dry_run)
        dashboard_url = f"http://localhost:{args.dashboard_port}"
        proxy_url = operator_proxy_url(args, host)
        proxy_health_url = local_proxy_url(args)
        dashboard_health = wait_health(
            f"{dashboard_url}/health",
            "dashboard",
            args.dry_run,
            headers=service_headers(deployment_env),
        )
        dashboard_https_health = wait_health(
            f"https://localhost:{args.https_port}/nginx-health",
            "dashboard-tls-proxy",
            args.dry_run or args.disable_https,
            verify_tls=False,
        )
        proxy_health = wait_health(f"{proxy_health_url}/health", "ai-proxy", args.dry_run)
        if args.dry_run:
            proxy_models = {"status": "dry_run"}
        else:
            proxy_models = http_json(f"{proxy_health_url}/v1/models", timeout=10)
        setup_ticket = create_agentic_setup_ticket(args, host, deployment_env, args.dry_run)
        if not args.dry_run:
            log_event(target, "docker_started", {
                "profile": args.profile,
                "migrations": migrations,
                "dashboard_health": dashboard_health,
                "dashboard_https_health": dashboard_https_health,
                "proxy_health": proxy_health,
                "setup_ticket_id": ((setup_ticket or {}).get("ticket") or {}).get("id"),
                "setup_agent": (setup_ticket or {}).get("agent"),
            })

    print(json.dumps({
        "status": "dry_run" if args.dry_run else "installed",
        "target": str(target),
        "profile": args.profile,
        "proxy_mode": args.proxy_mode,
        "proxy_url": operator_proxy_url(args, host),
        "proxy_health_url": local_proxy_url(args),
        "dashboard_https_url": None if args.disable_https else f"https://localhost:{args.https_port}",
        "dashboard_tls": tls_status,
        "harness": selected_harness(args),
        "provider": args.provider,
        "model": args.model,
        "dashboard_url": f"http://localhost:{args.dashboard_port}",
        "memory_db_port": args.memory_db_port,
        "dashboard_health": dashboard_health,
        "dashboard_https_health": dashboard_https_health,
        "proxy_health": proxy_health,
        "proxy_model_count": len((proxy_models or {}).get("data", [])) if isinstance(proxy_models, dict) else 0,
        "setup_ticket_id": ((setup_ticket or {}).get("ticket") or {}).get("id"),
        "setup_agent": (setup_ticket or {}).get("agent"),
        "proxy_config_models": {
            "local": len(proxy_config.get("local_models", [])),
            "providers": {
                name: len((provider or {}).get("models", []))
                for name, provider in (proxy_config.get("providers") or {}).items()
            },
        },
        "next_step": plan["operator_next_step"],
    }, indent=2))


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        print(f"Installer command failed with exit code {exc.returncode}: {exc.cmd}", file=sys.stderr)
        sys.exit(exc.returncode)
