import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_demo():
    spec = importlib.util.spec_from_file_location(
        "tested_complex_phish_edr_demo",
        ROOT / "scripts" / "agentic_complex_phish_edr_demo.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ComplexPhishEdrDemoTests(unittest.TestCase):
    def test_prompt_combines_user_response_steering_access_gates_and_learning(self):
        module = load_demo()
        prompt = module.build_prompt(531, "COMPLEX_MARKER")

        self.assertIn("/api/tickets/531/request-info", prompt)
        self.assertIn("USER_COMPLEX_RESPONSE COMPLEX_MARKER", prompt)
        self.assertIn("DASHBOARD_COMPLEX_STEER COMPLEX_MARKER", prompt)
        self.assertIn("ITOP_COMPLEX_STEER COMPLEX_MARKER", prompt)
        self.assertIn("/api/agents/<agent_id>/vault/lease", prompt)
        self.assertIn("missing_agent_vault_lease", prompt)
        self.assertIn("/api/tickets/531/access-request", prompt)
        self.assertIn("sync_provider true", prompt)
        self.assertIn("waiting_for_access", prompt)
        self.assertIn("/api/changes/request", prompt)
        self.assertIn("pending_approval", prompt)
        self.assertIn("/api/postmortems", prompt)
        self.assertIn("/promote", prompt)
        self.assertIn("/api/tickets/531/status", prompt)
        self.assertIn("COMPLEX_INCIDENT_COMPLETE COMPLEX_MARKER", prompt)

    def test_access_gate_wait_requires_durable_awaiting_access_before_approval(self):
        source = (ROOT / "scripts" / "agentic_complex_phish_edr_demo.py").read_text(encoding="utf-8")

        self.assertIn("waiting_for_access_checkpoint", source)
        self.assertIn('task_status == "awaiting_access"', source)
        self.assertIn('ticket.get("status") == "awaiting_access"', source)

    def test_containment_gate_wait_requires_pending_checkpoint_before_approval(self):
        source = (ROOT / "scripts" / "agentic_complex_phish_edr_demo.py").read_text(encoding="utf-8")

        self.assertIn("waiting_for_change_checkpoint", source)
        self.assertIn('task_status == "pending_approval"', source)
        self.assertIn('ticket.get("status") == "pending_approval"', source)


if __name__ == "__main__":
    unittest.main()
