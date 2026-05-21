import json
from pathlib import Path
import subprocess
import sys
import tempfile
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
        self.assertIn("route_for_chat_model", proxy)
        self.assertIn("AI_PROXY_MODEL_ROUTE", proxy)
        self.assertIn('"active": active_route', proxy)
        self.assertIn("EXTERNAL_ENABLED", proxy)
        self.assertIn("OPENROUTER_API_KEY", proxy)
        self.assertIn('NOUS_FALLBACK_PROVIDERS", "openrouter,lmstudio"', proxy)
        self.assertIn("proxy_chat_with_fallbacks", proxy)
        self.assertIn("PROXY_CONFIG_PATH", proxy)

    def test_proxy_local_profile_routes_aliases_to_local_model(self):
        script = """
import importlib.util
import os
from pathlib import Path
os.environ["AI_PROXY_MODEL_ROUTE"] = "local"
os.environ["AI_PROXY_EXTERNAL_ENABLED"] = "false"
os.environ["AI_PROXY_LOCAL_MODEL"] = "qwen/qwen3.6-27b"
spec = importlib.util.spec_from_file_location("ai_proxy", Path("deploy/ai-proxy/ai_proxy.py"))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
print(mod.route_for_chat_model("local/agent-default"))
print(mod.route_for_chat_model("deepseek/deepseek-v4-flash"))
"""
        proc = subprocess.run(
            [sys.executable, "-c", script],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=20,
        )

        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("('lmstudio', 'qwen/qwen3.6-27b')", proc.stdout)

    def test_compose_deploys_first_class_ai_proxy(self):
        compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("ai-proxy:", compose)
        self.assertIn("build: ./deploy/ai-proxy", compose)
        self.assertIn("PROXY_CONFIG_PATH", compose)
        self.assertIn("host.docker.internal:host-gateway", compose)
        self.assertIn("AGENT_LLM_BASE_URL: ${AGENT_LLM_BASE_URL:-http://ai-proxy:4001}", compose)
        self.assertIn("AI_MODEL_ROUTE: ${AI_MODEL_ROUTE:-local}", compose)
        self.assertIn("AI_PROXY_EXTERNAL_ENABLED: ${AI_PROXY_EXTERNAL_ENABLED:-false}", compose)

    def test_model_route_switcher_is_deployment_safe(self):
        script = (ROOT / "scripts" / "switch_model_route.py").read_text(encoding="utf-8")
        env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
        harness = (ROOT / "api" / "services" / "agent_harness.py").read_text(encoding="utf-8")
        self.assertIn("AI_MODEL_ROUTE", script)
        self.assertIn("AI_PROXY_MODEL_ROUTE", script)
        self.assertIn("local/agent-default", script)
        self.assertIn("dashboard-proxy", script)
        self.assertIn("AI_MODEL_ROUTE=local", env_example)
        self.assertIn("AGENT_DEFAULT_MODEL=gpt-5.5", env_example)
        model_config = json.loads((ROOT / "agent_models.json").read_text(encoding="utf-8"))
        local_profile = next(p for p in model_config["profiles"] if p["id"] == "local-only")
        self.assertEqual(local_profile["model"], "local/agent-default")
        self.assertEqual(local_profile["timeout_minutes"], 60)
        self.assertIn('env.setdefault("HERMES_DEFAULT_PROVIDER", "dashboard-proxy")', harness)

    def test_model_route_switcher_updates_temp_deployment(self):
        switcher = ROOT / "scripts" / "switch_model_route.py"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".env").write_text(
                "AI_MODEL_ROUTE=external\nAGENT_DEFAULT_MODEL=deepseek/deepseek-v4-flash\n",
                encoding="utf-8",
            )
            (root / "runtime").mkdir()
            (root / "runtime" / "proxy_config.json").write_text(
                json.dumps({"version": 1, "providers": {}, "local_models": []}),
                encoding="utf-8",
            )
            (root / "agent_models.json").write_text(
                json.dumps({"models": ["deepseek/deepseek-v4-flash"], "default": "deepseek/deepseek-v4-flash"}),
                encoding="utf-8",
            )

            proc = subprocess.run(
                [sys.executable, str(switcher), "--root", str(root), "--route", "local"],
                cwd=str(ROOT),
                text=True,
                capture_output=True,
                timeout=20,
            )

            self.assertEqual(proc.returncode, 0, proc.stderr)
            env = (root / ".env").read_text(encoding="utf-8")
            proxy = json.loads((root / "runtime" / "proxy_config.json").read_text(encoding="utf-8"))
            models = json.loads((root / "agent_models.json").read_text(encoding="utf-8"))
            self.assertIn("AI_MODEL_ROUTE=local", env)
            self.assertIn("AI_PROXY_EXTERNAL_ENABLED=false", env)
            self.assertIn("HERMES_DEFAULT_PROVIDER=dashboard-proxy", env)
            self.assertEqual(proxy["routing"]["active"], "local")
            self.assertFalse(proxy["routing"]["external_enabled"])
            self.assertEqual(models["default"], "local/agent-default")


if __name__ == "__main__":
    unittest.main()
