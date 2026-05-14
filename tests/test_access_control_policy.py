import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_access_control():
    database = types.ModuleType("database")
    database.fetchall = None
    database.fetchrow = None
    database.execute = None
    database.json_dumps = lambda value: __import__("json").dumps(value)
    sys.modules["database"] = database

    services = types.ModuleType("services")
    sys.modules["services"] = services

    event_logger = types.ModuleType("services.event_logger")

    async def log_event(*args, **kwargs):
        return None

    event_logger.log_event = log_event
    sys.modules["services.event_logger"] = event_logger

    spec = importlib.util.spec_from_file_location(
        "tested_access_control",
        ROOT / "api" / "services" / "access_control.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, database


class AccessControlPolicyTests(unittest.TestCase):
    def test_capability_wildcards_are_bounded(self):
        module, _ = load_access_control()

        self.assertTrue(module.capability_matches(["tickets:*"], "tickets:read"))
        self.assertTrue(module.capability_matches(["*"], "access:admin"))
        self.assertFalse(module.capability_matches(["tickets:read"], "tickets:note"))

    def test_route_requirements_make_agent_spawn_explicit(self):
        module, _ = load_access_control()

        self.assertEqual(
            module.required_permission("POST", "/api/tickets/447/assign-agent"),
            "agents:spawn",
        )
        self.assertEqual(
            module.required_permission("POST", "/api/tickets/447/access-request"),
            "access:request",
        )
        self.assertEqual(
            module.required_permission("GET", "/api/dashboard/audit?actor=agent"),
            "audit:read",
        )

    def test_agent_requested_permissions_cannot_exceed_spawner(self):
        module, _ = load_access_control()

        denied = module.requested_permissions_within_subject(
            ["tickets:read", "tickets:note", "changes:request"],
            ["tickets:read", "changes:approve"],
        )

        self.assertEqual(denied, ["changes:approve"])

    def test_record_agent_permission_context_refuses_excess_permissions(self):
        module, database = load_access_control()
        executes = []
        events = []

        async def execute(*args):
            executes.append(args)

        async def log_event(*args):
            events.append(args)

        database.execute = execute
        module.execute = execute
        module.log_event = log_event

        result = asyncio.run(module.record_agent_permission_context(
            163,
            447,
            {
                "identity": {"username": "dev-y"},
                "roles": ["analyst"],
                "capabilities": ["tickets:read"],
                "scopes": [{"scope_type": "group", "scope_value": "Dev Team Y"}],
                "max_classification": "confidential",
            },
            ["tickets:read", "tools:operate"],
        ))

        self.assertEqual(result["status"], "denied")
        self.assertEqual(result["denied_permissions"], ["tools:operate"])
        self.assertEqual(executes, [])
        self.assertEqual(events[0][3], "agent_permission_snapshot_denied")


if __name__ == "__main__":
    unittest.main()
