import os
import unittest
from unittest import mock

from api.services.agent_harness import ClaudeCodeHarness, HermesHarness, list_harnesses


class AgentHarnessTests(unittest.TestCase):
    def test_harness_registry_includes_hermes_and_claude_code(self):
        names = {item["name"] for item in list_harnesses()}
        self.assertIn("claude-code", names)
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

    def test_hermes_external_model_uses_nous_provider_and_oneshot(self):
        with mock.patch.dict(os.environ, {"HERMES_BIN": "/opt/hermes/bin/hermes"}, clear=False):
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


if __name__ == "__main__":
    unittest.main()
