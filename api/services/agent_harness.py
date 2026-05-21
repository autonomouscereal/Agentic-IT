"""Agent harness abstraction.

Claude Code was the first concrete harness. The runner calls this module so
Hermes and future harnesses can share the same command/env contract.
"""
import os
import shutil


class ClaudeCodeHarness:
    name = "claude-code"

    def build_env(self, base_env, llm_base_url=None, llm_auth_token=None, dashboard_api_base=None):
        env = dict(base_env)
        env["PYTHONIOENCODING"] = "utf-8"
        if dashboard_api_base:
            env["DASHBOARD_API_BASE"] = dashboard_api_base
        if llm_base_url:
            env["ANTHROPIC_BASE_URL"] = llm_base_url
        if llm_auth_token:
            env["ANTHROPIC_AUTH_TOKEN"] = llm_auth_token
            env.setdefault("ANTHROPIC_API_KEY", llm_auth_token)
        return env

    def build_command(self, prompt, settings_path, model, permission_mode, allowed_tools=None):
        cmd = ["claude"]
        if allowed_tools:
            cmd.extend(["--allowedTools", allowed_tools])
        cmd.extend([
            "-p",
            "--settings",
            settings_path,
            "--model",
            model,
            "--permission-mode",
            permission_mode,
            "--no-session-persistence",
            "--output-format",
            "stream-json",
            "--verbose",
        ])
        cmd.append(prompt)
        return cmd


class HermesHarness:
    name = "hermes"

    def build_env(self, base_env, llm_base_url=None, llm_auth_token=None, dashboard_api_base=None):
        env = dict(base_env)
        env["PYTHONIOENCODING"] = "utf-8"
        env["HERMES_ACCEPT_HOOKS"] = "1"
        env.setdefault("HERMES_AGENT_SOURCE", "soc-dashboard")
        env.setdefault("HERMES_TOOLSETS", "terminal,file")
        env.setdefault("HERMES_DEFAULT_PROVIDER", "dashboard-proxy")
        env.setdefault("HERMES_LOCAL_PROVIDER", "dashboard-proxy")
        run_home = env.get("HERMES_RUN_HOME", "/home/cereal")
        run_user = env.get("HERMES_RUN_USER", "cereal")
        env["HOME"] = run_home
        env["USER"] = run_user
        env["LOGNAME"] = run_user
        env.setdefault("XDG_CACHE_HOME", f"{run_home}/.cache")
        # Least privilege default: the dashboard approval/vault layer is the
        # privilege boundary. Do not pass a stored sudo password into Hermes
        # unless the deployment explicitly overrides this value.
        env.setdefault("SUDO_PASSWORD", "")
        if dashboard_api_base:
            env["DASHBOARD_API_BASE"] = dashboard_api_base
        if llm_base_url:
            env["HERMES_PROXY_BASE_URL"] = llm_base_url.rstrip("/")
            env.setdefault("OPENAI_BASE_URL", f"{llm_base_url.rstrip('/')}/v1")
        if llm_auth_token:
            env.setdefault("OPENAI_API_KEY", llm_auth_token)
        return env

    def _provider_for_model(self, model):
        override = os.getenv("HERMES_PROVIDER", "").strip()
        if override:
            return override
        active_route = os.getenv("AI_MODEL_ROUTE", os.getenv("AI_PROXY_MODEL_ROUTE", "local")).strip().lower()
        default_provider = "nous" if active_route.startswith("external") else "dashboard-proxy"
        model_name = (model or "").lower()
        if model_name.startswith(("qwen/", "lmstudio/", "local/")):
            return os.getenv("HERMES_LOCAL_PROVIDER", "dashboard-proxy")
        return os.getenv("HERMES_DEFAULT_PROVIDER", default_provider)

    def build_command(self, prompt, settings_path, model, permission_mode, allowed_tools=None):
        hermes_bin = os.getenv("HERMES_BIN") or shutil.which("hermes") or "hermes"
        toolsets = os.getenv("HERMES_TOOLSETS", "terminal,file")
        provider = self._provider_for_model(model)
        max_turns = os.getenv("HERMES_MAX_TURNS", "90").strip() or "90"
        source = os.getenv("HERMES_AGENT_SOURCE", "soc-dashboard").strip() or "soc-dashboard"
        cmd = []
        run_uid = os.getenv("HERMES_RUN_AS_UID", "1000").strip()
        run_gid = os.getenv("HERMES_RUN_AS_GID", run_uid).strip()
        if run_uid:
            cmd.extend(["setpriv", "--reuid", run_uid, "--regid", run_gid, "--clear-groups"])
        cmd.extend([
            hermes_bin,
            "chat",
            "-Q",
            "--provider",
            provider,
            "--model",
            model,
            "--toolsets",
            toolsets,
            "--accept-hooks",
            "--max-turns",
            max_turns,
            "--source",
            source,
            "--query",
            prompt,
        ])
        if os.getenv("HERMES_YOLO", "").strip().lower() in ("1", "true", "yes", "on"):
            cmd.insert(-2, "--yolo")
        return cmd


class CodexHarness:
    name = "codex"

    def _auth_mode(self):
        return (os.getenv("CODEX_AUTH_MODE") or "proxy").strip().lower()

    def build_env(self, base_env, llm_base_url=None, llm_auth_token=None, dashboard_api_base=None):
        env = dict(base_env)
        env["PYTHONIOENCODING"] = "utf-8"
        env.setdefault("CODEX_HOME", os.getenv("CODEX_HOME", "/root/.codex"))
        auth_mode = self._auth_mode()
        if dashboard_api_base:
            env["DASHBOARD_API_BASE"] = dashboard_api_base
        if auth_mode == "proxy" and llm_base_url:
            base = llm_base_url.rstrip("/")
            env.setdefault("OPENAI_BASE_URL", f"{base}/v1")
            env.setdefault("CODEX_PROXY_BASE_URL", base)
        if auth_mode in ("proxy", "api") and llm_auth_token:
            # Codex reads the provider key from OPENAI_API_KEY by default.
            # CODEX_API_KEY is kept for deployments that prefer a separate
            # secret name, but the config below points at OPENAI_API_KEY.
            env.setdefault("OPENAI_API_KEY", llm_auth_token)
            env.setdefault("CODEX_API_KEY", llm_auth_token)
        return env

    def build_command(self, prompt, settings_path, model, permission_mode, allowed_tools=None):
        codex_bin = os.getenv("CODEX_BIN") or shutil.which("codex") or "codex"
        sandbox = os.getenv("CODEX_SANDBOX", "danger-full-access").strip() or "danger-full-access"
        approval = os.getenv("CODEX_APPROVAL_POLICY", "never").strip() or "never"
        profile = os.getenv("CODEX_PROFILE", "").strip()
        auth_mode = self._auth_mode()
        provider = ""
        proxy_v1 = ""
        if auth_mode == "proxy":
            provider = os.getenv("CODEX_MODEL_PROVIDER", "agentic_proxy").strip() or "agentic_proxy"
            proxy_base = (
                os.getenv("CODEX_PROXY_BASE_URL")
                or os.getenv("AGENT_LLM_BASE_URL")
                or ""
            ).rstrip("/")
            proxy_v1 = f"{proxy_base}/v1" if proxy_base else ""
        effort = os.getenv("CODEX_REASONING_EFFORT", "").strip()

        cmd = [
            codex_bin,
            "exec",
            "--json",
            "--skip-git-repo-check",
            "--sandbox",
            sandbox,
            "--model",
            model,
        ]
        if profile:
            cmd.extend(["--profile", profile])
        if provider:
            cmd.extend(["--config", f'model_provider="{provider}"'])
        if approval:
            cmd.extend(["--config", f'approval_policy="{approval}"'])
        if proxy_v1:
            cmd.extend([
                "--config", f'model_providers.{provider}.name="Agentic Operations Proxy"',
                "--config", f'model_providers.{provider}.base_url="{proxy_v1}"',
                "--config", f'model_providers.{provider}.env_key="OPENAI_API_KEY"',
                "--config", f'model_providers.{provider}.wire_api="responses"',
            ])
        if effort:
            cmd.extend(["--config", f'reasoning_effort="{effort}"'])
        cmd.append(prompt)
        return cmd


_HARNESS_FACTORIES = {
    "claude-code": ClaudeCodeHarness,
    "codex": CodexHarness,
    "hermes": HermesHarness,
}


def get_harness(name=None):
    harness_name = name or os.getenv("AGENT_HARNESS", "claude-code")
    factory = _HARNESS_FACTORIES.get(harness_name)
    if not factory:
        raise ValueError(f"Unsupported agent harness: {harness_name}")
    return factory()


def list_harnesses():
    return [{"name": name} for name in sorted(_HARNESS_FACTORIES)]
