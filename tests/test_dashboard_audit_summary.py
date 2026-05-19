import importlib.util
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_dashboard_module():
    fastapi = types.ModuleType("fastapi")

    class APIRouter:
        def __init__(self, *args, **kwargs):
            pass

        def get(self, *args, **kwargs):
            return lambda fn: fn

    fastapi.APIRouter = APIRouter
    sys.modules["fastapi"] = fastapi

    database = types.ModuleType("database")
    database.fetchall = None
    database.fetchrow = None
    database.execute = None
    database.fetchval = None
    database.json_dumps = lambda value: value
    sys.modules["database"] = database

    spec = importlib.util.spec_from_file_location(
        "tested_dashboard",
        ROOT / "api" / "routes" / "dashboard.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DashboardAuditSummaryTests(unittest.TestCase):
    def test_change_approved_summary_names_approver(self):
        module = load_dashboard_module()

        summary = module._audit_summary({
            "actor": "demo_account_1",
            "action": "change_approved",
            "target": "change_12",
            "source": "audit",
            "details": {
                "change_id": 12,
                "approved_by": "demo_account_1",
                "action": "lab-safe mailbox quarantine",
                "target": "mailbox finance.user",
            },
        })

        self.assertIn("demo_account_1 approved change 12", summary)
        self.assertIn("lab-safe mailbox quarantine", summary)

    def test_change_rejected_summary_names_rejecter_and_reason(self):
        module = load_dashboard_module()

        summary = module._audit_summary({
            "actor": "platform-admin",
            "action": "change_rejected",
            "target": "change_13",
            "source": "audit",
            "details": {
                "change_id": 13,
                "rejected_by": "platform-admin",
                "action": "disable account",
                "target": "user demo",
                "reason": "needs manager approval",
            },
        })

        self.assertIn("platform-admin rejected change 13", summary)
        self.assertIn("needs manager approval", summary)


if __name__ == "__main__":
    unittest.main()
