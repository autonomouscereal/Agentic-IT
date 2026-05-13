import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ItopCloseSmokePromptTests(unittest.TestCase):
    def test_real_agent_close_smoke_requires_explicit_status_endpoint(self):
        source = (ROOT / "scripts" / "smoke_itop_agent_close_e2e.py").read_text(encoding="utf-8")

        self.assertIn("/api/tickets/{ticket_id}/status", source)
        self.assertIn('"close_provider":true', source)
        self.assertIn("status_payload.json", source)
        self.assertIn("-d @status_payload.json", source)


if __name__ == "__main__":
    unittest.main()
