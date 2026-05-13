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


if __name__ == "__main__":
    unittest.main()
