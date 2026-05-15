import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_tickets_route():
    fastapi = types.ModuleType("fastapi")

    class APIRouter:
        def __init__(self, *args, **kwargs):
            pass

        def get(self, *args, **kwargs):
            return lambda fn: fn

        def post(self, *args, **kwargs):
            return lambda fn: fn

        def put(self, *args, **kwargs):
            return lambda fn: fn

        def patch(self, *args, **kwargs):
            return lambda fn: fn

    class HTTPException(Exception):
        def __init__(self, status_code=None, detail=None):
            self.status_code = status_code
            self.detail = detail
            super().__init__(detail)

    fastapi.APIRouter = APIRouter
    fastapi.Query = lambda default=None, **kwargs: default
    fastapi.Body = lambda default=None, **kwargs: default
    fastapi.HTTPException = HTTPException
    sys.modules["fastapi"] = fastapi

    database = types.ModuleType("database")
    database.fetchall = None
    database.fetchrow = None
    database.execute = None
    database.fetchval = None
    database.json_dumps = lambda value: value
    sys.modules["database"] = database

    services = types.ModuleType("services")
    sys.modules["services"] = services

    provider_registry = types.ModuleType("services.provider_registry")
    provider_registry.close_ticket = None
    provider_registry.sync_ticket = None
    provider_registry.full_sync = None
    sys.modules["services.provider_registry"] = provider_registry
    services.provider_registry = provider_registry

    ticket_service = types.ModuleType("services.ticket_service")
    ticket_service.compact_ticket_payload = lambda ticket: ticket
    ticket_service.add_note = None
    sys.modules["services.ticket_service"] = ticket_service
    services.ticket_service = ticket_service

    ticket_links = types.ModuleType("services.ticket_links")
    ticket_links.external_ticket_url = lambda ticket: ""
    sys.modules["services.ticket_links"] = ticket_links

    task_prompts = types.ModuleType("services.task_prompts")
    task_prompts.build_ticket_resolution_prompt = lambda ticket: "work ticket"
    task_prompts.build_postmortem_prompt = lambda ticket, context=None: "postmortem"
    task_prompts.build_workflow_prompt = lambda ticket, context=None: "workflow"
    sys.modules["services.task_prompts"] = task_prompts

    event_logger = types.ModuleType("services.event_logger")
    event_logger.log_event = None
    sys.modules["services.event_logger"] = event_logger

    spec = importlib.util.spec_from_file_location(
        "tested_tickets_route",
        ROOT / "api" / "routes" / "tickets.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, provider_registry, ticket_service


class TicketStatusEndpointTests(unittest.TestCase):
    def test_status_update_does_not_close_provider_unless_requested(self):
        module, provider_registry, ticket_service = load_tickets_route()
        executes = []
        notes = []
        events = []
        provider_calls = []

        async def fetchrow(query, *args):
            return {"id": 442, "provider": "itop", "provider_ref": "275", "status": "in_progress"}

        async def execute(query, *args):
            executes.append((query, args))

        async def add_note(*args, **kwargs):
            notes.append((args, kwargs))
            return {"id": 770, "ticket_id": args[0], "status": "created"}

        async def close_ticket(*args, **kwargs):
            provider_calls.append((args, kwargs))
            return {"status": "resolved"}

        async def log_event(*args, **kwargs):
            events.append((args, kwargs))

        module.fetchrow = fetchrow
        module.execute = execute
        module.log_event = log_event
        ticket_service.add_note = add_note
        provider_registry.close_ticket = close_ticket

        result = asyncio.run(module.update_ticket_status(
            442,
            status="resolved",
            actor="agent-159",
            reason="Agent verified all workflow completion criteria.",
            close_provider=False,
        ))

        self.assertEqual(result["status"], "resolved")
        self.assertEqual(provider_calls, [])
        self.assertTrue(any("UPDATE tickets SET status" in call[0] for call in executes))
        self.assertEqual(notes[0][0][0], 442)
        self.assertEqual(events[0][0][3], "ticket_status_updated")

    def test_status_update_can_explicitly_close_provider(self):
        module, provider_registry, ticket_service = load_tickets_route()
        provider_calls = []

        async def fetchrow(query, *args):
            return {"id": 442, "provider": "itop", "provider_ref": "275", "status": "in_progress"}

        async def execute(*args, **kwargs):
            return None

        async def add_note(*args, **kwargs):
            return {"id": 771, "ticket_id": args[0], "status": "created"}

        async def close_ticket(*args, **kwargs):
            provider_calls.append((args, kwargs))
            return {"status": "resolved"}

        async def log_event(*args, **kwargs):
            return None

        module.fetchrow = fetchrow
        module.execute = execute
        module.log_event = log_event
        ticket_service.add_note = add_note
        provider_registry.close_ticket = close_ticket

        result = asyncio.run(module.update_ticket_status(
            442,
            status="resolved",
            actor="agent-159",
            reason="Workflow policy allows agent closure.",
            close_provider=True,
        ))

        self.assertEqual(result["provider_result"]["status"], "resolved")
        self.assertEqual(provider_calls[0][0][0], "itop")
        self.assertEqual(provider_calls[0][0][1], 442)

    def test_compat_status_update_accepts_agent_ticket_patch_shape(self):
        module, provider_registry, ticket_service = load_tickets_route()
        executes = []
        notes = []

        async def fetchrow(query, *args):
            return {"id": 537, "provider": "local", "provider_ref": "LOCAL-537", "status": "in_progress"}

        async def execute(query, *args):
            executes.append((query, args))

        async def add_note(*args, **kwargs):
            notes.append((args, kwargs))
            return {"id": 1189, "ticket_id": args[0], "status": "created"}

        async def close_ticket(*args, **kwargs):
            raise AssertionError("provider close should remain opt-in")

        async def log_event(*args, **kwargs):
            return None

        module.fetchrow = fetchrow
        module.execute = execute
        module.log_event = log_event
        ticket_service.add_note = add_note
        provider_registry.close_ticket = close_ticket

        result = asyncio.run(module.update_ticket_status_compat(
            537,
            body={
                "status": "closed",
                "close_provider": False,
            },
        ))

        self.assertEqual(result["status"], "closed")
        self.assertTrue(any(call[1][0] == "closed" for call in executes))
        self.assertEqual(notes[0][1]["source"], "ticket-status")


if __name__ == "__main__":
    unittest.main()
