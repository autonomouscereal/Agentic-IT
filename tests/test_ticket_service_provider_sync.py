import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_ticket_service(calls):
    database = types.ModuleType("database")
    stored = {}

    async def fetchval(query, *args):
        calls.append(("fetchval", query, args))
        if "INSERT INTO tickets" in query:
            stored["ticket"] = {
                "id": 901,
                "itop_ref": args[0],
                "itop_class": args[1],
                "title": args[2],
                "description": args[3],
                "status": args[4],
                "priority": args[5],
                "opened_by_name": args[8],
                "opened_by_email": args[9],
                "requester_name": args[10],
                "requester_email": args[11],
                "affected_user_name": args[12],
                "affected_user_email": args[13],
                "provider": args[14],
                "provider_ref": args[15],
                "provider_class": args[16],
                "provider_sync_status": args[17],
            }
            return 901
        return None

    async def fetchrow(query, *args):
        calls.append(("fetchrow", query, args))
        if "SELECT * FROM tickets WHERE id = $1" in query:
            ticket = dict(stored.get("ticket") or {})
            ticket["id"] = args[0]
            return ticket
        if "SELECT id FROM tickets WHERE id = $1" in query:
            return {"id": args[0]}
        return None

    async def fetchall(query, *args):
        calls.append(("fetchall", query, args))
        return []

    async def execute(query, *args):
        calls.append(("execute", query, args))
        if "provider_sync_status = 'synced'" in query and stored.get("ticket"):
            stored["ticket"].update({
                "provider": args[0],
                "itop_ref": args[1],
                "itop_class": args[2],
                "provider_ref": args[1],
                "provider_class": args[2],
                "provider_url": args[3],
                "provider_sync_status": "synced",
            })
        return None

    database.fetchval = fetchval
    database.fetchrow = fetchrow
    database.fetchall = fetchall
    database.execute = execute
    database.json_dumps = lambda value: value
    sys.modules["database"] = database

    services = types.ModuleType("services")
    sys.modules["services"] = services

    event_logger = types.ModuleType("services.event_logger")

    async def log_event(*args):
        calls.append(("log_event", args))

    event_logger.log_event = log_event
    sys.modules["services.event_logger"] = event_logger

    ticket_links = types.ModuleType("services.ticket_links")
    ticket_links.external_ticket_url = lambda ticket: None
    sys.modules["services.ticket_links"] = ticket_links

    workflow_keys = types.ModuleType("services.workflow_keys")
    workflow_keys.workflow_key_for_ticket = lambda ticket: "userrequest:test"
    sys.modules["services.workflow_keys"] = workflow_keys

    lease_inference = types.ModuleType("services.lease_inference")
    lease_inference.infer_lease_request = lambda *args, **kwargs: None
    sys.modules["services.lease_inference"] = lease_inference

    provider_registry = types.ModuleType("services.provider_registry")
    provider_registry.default_ticket_provider = lambda preferred=None: "local" if preferred == "local" else "itop"

    async def create_ticket(provider, ticket_id, fields):
        calls.append(("provider_create_ticket", provider, ticket_id, fields))
        return {
            "status": "created",
            "provider": provider,
            "provider_ref": "777",
            "provider_class": fields["provider_class"],
            "provider_url": "http://itop.local/pages/UI.php?operation=details&class=RoutineChange&id=777",
        }

    provider_registry.create_ticket = create_ticket
    sys.modules["services.provider_registry"] = provider_registry
    services.provider_registry = provider_registry

    auto_assignment = types.ModuleType("services.auto_assignment")

    async def maybe_auto_assign(ticket_id, source=None):
        calls.append(("auto_assign", ticket_id, source))
        return {"status": "skipped"}

    auto_assignment.maybe_auto_assign = maybe_auto_assign
    sys.modules["services.auto_assignment"] = auto_assignment
    services.auto_assignment = auto_assignment

    spec = importlib.util.spec_from_file_location(
        "tested_ticket_service",
        ROOT / "api" / "services" / "ticket_service.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TicketServiceProviderSyncTests(unittest.TestCase):
    def test_normalizes_made_up_classes(self):
        calls = []
        module = load_ticket_service(calls)
        self.assertEqual(module.normalize_ticket_class("Change"), "RoutineChange")
        self.assertEqual(module.normalize_ticket_class("BrokerLeaseProof"), "UserRequest")
        self.assertEqual(module.normalize_ticket_class("WorkflowReuseSmoke1778854487"), "UserRequest")
        self.assertEqual(module.normalize_ticket_class("phishing smoke proof"), "Incident")

    def test_create_ticket_syncs_to_configured_provider_by_default(self):
        calls = []
        module = load_ticket_service(calls)
        ticket = asyncio.run(module.create_ticket(
            title="Provider sync unit",
            description="Should select iTop by default.",
            ticket_class="Change",
            created_by="unit-test",
            auto_assign=False,
        ))
        provider_calls = [call for call in calls if call[0] == "provider_create_ticket"]
        self.assertEqual(provider_calls[0][1], "itop")
        self.assertEqual(provider_calls[0][3]["ticket_class"], "RoutineChange")
        self.assertEqual(provider_calls[0][3]["provider_class"], "RoutineChange")
        self.assertEqual(ticket["itop_class"], "RoutineChange")
        self.assertEqual(ticket["provider"], "itop")

    def test_create_ticket_persists_contacts_and_sends_provider_context(self):
        calls = []
        module = load_ticket_service(calls)
        ticket = asyncio.run(module.create_ticket(
            title="Jeff needs Figma",
            description="Install request from chat.",
            ticket_class="UserRequest",
            opened_by_name="Ops Chat Agent",
            requester_name="Demo Account",
            requester_email="demo@example.invalid",
            affected_user_name="Jeff Example",
            affected_user_email="jeff@example.invalid",
            created_by="unit-test",
            auto_assign=False,
        ))
        provider_call = [call for call in calls if call[0] == "provider_create_ticket"][0]
        provider_fields = provider_call[3]
        self.assertEqual(ticket["requester_name"], "Demo Account")
        self.assertEqual(ticket["affected_user_name"], "Jeff Example")
        self.assertIn("Affected user: Jeff Example (jeff@example.invalid)", provider_fields["description"])

    def test_explicit_local_stays_local(self):
        calls = []
        module = load_ticket_service(calls)
        asyncio.run(module.create_ticket(
            title="Local provider unit",
            description="Provider adapter tests may explicitly stay local.",
            ticket_class="Incident",
            provider="local",
            created_by="unit-test",
            auto_assign=False,
        ))
        self.assertFalse([call for call in calls if call[0] == "provider_create_ticket"])

    def test_create_ticket_truncates_provider_unsafe_titles(self):
        calls = []
        module = load_ticket_service(calls)
        long_title = "Codex smoke " + ("marker file verification " * 20)
        ticket = asyncio.run(module.create_ticket(
            title=long_title,
            description="Long prompts should not break iTop create.",
            ticket_class="UserRequest",
            created_by="unit-test",
            auto_assign=False,
        ))
        provider_call = [call for call in calls if call[0] == "provider_create_ticket"][0]
        provider_title = provider_call[3]["title"]
        self.assertLessEqual(len(ticket["title"]), module.MAX_PROVIDER_TITLE_LENGTH)
        self.assertLessEqual(len(provider_title), module.MAX_PROVIDER_TITLE_LENGTH)
        self.assertTrue(provider_title.endswith("..."))


if __name__ == "__main__":
    unittest.main()
