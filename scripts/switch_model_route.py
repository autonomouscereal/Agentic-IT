"""Switch Agentic Operations between local/on-prem and external model routes.

This edits deployment-owned config files only. Secrets remain in the vault or
runtime environment. Run from the deployment directory, for example:

    python scripts/switch_model_route.py --route local --restart
    python scripts/switch_model_route.py --route external --restart
"""
import argparse
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


LOCAL_MODEL = "qwen/qwen3.6-27b"
LOCAL_ALIAS = "local/agent-default"
EXTERNAL_PROVIDER = "nous"
EXTERNAL_MODEL = "deepseek/deepseek-v4-flash"


def read_env(path):
    values = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def write_env(path, updates):
    existing_lines = path.read_text(encoding="utf-8", errors="replace").splitlines() if path.exists() else []
    seen = set()
    output = []
    for line in existing_lines:
        if not line.strip() or line.lstrip().startswith("#") or "=" not in line:
            output.append(line)
            continue
        key, _ = line.split("=", 1)
        key = key.strip()
        if key in updates:
            output.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            output.append(line)
    for key, value in updates.items():
        if key not in seen:
            output.append(f"{key}={value}")
    path.write_text("\n".join(output).rstrip() + "\n", encoding="utf-8", newline="\n")


def load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8", newline="\n")


def update_proxy_config(root, route, local_model, external_provider, external_model):
    path = root / "runtime" / "proxy_config.json"
    config = load_json(path, {"version": 1, "providers": {}, "local_models": []})
    routing = config.setdefault("routing", {})
    routing["active"] = route
    routing["external_enabled"] = route == "external"
    profiles = routing.setdefault("profiles", {})
    profiles["local"] = {
        "provider": "lmstudio",
        "model": local_model,
        "aliases": ["default", "agent-default", LOCAL_ALIAS, external_model, "deepseek-v4-flash"],
        "fallbacks": [],
    }
    profiles["external"] = {
        "provider": external_provider,
        "model": external_model,
        "aliases": ["external/agent-default"],
        "fallbacks": ["openrouter", "lmstudio"],
    }
    config["default_provider"] = "lmstudio" if route == "local" else external_provider
    config["default_model"] = LOCAL_ALIAS if route == "local" else external_model
    providers = config.setdefault("providers", {})
    lmstudio = providers.setdefault("lmstudio", {})
    lmstudio.setdefault("token_env", "LM_STUDIO_TOKEN")
    lmstudio["models"] = list(dict.fromkeys([local_model] + list(lmstudio.get("models") or [])))
    lmstudio["fallbacks"] = []
    external = providers.setdefault(external_provider, {})
    external.setdefault("token_env", "NOUS_API_KEY" if external_provider == "nous" else f"{external_provider.upper()}_API_KEY")
    external["models"] = list(dict.fromkeys([external_model] + list(external.get("models") or [])))
    external["fallbacks"] = ["openrouter", "lmstudio"]
    local_models = config.setdefault("local_models", [])
    if not any(item.get("id") == local_model for item in local_models if isinstance(item, dict)):
        local_models.insert(0, {"id": local_model, "weight": 3})
    write_json(path, config)


def update_agent_models(root, route, local_alias, external_model):
    path = root / "agent_models.json"
    data = load_json(path, {"models": [], "default": local_alias})
    models = list(data.get("models") or [])
    for model in (local_alias, external_model, LOCAL_MODEL):
        if model not in models:
            models.append(model)
    data["models"] = models
    data["default"] = local_alias if route == "local" else external_model
    write_json(path, data)


def route_updates(route, local_model, external_provider, external_model):
    if route == "local":
        return {
            "AI_MODEL_ROUTE": "local",
            "AI_PROXY_MODEL_ROUTE": "local",
            "AI_PROXY_EXTERNAL_ENABLED": "false",
            "AI_PROXY_LOCAL_MODEL": local_model,
            "AI_PROXY_EXTERNAL_PROVIDER": external_provider,
            "AI_PROXY_EXTERNAL_MODEL": external_model,
            "AGENT_DEFAULT_MODEL": LOCAL_ALIAS,
            "AGENT_TRANSIENT_MODEL_FALLBACK_ENABLED": "false",
            "AGENT_TRANSIENT_MODEL_FALLBACK_MODEL": LOCAL_ALIAS,
            "HERMES_DEFAULT_PROVIDER": "dashboard-proxy",
            "HERMES_LOCAL_PROVIDER": "dashboard-proxy",
        }
    return {
        "AI_MODEL_ROUTE": "external",
        "AI_PROXY_MODEL_ROUTE": "external",
        "AI_PROXY_EXTERNAL_ENABLED": "true",
        "AI_PROXY_LOCAL_MODEL": local_model,
        "AI_PROXY_EXTERNAL_PROVIDER": external_provider,
        "AI_PROXY_EXTERNAL_MODEL": external_model,
        "AGENT_DEFAULT_MODEL": external_model,
        "AGENT_TRANSIENT_MODEL_FALLBACK_ENABLED": "true",
        "AGENT_TRANSIENT_MODEL_FALLBACK_MODEL": LOCAL_ALIAS,
        "HERMES_DEFAULT_PROVIDER": external_provider,
        "HERMES_LOCAL_PROVIDER": "dashboard-proxy",
    }


def main():
    parser = argparse.ArgumentParser(description="Switch model routing profile for a deployment")
    parser.add_argument("--route", choices=["local", "external"], required=True)
    parser.add_argument("--root", default=str(ROOT), help="Deployment/repo root")
    parser.add_argument("--local-model", default=LOCAL_MODEL)
    parser.add_argument("--external-provider", default=EXTERNAL_PROVIDER)
    parser.add_argument("--external-model", default=EXTERNAL_MODEL)
    parser.add_argument("--restart", action="store_true", help="Restart api and ai-proxy with docker compose")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    env_path = root / ".env"
    updates = route_updates(args.route, args.local_model, args.external_provider, args.external_model)
    write_env(env_path, updates)
    update_proxy_config(root, args.route, args.local_model, args.external_provider, args.external_model)
    update_agent_models(root, args.route, LOCAL_ALIAS, args.external_model)

    if args.restart:
        subprocess.run(["docker", "compose", "up", "-d", "--build", "ai-proxy", "api"], cwd=str(root), check=True)

    print(json.dumps({
        "status": "updated",
        "route": args.route,
        "env": str(env_path),
        "agent_default_model": updates["AGENT_DEFAULT_MODEL"],
        "proxy_config": str(root / "runtime" / "proxy_config.json"),
        "restart": bool(args.restart),
    }, indent=2))


if __name__ == "__main__":
    main()
