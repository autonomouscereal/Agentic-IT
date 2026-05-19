import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SetupOnboardingPromptTests(unittest.TestCase):
    def test_spawned_setup_agent_is_bounded_bootstrap_not_full_deployment(self):
        source = (ROOT / "api" / "routes" / "setup.py").read_text(encoding="utf-8")

        self.assertIn("bounded first-pass onboarding verification", source)
        self.assertIn("Do not deploy modules", source)
        self.assertIn("GET /api/agents/runner-health", source)
        self.assertIn("GET /api/setup/manifest", source)
        self.assertIn("GET /api/setup/profiles", source)
        self.assertIn("SETUP_ONBOARDING_BOOTSTRAP_COMPLETE", source)
        self.assertNotIn("/api/setup/status", source)


if __name__ == "__main__":
    unittest.main()
