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

        original_public_health = module.public_health
        original_protect_ui = module.protect_ui
        module.public_health = lambda: False
        module.protect_ui = lambda: True
        try:
            self.assertEqual(module.required_permission("GET", "/"), "ui:read")
            self.assertIsNone(module.required_permission("GET", "/login"))
            self.assertIsNone(module.required_permission("GET", "/favicon.ico"))
            self.assertIsNone(module.required_permission("POST", "/api/auth/login"))
            self.assertEqual(module.required_permission("GET", "/static/js/dashboard.js"), "ui:read")
            self.assertEqual(module.required_permission("GET", "/health"), "health:read")
            self.assertEqual(module.required_permission("GET", "/api/providers"), "providers:read")
            self.assertEqual(module.required_permission("POST", "/api/skills/4/render"), "skills:write")
            self.assertEqual(module.required_permission("POST", "/api/intake/submit"), "intake:write")
            self.assertEqual(module.required_permission("GET", "/api/search/global"), "search:read")
            self.assertEqual(module.required_permission("GET", "/api/ops-chat/openai/v1/models"), "ops-chat:read")
            self.assertEqual(module.required_permission("POST", "/api/ops-chat/message"), "ops-chat:write")
        finally:
            module.public_health = original_public_health
            module.protect_ui = original_protect_ui

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

    def test_local_password_hash_verification(self):
        module, _ = load_access_control()

        stored = module.hash_password("correct horse")

        self.assertTrue(module.verify_password("correct horse", stored))
        self.assertFalse(module.verify_password("wrong horse", stored))
        self.assertFalse(module.verify_password("correct horse", "not-a-real-hash"))

    def test_header_auth_requires_trusted_proxy_secret_when_enforced(self):
        module, database = load_access_control()
        original_auth_mode = module.auth_mode
        original_enforcement_mode = module.enforcement_mode
        original_trusted_auth_secret = module.trusted_auth_secret
        module.auth_mode = lambda: "header"
        module.enforcement_mode = lambda: "enforce"
        module.trusted_auth_secret = lambda: "trusted-secret"

        async def fetchrow(query, *args):
            if "FROM dashboard_users" in query:
                return {"id": 1, "username": "demo_account_1", "enabled": True}
            return None

        async def fetchall(query, *args):
            if "dashboard_user_roles" in query:
                return [{"name": "platform-admin"}]
            if "dashboard_role_permissions" in query:
                return [{"permission_key": "*"}]
            return []

        database.fetchrow = fetchrow
        database.fetchall = fetchall
        module.fetchrow = fetchrow
        module.fetchall = fetchall
        try:
            denied = asyncio.run(module.evaluate_headers("GET", "/api/tickets", {
                "x-auth-request-user": "demo_account_1",
            }))
            allowed = asyncio.run(module.evaluate_headers("GET", "/api/tickets", {
                "x-auth-request-user": "demo_account_1",
                "x-dashboard-auth-secret": "trusted-secret",
            }))

            self.assertFalse(denied["allow"])
            self.assertEqual(denied["reason"], "missing_or_invalid_trusted_auth_secret")
            self.assertTrue(allowed["allow"])
            self.assertEqual(allowed["reason"], "capability_match")
        finally:
            module.auth_mode = original_auth_mode
            module.enforcement_mode = original_enforcement_mode
            module.trusted_auth_secret = original_trusted_auth_secret

    def test_service_token_is_explicit_platform_service_identity(self):
        module, _ = load_access_control()
        original_auth_mode = module.auth_mode
        original_enforcement_mode = module.enforcement_mode
        original_service_token = module.service_token
        module.auth_mode = lambda: "header"
        module.enforcement_mode = lambda: "enforce"
        module.service_token = lambda: "service-secret"
        try:
            decision = asyncio.run(module.evaluate_headers("POST", "/api/agents/1/update", {
                "x-dashboard-service-token": "service-secret",
                "x-dashboard-service-user": "agent-runner",
            }))
            self.assertTrue(decision["allow"])
            self.assertEqual(decision["reason"], "service_token_authenticated")
            self.assertEqual(decision["identity"]["username"], "agent-runner")
            self.assertEqual(decision["capabilities"], ["*"])
        finally:
            module.auth_mode = original_auth_mode
            module.enforcement_mode = original_enforcement_mode
            module.service_token = original_service_token

    def test_signed_session_cookie_authenticates_websocket_style_requests(self):
        module, database = load_access_control()
        original_auth_mode = module.auth_mode
        original_enforcement_mode = module.enforcement_mode
        original_trusted_auth_secret = module.trusted_auth_secret
        module.auth_mode = lambda: "header"
        module.enforcement_mode = lambda: "enforce"
        module.trusted_auth_secret = lambda: "trusted-secret"

        async def fetchrow(query, *args):
            if "FROM dashboard_users" in query:
                return {"id": 1, "username": "demo_account_1", "enabled": True}
            return None

        async def fetchall(query, *args):
            if "dashboard_user_roles" in query:
                return [{"name": "platform-admin"}]
            if "dashboard_role_permissions" in query:
                return [{"permission_key": "*"}]
            return []

        database.fetchrow = fetchrow
        database.fetchall = fetchall
        module.fetchrow = fetchrow
        module.fetchall = fetchall
        try:
            cookie = module.create_session_cookie({
                "username": "demo_account_1",
                "email": "demo@example.local",
                "provider": "trusted-proxy",
                "auth_mode": "header",
                "authenticated": True,
            })
            self.assertIsNotNone(cookie)
            decision = asyncio.run(module.evaluate_headers("GET", "/api/agents/ws", {
                "cookie": f"dashboard_session={cookie}",
            }))
            self.assertTrue(decision["allow"])
            self.assertEqual(decision["identity"]["auth_strength"], "signed-session-cookie")
        finally:
            module.auth_mode = original_auth_mode
            module.enforcement_mode = original_enforcement_mode
            module.trusted_auth_secret = original_trusted_auth_secret

    def test_signed_session_cookie_can_carry_agent_scoped_subject(self):
        module, database = load_access_control()
        original_auth_mode = module.auth_mode
        original_enforcement_mode = module.enforcement_mode
        original_trusted_auth_secret = module.trusted_auth_secret
        module.auth_mode = lambda: "header"
        module.enforcement_mode = lambda: "enforce"
        module.trusted_auth_secret = lambda: "trusted-secret"

        async def fetchrow(query, *args):
            raise AssertionError("embedded signed subject should not need a dashboard_users lookup")

        database.fetchrow = fetchrow
        module.fetchrow = fetchrow
        try:
            cookie = module.create_session_cookie(
                {
                    "username": "agent-runner-service",
                    "provider": "agent-runner",
                    "auth_mode": "agent-session",
                    "authenticated": True,
                },
                {
                    "roles": ["agent-operator"],
                    "capabilities": ["tickets:read", "tickets:note"],
                    "scopes": [{"scope_type": "ticket", "scope_value": "589"}],
                    "max_classification": "confidential",
                },
            )
            allowed = asyncio.run(module.evaluate_headers("GET", "/api/tickets/589/context", {
                "cookie": f"dashboard_session={cookie}",
            }))
            denied = asyncio.run(module.evaluate_headers("POST", "/api/access/users", {
                "cookie": f"dashboard_session={cookie}",
            }))

            self.assertTrue(allowed["allow"])
            self.assertEqual(allowed["reason"], "signed_session_subject_match")
            self.assertFalse(denied["allow"])
            self.assertEqual(denied["reason"], "missing_required_permission")
        finally:
            module.auth_mode = original_auth_mode
            module.enforcement_mode = original_enforcement_mode
            module.trusted_auth_secret = original_trusted_auth_secret

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

    def test_request_agent_vault_lease_returns_human_broker_trace_without_secret(self):
        module, database = load_access_control()
        executed = []
        events = []

        async def fetchall(query, *args):
            return [{
                "id": 77,
                "agent_id": 42,
                "system": "wazuh",
                "resource_type": "api",
                "resource_id": "wazuh.manager",
                "action": "read",
                "credential_ref": "<vault:wazuh_manager_read>",
            }]

        async def execute(*args):
            executed.append(args)

        async def log_event(*args):
            events.append(args)

        database.fetchall = fetchall
        database.execute = execute
        module.fetchall = fetchall
        module.execute = execute
        module.log_event = log_event

        result = asyncio.run(module.request_agent_vault_lease(
            42,
            "wazuh",
            "api",
            "wazuh.manager",
            "read",
        ))

        self.assertTrue(result["allow"])
        self.assertIsNone(result["credential_value"])
        self.assertEqual(result["credential_ref"], "<vault:wazuh_manager_read>")
        self.assertEqual(result["broker_trace"]["vault_provider"], "server-manager")
        self.assertIn("no secret value", result["broker_trace"]["human_summary"].lower())
        self.assertTrue(executed)
        self.assertTrue(events)
        self.assertIn("human_summary", events[0][5])

    def test_workflow_preapproved_leases_are_added_to_agent_manifest(self):
        module, database = load_access_control()
        inserts = []

        async def fetchrow(query, *args):
            if "FROM tickets" in query:
                return {
                    "id": 501,
                    "title": "Phishing investigation",
                    "description": "Investigate phishing report",
                    "itop_class": "Incident",
                    "provider_class": "Incident",
                    "owning_group": "Security Operations",
                    "security_classification": "internal",
                }
            return None

        async def fetchall(query, *args):
            if "FROM agent_workflows" in query:
                return [{
                    "id": 4,
                    "name": "Canonical phishing",
                    "status": "active",
                    "reviewed_at": "2026-05-15T00:00:00Z",
                    "workflow_key": "incident:phishing",
                    "approval_policy": {
                        "preapproved_leases": [
                            {
                                "system": "mailcow",
                                "resource_type": "mailbox",
                                "resource_id": "security-team@example.invalid",
                                "action": "read",
                                "credential_ref": "<vault:mailcow_security_read>",
                            },
                            {
                                "system": "wazuh",
                                "resource_type": "api",
                                "resource_id": "wazuh.manager",
                                "actions": ["read"],
                                "credential_ref": "<vault:wazuh_manager_read>",
                            },
                        ],
                    },
                }]
            if "FROM agent_vault_leases" in query:
                return [
                    {
                        "id": index + 1,
                        "agent_id": 88,
                        "system": row[2],
                        "resource_type": row[3],
                        "resource_id": row[4],
                        "action": row[5],
                        "credential_ref": row[6],
                        "lease_status": "active",
                    }
                    for index, row in enumerate(inserts)
                ]
            return []

        async def execute(query, *args):
            if "INSERT INTO agent_vault_leases" in query:
                inserts.append(args)

        database.fetchrow = fetchrow
        database.fetchall = fetchall
        database.execute = execute
        module.fetchrow = fetchrow
        module.fetchall = fetchall
        module.execute = execute

        manifest = asyncio.run(module.create_agent_vault_manifest(
            88,
            501,
            {
                "identity": {"username": "soc-operator"},
                "roles": ["soc-manager"],
                "capabilities": ["*"],
                "scopes": [],
                "max_classification": "restricted",
            },
        ))

        self.assertEqual(manifest["workflow_preapproved_lease_count"], 2)
        systems = {(row[1], row[2], row[3], row[4], row[5]) for row in inserts}
        self.assertIn(("mailcow", "mailbox", "security-team@example.invalid", "read", "<vault:mailcow_security_read>"), systems)
        self.assertIn(("wazuh", "api", "wazuh.manager", "read", "<vault:wazuh_manager_read>"), systems)
        self.assertEqual(manifest["broker_metadata"]["secret_values_returned"], False)


if __name__ == "__main__":
    unittest.main()
