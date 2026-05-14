import importlib.util
import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_demo():
    spec = importlib.util.spec_from_file_location(
        "tested_permission_vault_demo",
        ROOT / "scripts" / "agentic_permission_vault_access_demo.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PermissionVaultDemoTests(unittest.TestCase):
    def test_wait_access_request_fails_fast_when_agent_ends(self):
        module = load_demo()
        marker = "UNIT_PERMISSION_FAIL"

        def request(base, method, path, payload=None, user=None, expect=(200,)):
            self.assertEqual(method, "GET")
            self.assertEqual(path, "/api/tickets/522/context")
            return {
                "ticket": {"id": 522, "status": "in_progress", "agent_id": 188},
                "notes": [{"body": "permission probe started"}],
                "access_requests": [],
            }

        def latest_task(base, agent_id):
            self.assertEqual(agent_id, 188)
            return {
                "id": 185,
                "status": "failed",
                "progress_pct": 10,
                "error_message": "worker exited before access request",
            }

        module.request = request
        module.latest_task = latest_task
        module.time.sleep = lambda seconds: None

        with self.assertRaises(RuntimeError) as raised:
            module.wait_access_request("http://example.invalid", 522, marker, timeout=5)

        self.assertIn("ended before access request", str(raised.exception))

    def test_wait_completion_requires_resumed_task_terminal_checkpoint(self):
        module = load_demo()
        marker = "UNIT_PERMISSION"
        calls = {"latest_task": 0}

        def request(base, method, path, payload=None, user=None, expect=(200,)):
            self.assertEqual(method, "GET")
            self.assertEqual(path, "/api/tickets/522/context")
            return {
                "ticket": {"id": 522, "status": "resolved", "agent_id": 189},
                "notes": [{"body": f"ACCESS LEASE GRANTED {marker}"}],
                "access_requests": [{"status": "granted"}],
            }

        def latest_task(base, agent_id):
            calls["latest_task"] += 1
            if calls["latest_task"] == 1:
                return {
                    "id": 186,
                    "status": "running",
                    "progress_pct": 40,
                    "checkpoints": "[]",
                }
            return {
                "id": 186,
                "status": "completed",
                "progress_pct": 100,
                "checkpoints": json.dumps([
                    {
                        "step": f"vault-access-complete-{marker}",
                        "status": "done",
                        "output": f"ACCESS LEASE GRANTED {marker}",
                    }
                ]),
            }

        module.request = request
        module.latest_task = latest_task
        module.time.sleep = lambda seconds: None

        context = module.wait_completion("http://example.invalid", 522, marker, timeout=5)

        self.assertEqual(context["ticket"]["status"], "resolved")
        self.assertEqual(calls["latest_task"], 2)


if __name__ == "__main__":
    unittest.main()
