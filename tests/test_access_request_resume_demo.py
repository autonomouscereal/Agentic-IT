import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class AccessRequestResumeDemoTests(unittest.TestCase):
    def test_resume_prompt_requires_explicit_ticket_status_close(self):
        source = (ROOT / "scripts" / "agentic_access_request_resume_demo.py").read_text(encoding="utf-8")

        self.assertIn("status_payload.json", source)
        self.assertIn("/api/tickets/{ticket_id}/status", source)
        self.assertIn('close_provider false', source)
        self.assertIn("ACCESS RESUME COMPLETE", source)


if __name__ == "__main__":
    unittest.main()
