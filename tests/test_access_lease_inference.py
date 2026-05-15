import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module():
    spec = importlib.util.spec_from_file_location(
        "tested_lease_inference",
        ROOT / "api" / "services" / "lease_inference.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AccessLeaseInferenceTests(unittest.TestCase):
    def test_infers_wazuh_manager_api_read_lease(self):
        module = load_module()

        lease = module.infer_lease_request(
            "wazuh.manager API",
            "read",
            "agent-197",
        )

        self.assertEqual(lease, {
            "system": "wazuh",
            "resource_type": "api",
            "resource_id": "wazuh.manager",
            "action": "read",
        })

    def test_infers_wazuh_alert_index_lease(self):
        module = load_module()

        lease = module.infer_lease_request(
            "Wazuh alert index finance-edr-restricted",
            "read",
            "agent-191",
        )

        self.assertEqual(lease["system"], "wazuh")
        self.assertEqual(lease["resource_type"], "alert_index")
        self.assertEqual(lease["resource_id"], "finance-edr-restricted")
        self.assertEqual(lease["action"], "read")

    def test_infers_gitlab_project_lease(self):
        module = load_module()

        lease = module.infer_lease_request(
            "GitLab project demo/private-infra",
            "Developer repository read access",
            "agent-190",
        )

        self.assertEqual(lease["system"], "gitlab")
        self.assertEqual(lease["resource_type"], "project")
        self.assertEqual(lease["resource_id"], "demo/private-infra")
        self.assertEqual(lease["action"], "read")


if __name__ == "__main__":
    unittest.main()
