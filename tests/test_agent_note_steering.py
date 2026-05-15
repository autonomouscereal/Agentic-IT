import asyncio
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_agent_steering():
    database = types.ModuleType("database")

    async def noop(*args, **kwargs):
        return None

    database.fetchall = noop
    database.fetchval = noop
    database.execute = noop
    database.json_dumps = lambda value: json.dumps(value, default=str)
    sys.modules["database"] = database

    services = types.ModuleType("services")
    sys.modules["services"] = services

    event_logger = types.ModuleType("services.event_logger")
    event_logger.log_event = noop
    sys.modules["services.event_logger"] = event_logger

    spec = importlib.util.spec_from_file_location(
        "tested_agent_steering",
        ROOT / "api" / "services" / "agent_steering.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, database


def load_agent_runner():
    database = types.ModuleType("database")

    async def noop(*args, **kwargs):
        return None

    database.execute = noop
    database.fetchrow = noop
    database.fetchval = noop
    database.fetchall = noop
    database.json_dumps = lambda value: json.dumps(value, default=str)
    sys.modules["database"] = database

    services = types.ModuleType("services")
    sys.modules["services"] = services

    event_logger = types.ModuleType("services.event_logger")
    event_logger.log_event = noop
    sys.modules["services.event_logger"] = event_logger

    agent_harness = types.ModuleType("services.agent_harness")
    agent_harness.get_harness = lambda name: None
    agent_harness.list_harnesses = lambda: []
    sys.modules["services.agent_harness"] = agent_harness

    spec = importlib.util.spec_from_file_location(
        "tested_agent_runner_steering",
        ROOT / "api" / "services" / "agent_runner.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_itop_sync():
    database = types.ModuleType("database")

    async def noop(*args, **kwargs):
        return None

    database.fetchall = noop
    database.fetchrow = noop
    database.fetchval = noop
    database.execute = noop
    database.json_dumps = lambda value: json.dumps(value, default=str)
    sys.modules["database"] = database

    services = types.ModuleType("services")
    sys.modules["services"] = services

    ticket_provider = types.ModuleType("services.ticket_provider")

    class TicketProvider:
        pass

    ticket_provider.TicketProvider = TicketProvider
    sys.modules["services.ticket_provider"] = ticket_provider

    event_logger = types.ModuleType("services.event_logger")
    event_logger.log_event = noop
    sys.modules["services.event_logger"] = event_logger

    spec = importlib.util.spec_from_file_location(
        "tested_itop_sync_steering",
        ROOT / "api" / "services" / "itop_sync.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, database


class AgentNoteSteeringTests(unittest.TestCase):
    def test_dashboard_note_delivers_workspace_inbox_without_interrupt(self):
        module, database = load_agent_steering()
        with tempfile.TemporaryDirectory() as tmp:
            execute_calls = []

            async def fetchall(query, *args):
                if "FROM agents a" in query:
                    return [{"agent_id": 12, "task_id": 34, "work_dir": tmp, "task_status": "running"}]
                if "FROM agent_steering_events" in query:
                    return [{
                        "id": 77,
                        "ticket_id": 56,
                        "agent_id": 12,
                        "task_id": 34,
                        "note_id": 90,
                        "source": "dashboard",
                        "author": "operator",
                        "body": "User clarified that the VPN outage is limited to Team Y.",
                        "status": "pending",
                        "created_at": "2026-05-14T12:00:00Z",
                    }]
                return []

            async def fetchval(query, *args):
                return 77

            async def execute(query, *args):
                execute_calls.append((query, args))

            database.fetchall = fetchall
            database.fetchval = fetchval
            database.execute = execute
            module.fetchall = fetchall
            module.fetchval = fetchval
            module.execute = execute

            result = asyncio.run(module.record_ticket_note(
                56,
                90,
                "User clarified that the VPN outage is limited to Team Y.",
                author="operator",
                source="dashboard",
            ))

            self.assertEqual(result["status"], "created")
            inbox = json.loads((Path(tmp) / "agent_steering_inbox.json").read_text(encoding="utf-8"))
            self.assertEqual(inbox["updates"][0]["id"], 77)
            self.assertIn("Keep the original ticket objective", inbox["instructions"])
            self.assertIn("Team Y", (Path(tmp) / "AGENT_STEERING.md").read_text(encoding="utf-8"))
            self.assertTrue(any("UPDATE agent_steering_events" in call[0] for call in execute_calls))

    def test_agent_authored_notes_do_not_create_self_steering(self):
        module, database = load_agent_steering()
        calls = {"fetchall": 0}

        async def fetchall(query, *args):
            calls["fetchall"] += 1
            return []

        database.fetchall = fetchall
        module.fetchall = fetchall

        result = asyncio.run(module.record_ticket_note(
            56,
            91,
            "Agent progress note",
            author="agent-12",
            source="agent-control-plane",
        ))

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(calls["fetchall"], 0)

    def test_agent_prompt_instructs_non_interrupting_steering_poll(self):
        module = load_agent_runner()
        prompt = module._build_claude_md(
            {"id": 56, "title": "Steering prompt", "description": "demo"},
            [],
            "Work the ticket.",
        )

        self.assertIn("Live Ticket Note Steering", prompt)
        self.assertIn("agent_steering_inbox.json", prompt)
        self.assertIn("Do not drop prior requirements", prompt)

    def test_itop_case_log_diff_becomes_ticket_note(self):
        module, database = load_itop_sync()
        notes = []

        async def fetchval(query, *args):
            return None

        async def add_note(*args, **kwargs):
            notes.append((args, kwargs))
            return {"id": 101, "status": "created"}

        ticket_service = types.ModuleType("services.ticket_service")
        ticket_service.add_note = add_note
        sys.modules["services"].ticket_service = ticket_service
        sys.modules["services.ticket_service"] = ticket_service
        database.fetchval = fetchval
        module.fetchval = fetchval

        asyncio.run(module._sync_case_log_notes(
            56,
            "Incident",
            "777",
            {"public_log": {"entries": [{"user_login": "alice", "message": "<p>Use alternate VPN profile.</p>"}]}},
            {"fields": {"public_log": {"entries": []}}},
        ))

        self.assertEqual(notes[0][0][0], 56)
        self.assertEqual(notes[0][1]["source"], "itop")
        self.assertIn("alternate VPN profile", notes[0][0][1])

    def test_itop_sync_preserves_local_terminal_status_when_provider_lags(self):
        module, _database = load_itop_sync()

        self.assertEqual(
            module._effective_local_status("new", "resolved", has_active_agent=False),
            "resolved",
        )
        self.assertEqual(
            module._effective_local_status("assigned", "closed", has_active_agent=False),
            "closed",
        )
        self.assertEqual(
            module._effective_local_status("new", "awaiting_user_response", has_active_agent=True),
            "awaiting_user_response",
        )
        self.assertEqual(
            module._effective_local_status("new", "pending_approval", has_active_agent=False),
            "pending_approval",
        )
        self.assertEqual(
            module._effective_local_status("new", "awaiting_access", has_active_agent=False),
            "awaiting_access",
        )
        self.assertEqual(
            module._effective_local_status("resolved", "in_progress", has_active_agent=True),
            "resolved",
        )

    def test_itop_markup_is_stripped_for_synced_note_text(self):
        module, _database = load_itop_sync()

        self.assertEqual(
            module._strip_markup("<p>Requester added <b>VPN logs</b>.</p>"),
            "Requester added VPN logs.",
        )


if __name__ == "__main__":
    unittest.main()
