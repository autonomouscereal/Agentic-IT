import json
from pathlib import Path
import subprocess
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


class AgenticSelfRepairMarkerTest(unittest.TestCase):
    def test_marker_cli_outputs_contract(self):
        script = ROOT / "scripts" / "agentic_self_repair_marker.py"
        marker = "CODEX_SOURCE_SELF_REPAIR_UNIT"

        proc = subprocess.run(
            [sys.executable, str(script), "--marker", marker],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=10,
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        payload = json.loads(proc.stdout)
        self.assertEqual(payload["marker"], marker)
        self.assertEqual(payload["status"], "source_self_repair_ready")
        self.assertIs(payload["agentic_edit"], True)
        self.assertIn("timestamp", payload)


class AgentRuntimeImageTest(unittest.TestCase):
    def test_api_image_includes_git_for_diff_evidence(self):
        dockerfile = (ROOT / "api" / "Dockerfile").read_text(encoding="utf-8")
        self.assertRegex(dockerfile, r"apt-get install[\s\S]*\bgit\b")

    def test_compose_mounts_hermes_home_for_harness(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("HERMES_BIN", compose)
        self.assertIn("HERMES_HOME_DIR", compose)
        self.assertIn("HERMES_UV_PYTHON_DIR", compose)
        self.assertIn("HERMES_RUN_AS_UID", compose)
        self.assertIn("/home/cereal/.hermes", compose)

    def test_reference_proxy_supports_hermes_chat_completions(self):
        proxy = (ROOT / "deploy" / "ai-proxy" / "ai_proxy.py").read_text(encoding="utf-8")
        self.assertIn('path == "v1/chat/completions"', proxy)
        self.assertIn("deepseek/deepseek-v4-flash", proxy)
        self.assertIn("proxy_nous_chat", proxy)
        self.assertIn("OPENROUTER_API_KEY", proxy)
        self.assertIn('"fallbacks": ["openrouter", "lmstudio"]', proxy)
        self.assertIn("proxy_chat_with_fallbacks", proxy)
        self.assertIn("PROXY_CONFIG_PATH", proxy)

    def test_compose_deploys_first_class_ai_proxy(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("ai-proxy:", compose)
        self.assertIn("build: ./deploy/ai-proxy", compose)
        self.assertIn("PROXY_CONFIG_PATH", compose)
        self.assertIn("host.docker.internal:host-gateway", compose)
        self.assertIn("AGENT_LLM_BASE_URL: ${AGENT_LLM_BASE_URL:-http://ai-proxy:4001}", compose)


if __name__ == "__main__":
    unittest.main()
