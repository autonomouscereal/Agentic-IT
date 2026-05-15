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
        self.assertEqual(module._resolution_fields("Incident", "done"), {
            "resolution_code": "assistance",
            "solution": "done",
        })
        self.assertEqual(module._resolution_fields("RoutineChange", "done"), {})
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

    def test_list_keys_uses_select_for_sparse_provider_ids(self):
        module = load_itop_sync()
        calls = []

        async def fake_itop_request(operation, **fields):
            calls.append((operation, fields))
            self.assertEqual(operation, "core/get")
            self.assertEqual(fields["key"], "SELECT Incident")
            return {
                "code": 0,
                "objects": {
                    "Incident::3": {"fields": {"id": "3", "title": "old"}},
                    "Incident::198": {"fields": {"id": "198", "title": "bridge"}},
                    "Incident::42": {"fields": {"title": "object-ref fallback"}},
                },
            }

        module.itop_request = fake_itop_request
        provider = module.iTopProvider()
        keys = asyncio.run(provider._list_keys("Incident"))

        self.assertEqual(keys, [3, 42, 198])
        self.assertEqual(len(calls), 1)

    def test_close_ticket_prefers_provider_ref_for_outbound_itop_tickets(self):
        module = load_itop_sync()
        calls = []
        updates = []

        async def fake_fetchrow(query, *args):
            self.assertIn("COALESCE(provider_ref, itop_ref)", query)
            return {"itop_ref": "170", "itop_class": "Incident", "status": "assigned"}

        async def fake_itop_request(operation, **fields):
            calls.append((operation, fields))
            return {"code": 0}

        async def fake_execute(*args):
            updates.append(args)

        module.fetchrow = fake_fetchrow
        module.itop_request = fake_itop_request
        module.execute = fake_execute

        provider = module.iTopProvider()
        result = asyncio.run(provider.close_ticket(127, "provider close proof"))

        self.assertEqual(result["status"], "resolved")
        self.assertEqual(calls[0][1]["key"], "170")
        self.assertEqual(calls[0][1]["class"], "Incident")
        self.assertTrue(any("UPDATE tickets SET status = 'resolved'" in call[0] for call in updates))

    def test_close_ticket_assigns_with_empty_fields_before_resolve(self):
        module = load_itop_sync()
        calls = []

        async def fake_fetchrow(query, *args):
            return {"itop_ref": "239", "itop_class": "Incident", "status": "new"}

        async def fake_itop_request(operation, **fields):
            calls.append((operation, fields))
            if fields.get("stimulus") == "ev_resolve" and len(calls) == 1:
                return {"code": 1, "message": "Invalid stimulus: ev_resolve in state new"}
            if operation == "core/get":
                return {"code": 0, "objects": {"Incident::239": {"fields": {"status": "assigned"}}}}
            return {"code": 0}

        module.fetchrow = fake_fetchrow
        module.itop_request = fake_itop_request

        provider = module.iTopProvider()
        result = asyncio.run(provider.close_ticket(367, "provider close proof"))

        self.assertEqual(result["status"], "resolved")
        self.assertEqual(calls[1][1]["stimulus"], "ev_assign")
        self.assertEqual(calls[1][1]["fields"], {})
        self.assertEqual(calls[2][0], "core/get")
        self.assertEqual(calls[2][1]["output_fields"], "status")
        self.assertEqual(calls[3][1]["stimulus"], "ev_resolve")
        self.assertEqual(calls[3][1]["fields"], {
            "resolution_code": "assistance",
            "solution": "provider close proof",
        })

    def test_close_ticket_waits_for_assignment_state_before_resolve_retry(self):
        module = load_itop_sync()
        calls = []
        sleeps = []

        async def fake_fetchrow(query, *args):
            return {"itop_ref": "240", "itop_class": "Incident", "status": "new"}

        async def fake_sleep(seconds):
            sleeps.append(seconds)

        async def fake_itop_request(operation, **fields):
            calls.append((operation, fields))
            if fields.get("stimulus") == "ev_resolve" and len(calls) == 1:
                return {"code": 1, "message": "Invalid stimulus: ev_resolve in state new"}
            if operation == "core/get" and len(sleeps) == 0:
                return {"code": 0, "objects": {"Incident::240": {"fields": {"status": "new"}}}}
            if operation == "core/get":
                return {"code": 0, "objects": {"Incident::240": {"fields": {"status": "assigned"}}}}
            return {"code": 0}

        module.fetchrow = fake_fetchrow
        module.itop_request = fake_itop_request
        original_sleep = module.asyncio.sleep
        module.asyncio.sleep = fake_sleep
        try:
            provider = module.iTopProvider()
            result = asyncio.run(provider.close_ticket(368, "provider close proof"))
        finally:
            module.asyncio.sleep = original_sleep

        self.assertEqual(result["status"], "resolved")
        self.assertEqual(sleeps, [1])
        self.assertEqual(calls[-1][1]["stimulus"], "ev_resolve")

    def test_close_change_omits_incident_resolution_fields(self):
        module = load_itop_sync()
        calls = []

        async def fake_fetchrow(query, *args):
            return {"itop_ref": "346", "itop_class": "RoutineChange", "status": "assigned"}

        async def fake_itop_request(operation, **fields):
            calls.append((operation, fields))
            return {"code": 0}

        module.fetchrow = fake_fetchrow
        module.itop_request = fake_itop_request

        provider = module.iTopProvider()
        result = asyncio.run(provider.close_ticket(98, "change close proof"))

        self.assertEqual(result["status"], "resolved")
        self.assertEqual(calls[0][1]["class"], "RoutineChange")
        self.assertEqual(calls[0][1]["fields"], {})

    def test_close_retries_without_fields_on_unknown_attribute(self):
        module = load_itop_sync()
        calls = []

        async def fake_fetchrow(query, *args):
            return {"itop_ref": "170", "itop_class": "Incident", "status": "assigned"}

        async def fake_itop_request(operation, **fields):
            calls.append((operation, fields))
            if len(calls) == 1:
                return {"code": 1, "message": "Unknown attribute resolution_code from class Incident"}
            return {"code": 0}

        module.fetchrow = fake_fetchrow
        module.itop_request = fake_itop_request

        provider = module.iTopProvider()
        result = asyncio.run(provider.close_ticket(127, "retry close proof"))

        self.assertEqual(result["status"], "resolved")
        self.assertEqual(calls[0][1]["fields"]["resolution_code"], "assistance")
        self.assertEqual(calls[1][1]["fields"], {})

    def test_full_sync_imports_without_auto_assigning_historical_rows(self):
        module = load_itop_sync()
        provider = module.iTopProvider()
        synced = []

        async def fake_list_keys(itop_class):
            return [198] if itop_class == "Incident" else []

        async def fake_sync_ticket(itop_class, key, auto_assign=True):
            synced.append((itop_class, key, auto_assign))
            return {"status": "synced", "is_new": True}

        provider._list_keys = fake_list_keys
        provider.sync_ticket = fake_sync_ticket
        module._load_max_keys = lambda: {}
        module._save_max_keys = lambda data: None

        result = asyncio.run(provider.full_sync())

        self.assertEqual(result["new"], 1)
        self.assertEqual(synced, [("Incident", 198, False)])


if __name__ == "__main__":
    unittest.main()
