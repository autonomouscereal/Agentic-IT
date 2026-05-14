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

    def test_record_agent_permission_context_trims_excess_permissions_without_blocking_spawn(self):
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

        self.assertEqual(result["status"], "recorded_with_denials")
        self.assertEqual(result["allowed_permissions"], ["tickets:read"])
        self.assertEqual(result["denied_permissions"], ["tools:operate"])
        self.assertTrue(executes)
        self.assertEqual(events[0][3], "agent_permission_snapshot_denied")

    def test_ticket_scope_blocks_cross_team_access_when_enforced(self):
        module, _ = load_access_control()
        original_auth_mode = module.auth_mode
        original_enforcement_mode = module.enforcement_mode
        module.auth_mode = lambda: "header"
        module.enforcement_mode = lambda: "enforce"
        try:
            subject = {
                "roles": ["analyst"],
                "capabilities": ["tickets:read", "tickets:note"],
                "scopes": [{"scope_type": "group", "scope_value": "Dev Team Y"}],
                "max_classification": "confidential",
            }
            allowed = module.ticket_access_decision(
                {"id": 1, "owning_group": "Dev Team Y", "security_classification": "confidential"},
                subject,
                "tickets:read",
            )
            denied_group = module.ticket_access_decision(
                {"id": 2, "owning_group": "Dev Team Z", "security_classification": "confidential"},
                subject,
                "tickets:read",
            )
            denied_classification = module.ticket_access_decision(
                {"id": 3, "owning_group": "Dev Team Y", "security_classification": "restricted"},
                subject,
                "tickets:read",
            )

            self.assertTrue(allowed["allow"])
            self.assertFalse(denied_group["allow"])
            self.assertEqual(denied_group["reason"], "ticket_outside_subject_scope")
            self.assertFalse(denied_classification["allow"])
            self.assertEqual(denied_classification["reason"], "classification_exceeds_subject")
        finally:
            module.auth_mode = original_auth_mode
            module.enforcement_mode = original_enforcement_mode

    def test_ticket_list_filter_uses_group_scope_and_classification_cap(self):
        module, _ = load_access_control()
        original_auth_mode = module.auth_mode
        module.auth_mode = lambda: "header"
        try:
            sql, params, next_idx = module.ticket_filter_clause(
                {
                    "roles": ["analyst"],
                    "capabilities": ["tickets:read"],
                    "scopes": [{"scope_type": "group", "scope_value": "Dev Team Y"}],
                    "max_classification": "confidential",
                },
                "t",
                3,
            )
            self.assertIn("security_classification", sql)
            self.assertIn("owning_group", sql)
            self.assertEqual(params, [2, ["Dev Team Y"]])
            self.assertEqual(next_idx, 5)
        finally:
            module.auth_mode = original_auth_mode

    def test_agent_vault_lease_match_is_system_resource_action_specific(self):
        module, _ = load_access_control()

        lease = {
            "system": "gitlab",
            "resource_type": "project",
            "resource_id": "dev-y/*",
            "action": "read",
        }

        self.assertTrue(module._lease_matches(lease, "gitlab", "project", "dev-y/app", "read"))
        self.assertFalse(module._lease_matches(lease, "gitlab", "project", "dev-z/app", "read"))
        self.assertFalse(module._lease_matches(lease, "gitlab", "project", "dev-y/app", "write"))

    def test_default_agent_vault_ref_does_not_embed_secret_material(self):
        module, _ = load_access_control()

        ref = module.default_agent_vault_ref(42, {
            "system": "gitlab",
            "resource_type": "project",
            "resource_id": "dev-z/private repo",
            "action": "read",
        })

        self.assertEqual(ref, "<vault:agent_42_gitlab_project_dev_z_private_repo_read>")
        self.assertNotIn("password", ref.lower())
        self.assertNotIn("token", ref.lower())


if __name__ == "__main__":
    unittest.main()
