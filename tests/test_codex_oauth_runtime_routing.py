import os
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
API_ROOT = ROOT / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

from services import agent_runner  # noqa: E402


class CodexOauthRuntimeRoutingTests(unittest.TestCase):
    def test_codex_oauth_repairs_local_alias_before_spawn(self):
        with mock.patch.dict(os.environ, {"CODEX_AUTH_MODE": "oauth"}, clear=False):
            resolved = agent_runner.resolve_agent_runtime_profile(
                task_type="ticket_resolution",
                requested_model="local/agent-default",
            )

        self.assertEqual(resolved["harness"], "codex")
        self.assertEqual(resolved["model"], "gpt-5.5")
        self.assertEqual(resolved["model_repair_reason"], "codex_oauth_replaced_proxy_or_local_model")
        self.assertEqual(resolved["requested_model_repaired_from"], "local/agent-default")

    def test_codex_oauth_repairs_provider_alias_before_spawn(self):
        with mock.patch.dict(os.environ, {"CODEX_AUTH_MODE": "oauth"}, clear=False):
            resolved = agent_runner.resolve_agent_runtime_profile(
                task_type="ticket_resolution",
                requested_model="deepseek/deepseek-v4-flash",
            )

        self.assertEqual(resolved["harness"], "codex")
        self.assertEqual(resolved["model"], "gpt-5.5")

    def test_proxy_mode_preserves_local_alias_for_codex_proxy_tests(self):
        with mock.patch.dict(os.environ, {"CODEX_AUTH_MODE": "proxy"}, clear=False):
            resolved = agent_runner.resolve_agent_runtime_profile(
                task_type="ticket_resolution",
                requested_model="local/agent-default",
            )

        self.assertEqual(resolved["harness"], "codex")
        self.assertEqual(resolved["model"], "local/agent-default")
        self.assertNotIn("model_repair_reason", resolved)

    def test_ops_chat_tool_does_not_default_ticket_workers_to_local_alias(self):
        source = (ROOT / "api" / "routes" / "ops_chat.py").read_text(encoding="utf-8")
        self.assertIn('DEFAULT_MODEL = os.environ.get("OPS_CHAT_TICKET_AGENT_MODEL")', source)
        self.assertNotIn('DEFAULT_MODEL = os.environ.get("OPS_CHAT_AGENT_MODEL") or os.environ.get("AGENT_DEFAULT_MODEL") or "local/agent-default"', source)
        self.assertNotIn('"model": args.model or DEFAULT_MODEL', source)
        self.assertIn("assign_agent_payload(prompt, args)", source)


if __name__ == "__main__":
    unittest.main()
