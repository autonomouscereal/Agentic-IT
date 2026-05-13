import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_task_prompts():
    spec = importlib.util.spec_from_file_location(
        "tested_task_prompts",
        ROOT / "api" / "services" / "task_prompts.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TaskPromptTicketClosureTests(unittest.TestCase):
    def test_ticket_prompt_defaults_to_agent_initiated_closure(self):
        module = load_task_prompts()
        prompt = module.build_ticket_resolution_prompt({"id": 447, "title": "Close policy proof"})

        self.assertIn("Default workflow behavior is agent-initiated closure", prompt)
        self.assertIn("POST /api/tickets/{ticket_id}/status", prompt)
        self.assertIn("before the final `done`", prompt)
        self.assertIn("Opt out of closure only when", prompt)
        self.assertIn("requires human review", prompt)
        self.assertIn("close_provider: true", prompt)
        self.assertIn("Ticket to work: Close policy proof", prompt)
        self.assertNotIn("Ticket to resolve: Close policy proof", prompt)

    def test_auto_assignment_prompt_has_same_closure_contract(self):
        module = load_task_prompts()
        prompt = module.build_auto_assignment_prompt({"id": 448, "title": "Auto close proof"})

        self.assertIn("Default workflow behavior is agent-initiated closure", prompt)
        self.assertIn("POST /api/tickets/{ticket_id}/status", prompt)
        self.assertIn("leave it open only when", prompt)
        self.assertIn("Ticket id: 448", prompt)
        self.assertIn("Ticket to work: Auto close proof", prompt)


if __name__ == "__main__":
    unittest.main()
