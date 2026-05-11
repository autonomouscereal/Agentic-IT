"""Agent harness abstraction.

Claude Code is the first concrete harness, but the runner calls this module so
future harnesses can implement the same command/env contract.
"""
import os


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


_HARNESS_FACTORIES = {
    "claude-code": ClaudeCodeHarness,
}


def get_harness(name=None):
    harness_name = name or os.getenv("AGENT_HARNESS", "claude-code")
    factory = _HARNESS_FACTORIES.get(harness_name)
    if not factory:
        raise ValueError(f"Unsupported agent harness: {harness_name}")
    return factory()


def list_harnesses():
    return [{"name": name} for name in sorted(_HARNESS_FACTORIES)]
