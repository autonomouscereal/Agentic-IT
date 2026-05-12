import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_itop_sync():
    database = types.ModuleType("database")
    database.fetchall = lambda *args, **kwargs: None
    database.fetchrow = lambda *args, **kwargs: None
    database.fetchval = lambda *args, **kwargs: None
    database.json_dumps = lambda value: value

    async def execute(*args, **kwargs):
        return None

    database.execute = execute
    sys.modules["database"] = database

    services = types.ModuleType("services")
    sys.modules["services"] = services

    ticket_provider = types.ModuleType("services.ticket_provider")

    class TicketProvider:
        pass

    ticket_provider.TicketProvider = TicketProvider
    sys.modules["services.ticket_provider"] = ticket_provider

    event_logger = types.ModuleType("services.event_logger")

    async def log_event(*args, **kwargs):
        return None

    event_logger.log_event = log_event
    sys.modules["services.event_logger"] = event_logger

    spec = importlib.util.spec_from_file_location("tested_itop_sync", ROOT / "api" / "services" / "itop_sync.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class iTopOutboundTests(unittest.TestCase):
    def test_helper_mappings(self):
        module = load_itop_sync()
        self.assertEqual(module._normalize_ticket_class("Change"), "RoutineChange")
        self.assertEqual(module._normalize_ticket_class("Incident"), "Incident")
        self.assertEqual(module._priority_to_impact_urgency("P1"), (1, 1))
        self.assertEqual(module._priority_to_impact_urgency("P2"), (2, 2))
        self.assertEqual(module._priority_to_impact_urgency("P4"), (3, 4))
        self.assertEqual(module._object_key("Incident::170", {"fields": {"title": "x"}}), "170")

    def test_create_ticket_resolves_defaults_and_uses_valid_fields(self):
        module = load_itop_sync()
        calls = []

        async def fake_itop_request(operation, **fields):
            calls.append((operation, fields))
            if operation == "core/get" and fields["class"] == "Organization":
                self.assertEqual(fields["output_fields"], "id,name,friendlyname")
                return {"code": 0, "objects": {"Organization::1": {"fields": {"id": "1", "name": "Org"}}}}
            if operation == "core/get" and fields["class"] == "Person":
                return {"code": 0, "objects": {"Person::94": {"fields": {"id": "94", "org_id": "1"}}}}
            if operation == "core/get" and fields["class"] == "Team":
                return {"code": 0, "objects": {"Team::65": {"fields": {"id": "65", "org_id": "1"}}}}
            if operation == "core/create":
                return {"code": 0, "objects": {"Incident::170": {"fields": {"id": "170", "title": fields["fields"]["title"]}}}}
            return {"code": 1, "message": "unexpected"}

        updates = []

        async def fake_execute(*args):
            updates.append(args)

        module.itop_request = fake_itop_request
        module.execute = fake_execute
        module.ITOP_DEFAULT_ORG_ID = ""
        module.ITOP_DEFAULT_CALLER_ID = ""
        module.ITOP_SECURITY_TEAM_ID = "65"

        provider = module.iTopProvider()
        result = asyncio.run(provider.create_ticket(127, {
            "title": "Unit Incident",
            "description": "Created from unit test",
            "ticket_class": "Incident",
            "provider_class": "Incident",
            "priority": "P2",
        }))

        self.assertEqual(result["status"], "created")
        self.assertEqual(result["provider_ref"], "170")
        create_call = [item for item in calls if item[0] == "core/create"][0][1]
        self.assertEqual(create_call["class"], "Incident")
        self.assertEqual(create_call["fields"]["org_id"], "1")
        self.assertEqual(create_call["fields"]["caller_id"], "94")
        self.assertEqual(create_call["fields"]["team_id"], "65")
        self.assertEqual(create_call["fields"]["impact"], 2)
        self.assertEqual(create_call["fields"]["urgency"], 2)
        self.assertTrue(updates)


if __name__ == "__main__":
    unittest.main()
