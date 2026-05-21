import os
import unittest
from unittest import mock

from api.services.agent_harness import ClaudeCodeHarness, CodexHarness, HermesHarness, list_harnesses


class AgentHarnessTests(unittest.TestCase):
    def test_harness_registry_includes_supported_harnesses(self):
        names = {item["name"] for item in list_harnesses()}
        self.assertIn("claude-code", names)
        self.assertIn("codex", names)
        self.assertIn("hermes", names)

    def test_claude_command_keeps_allowed_tools_before_prompt(self):
        cmd = ClaudeCodeHarness().build_command(
            "resolve ticket",
            "/work/.claude/settings.json",
            "qwen/qwen3.6-27b",
            "acceptEdits",
            "Read,Write,Bash(curl *)",
        )

        self.assertEqual(cmd[0], "claude")
        self.assertLess(cmd.index("--allowedTools"), cmd.index("-p"))
        self.assertEqual(cmd[-1], "resolve ticket")

    def test_claude_env_sets_api_key_for_proxy_auth(self):
        env = ClaudeCodeHarness().build_env(
            {},
            llm_base_url="http://proxy.local:4001",
            llm_auth_token="redacted-token",
            dashboard_api_base="http://localhost:8000",
        )

        self.assertEqual(env["ANTHROPIC_BASE_URL"], "http://proxy.local:4001")
        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "redacted-token")
        self.assertEqual(env["ANTHROPIC_API_KEY"], "redacted-token")
        self.assertEqual(env["DASHBOARD_API_BASE"], "http://localhost:8000")

    def test_hermes_external_route_uses_nous_provider_and_oneshot(self):
        with mock.patch.dict(os.environ, {
            "AI_MODEL_ROUTE": "external",
            "HERMES_BIN": "/opt/hermes/bin/hermes",
        }, clear=False):
            cmd = HermesHarness().build_command(
                "resolve ticket",
                "/work/.claude/settings.json",
                "deepseek/deepseek-v4-flash",
                "acceptEdits",
                None,
            )

        self.assertEqual(cmd[:6], ["setpriv", "--reuid", "1000", "--regid", "1000", "--clear-groups"])
        self.assertIn("/opt/hermes/bin/hermes", cmd)
        self.assertIn("--provider", cmd)
        self.assertEqual(cmd[cmd.index("--provider") + 1], "nous")
        self.assertIn("--accept-hooks", cmd)
        self.assertIn("chat", cmd)
        self.assertIn("-Q", cmd)
        self.assertIn("--source", cmd)
        self.assertIn("soc-dashboard", cmd)
        self.assertIn("--max-turns", cmd)
        self.assertIn("--query", cmd)
        self.assertNotIn("-z", cmd)
        self.assertEqual(cmd[-1], "resolve ticket")

    def test_hermes_default_route_uses_dashboard_proxy_for_lab_alias(self):
        with mock.patch.dict(os.environ, {
            "AI_MODEL_ROUTE": "local",
            "HERMES_BIN": "/opt/hermes/bin/hermes",
        }, clear=False):
            cmd = HermesHarness().build_command(
                "resolve ticket",
                "/work/.claude/settings.json",
                "deepseek/deepseek-v4-flash",
                "acceptEdits",
                None,
            )

        self.assertEqual(cmd[cmd.index("--provider") + 1], "dashboard-proxy")

    def test_hermes_local_model_uses_dashboard_proxy_provider(self):
        with mock.patch.dict(os.environ, {
            "HERMES_LOCAL_PROVIDER": "dashboard-proxy",
            "HERMES_BIN": "/opt/hermes/bin/hermes",
        }, clear=False):
            cmd = HermesHarness().build_command(
                "resolve ticket",
                "/work/.claude/settings.json",
                "qwen/qwen3.6-27b",
                "acceptEdits",
                None,
            )

        self.assertEqual(cmd[cmd.index("--provider") + 1], "dashboard-proxy")

    def test_hermes_env_defaults_disable_sudo_and_configure_proxy(self):
        env = HermesHarness().build_env(
            {},
            llm_base_url="http://proxy.local:4001",
            llm_auth_token="lmstudio",
            dashboard_api_base="http://localhost:8000",
        )

        self.assertEqual(env["SUDO_PASSWORD"], "")
        self.assertEqual(env["HERMES_ACCEPT_HOOKS"], "1")
        self.assertEqual(env["HERMES_TOOLSETS"], "terminal,file")
        self.assertEqual(env["HERMES_PROXY_BASE_URL"], "http://proxy.local:4001")
        self.assertEqual(env["OPENAI_BASE_URL"], "http://proxy.local:4001/v1")
        self.assertEqual(env["OPENAI_API_KEY"], "lmstudio")
        self.assertEqual(env["DASHBOARD_API_BASE"], "http://localhost:8000")
        self.assertEqual(env["HOME"], "/home/cereal")
        self.assertEqual(env["USER"], "cereal")
        self.assertEqual(env["LOGNAME"], "cereal")
        self.assertEqual(env["XDG_CACHE_HOME"], "/home/cereal/.cache")

    def test_codex_env_configures_proxy_without_logging_secret(self):
        with mock.patch.dict(os.environ, {"CODEX_AUTH_MODE": "proxy"}, clear=False):
            env = CodexHarness().build_env(
                {},
                llm_base_url="http://proxy.local:4001",
                llm_auth_token="redacted-token",
                dashboard_api_base="http://localhost:8000",
            )

        self.assertEqual(env["CODEX_HOME"], "/root/.codex")
        self.assertEqual(env["OPENAI_BASE_URL"], "http://proxy.local:4001/v1")
        self.assertEqual(env["CODEX_PROXY_BASE_URL"], "http://proxy.local:4001")
        self.assertEqual(env["OPENAI_API_KEY"], "redacted-token")
        self.assertEqual(env["CODEX_API_KEY"], "redacted-token")
        self.assertEqual(env["DASHBOARD_API_BASE"], "http://localhost:8000")

    def test_codex_oauth_env_does_not_force_proxy_or_api_key(self):
        with mock.patch.dict(os.environ, {"CODEX_AUTH_MODE": "oauth"}, clear=False):
            env = CodexHarness().build_env(
                {},
                llm_base_url="http://proxy.local:4001",
                llm_auth_token="redacted-token",
                dashboard_api_base="http://localhost:8000",
            )

        self.assertEqual(env["CODEX_HOME"], "/root/.codex")
        self.assertEqual(env["DASHBOARD_API_BASE"], "http://localhost:8000")
        self.assertNotIn("OPENAI_BASE_URL", env)
        self.assertNotIn("CODEX_PROXY_BASE_URL", env)
        self.assertNotIn("OPENAI_API_KEY", env)
        self.assertNotIn("CODEX_API_KEY", env)

    def test_codex_command_uses_exec_json_and_proxy_chat_provider(self):
        with mock.patch.dict(os.environ, {
            "CODEX_BIN": "/usr/local/bin/codex",
            "CODEX_AUTH_MODE": "proxy",
            "AGENT_LLM_BASE_URL": "http://ai-proxy:4001",
            "CODEX_SANDBOX": "danger-full-access",
            "CODEX_APPROVAL_POLICY": "never",
        }, clear=False):
            cmd = CodexHarness().build_command(
                "resolve ticket",
                "/work/.claude/settings.json",
                "local/agent-default",
                "acceptEdits",
                None,
            )

        self.assertEqual(cmd[:3], ["/usr/local/bin/codex", "exec", "--json"])
        self.assertIn("--skip-git-repo-check", cmd)
        self.assertIn("--sandbox", cmd)
        self.assertEqual(cmd[cmd.index("--sandbox") + 1], "danger-full-access")
        self.assertIn('approval_policy="never"', cmd)
        self.assertIn("--model", cmd)
        self.assertEqual(cmd[cmd.index("--model") + 1], "local/agent-default")
        self.assertIn('model_provider="agentic_proxy"', cmd)
        self.assertIn('model_providers.agentic_proxy.base_url="http://ai-proxy:4001/v1"', cmd)
        self.assertIn('model_providers.agentic_proxy.wire_api="responses"', cmd)
        self.assertEqual(cmd[-1], "resolve ticket")

    def test_codex_oauth_command_uses_subscription_login_without_proxy_provider(self):
        with mock.patch.dict(os.environ, {
            "CODEX_BIN": "/usr/local/bin/codex",
            "CODEX_AUTH_MODE": "oauth",
            "AGENT_LLM_BASE_URL": "http://ai-proxy:4001",
            "CODEX_SANDBOX": "danger-full-access",
            "CODEX_APPROVAL_POLICY": "never",
        }, clear=False):
            cmd = CodexHarness().build_command(
                "resolve ticket",
                "/work/.claude/settings.json",
                "gpt-5.5-high",
                "acceptEdits",
                None,
            )

        self.assertEqual(cmd[:3], ["/usr/local/bin/codex", "exec", "--json"])
        self.assertIn("--model", cmd)
        self.assertEqual(cmd[cmd.index("--model") + 1], "gpt-5.5-high")
        self.assertIn('approval_policy="never"', cmd)
        self.assertNotIn('model_provider="agentic_proxy"', cmd)
        self.assertFalse(any("model_providers.agentic_proxy" in part for part in cmd))
        self.assertEqual(cmd[-1], "resolve ticket")


if __name__ == "__main__":
    unittest.main()
