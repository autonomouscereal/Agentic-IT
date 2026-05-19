import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_platform_manifest():
    path = ROOT / "api" / "services" / "platform_manifest.py"
    spec = importlib.util.spec_from_file_location("platform_manifest_for_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SetupModuleScopeTests(unittest.TestCase):
    def test_module_actions_disable_email_scope_and_block_dependents(self):
        manifest = load_platform_manifest()

        plan = manifest.build_setup_plan(
            profile="soc",
            module_actions={
                "mailcow": "disabled",
                "roundcube-webmail": "disabled",
                "report-phish": "disabled",
                "itop": "integrate",
            },
            deploy_missing=True,
        )

        ids = {step["module_id"]: step for step in plan["steps"]}
        self.assertNotIn("mailcow", ids)
        self.assertNotIn("roundcube-webmail", ids)
        self.assertNotIn("report-phish", ids)
        self.assertEqual(ids["itop"]["status"], "integrate_existing")
        self.assertEqual(ids["soc-bridge"]["status"], "blocked_disabled_dependency")
        self.assertIn("mailcow", ids["soc-bridge"]["disabled_dependencies"])
        self.assertIn("mailcow", plan["summary"]["disabled_modules"])
        self.assertGreaterEqual(plan["summary"]["disabled"], 3)

    def test_module_ticket_description_is_scoped_to_one_module(self):
        manifest = load_platform_manifest()
        plan = manifest.build_setup_plan(
            profile="minimal",
            module_actions={"ai-proxy": "deploy"},
            deploy_missing=True,
        )
        step = next(row for row in plan["steps"] if row["module_id"] == "ai-proxy")
        description = manifest.module_ticket_description(
            42,
            step,
            runtime={"proxy_mode": "deploy", "proxy_url": "http://localhost:4401", "harness": "hermes"},
            notes="No public model proxy exposure.",
        )

        self.assertIn("Parent setup ticket: 42", description)
        self.assertIn("Work only this module or integration.", description)
        self.assertIn("AI Model Proxy", description)
        self.assertIn("No public model proxy exposure.", description)

    def test_keep_action_does_not_create_redeploy_step(self):
        manifest = load_platform_manifest()

        plan = manifest.build_setup_plan(
            profile="minimal",
            module_actions={"soc-dashboard": "keep", "ai-proxy": "keep"},
            deploy_missing=True,
        )
        ids = {step["module_id"]: step for step in plan["steps"]}

        self.assertEqual(ids["soc-dashboard"]["status"], "already_active")
        self.assertEqual(ids["ai-proxy"]["status"], "already_active")
        self.assertEqual(plan["summary"]["already_active"], 2)

    def test_single_module_undeploy_ticket_description_includes_teardown_guardrails(self):
        manifest = load_platform_manifest()
        step = manifest.module_step(
            "mailcow",
            action="undeploy",
            deployment_status={"deployment_status": "ready"},
        )
        description = manifest.module_ticket_description(
            None,
            step,
            notes="Migrate to existing Exchange tenant before teardown.",
        )

        self.assertEqual(step["status"], "undeploy")
        self.assertIn("single-module setup ticket", description)
        self.assertIn("Current deployment status: ready", description)
        self.assertIn("Before teardown, capture current config/state", description)
        self.assertIn("Migrate to existing Exchange tenant before teardown.", description)


if __name__ == "__main__":
    unittest.main()
