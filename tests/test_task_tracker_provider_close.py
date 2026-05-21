import asyncio
import importlib.util
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_task_tracker():
    database = types.ModuleType("database")

    async def noop(*args, **kwargs):
        return None

    database.fetchall = noop
    database.fetchrow = noop
    database.execute = noop
    database.fetchval = noop
    sys.modules["database"] = database

    services = types.ModuleType("services")
    sys.modules["services"] = services

    event_logger = types.ModuleType("services.event_logger")
    event_logger.log_event = noop
    sys.modules["services.event_logger"] = event_logger

    spec = importlib.util.spec_from_file_location(
        "tested_task_tracker",
        ROOT / "api" / "services" / "task_tracker.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TaskTrackerProviderCloseTests(unittest.TestCase):
    def test_runner_owned_task_is_not_orphaned_when_pid_exits(self):
        module = load_task_tracker()
        process = object()
        agent_runner = types.ModuleType("services.agent_runner")
        agent_runner._active_processes = {149: process}
        sys.modules["services.agent_runner"] = agent_runner
        sys.modules["services"].agent_runner = agent_runner

        self.assertTrue(module._runner_is_managing_task(149))
        self.assertFalse(module._runner_is_managing_task(150))

    def test_completed_checkpoint_does_not_close_ticket_implicitly(self):
        module = load_task_tracker()
        executes = []
        events = []
        provider_closes = []
        status_recoveries = []

        async def execute(query, *args):
            executes.append((query, args))

        async def fetchval(*args, **kwargs):
            return 9001

        async def log_event(*args):
            events.append(args)

        async def complete_approved_changes_for_task(*args, **kwargs):
            return {"completed": [], "skipped": []}

        async def close_provider(*args, **kwargs):
            provider_closes.append((args, kwargs))
            raise AssertionError("provider close should require an explicit ticket status action")

        async def recover_done_checkpoint_ticket_status(*args, **kwargs):
            status_recoveries.append((args, kwargs))
            return {"status": "skipped", "reason": "closure_not_required_by_prompt"}

        agent_runner = types.ModuleType("services.agent_runner")
        agent_runner.complete_approved_changes_for_task = complete_approved_changes_for_task
        agent_runner._close_provider_ticket_if_needed = close_provider
        agent_runner.recover_done_checkpoint_ticket_status = recover_done_checkpoint_ticket_status
        sys.modules["services.agent_runner"] = agent_runner
        sys.modules["services"].agent_runner = agent_runner

        module.execute = execute
        module.fetchval = fetchval
        module.log_event = log_event

        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = {
                "step": "complete",
                "status": "done",
                "progress_pct": 100,
                "output": "provider close proof complete",
                "timestamp": "2026-05-13T04:00:00Z",
            }
            Path(tmp, "checkpoint.json").write_text(json.dumps(checkpoint), encoding="utf-8")
            task = {
                "id": 110,
                "agent_id": 113,
                "ticket_id": 342,
                "task_type": "ticket_resolution",
                "work_dir": tmp,
                "checkpoints": [],
                "pid": None,
            }
            asyncio.run(module._sync_task_status(task))

        self.assertEqual(provider_closes, [])
        self.assertEqual(len(status_recoveries), 1)
        self.assertFalse(any("UPDATE tickets SET status = 'resolved'" in call[0] for call in executes))
        completed_event = [event for event in events if event[3] == "task_completed"][0]
        self.assertEqual(
            completed_event[5]["provider_close"]["reason"],
            "ticket_closure_requires_explicit_action",
        )
        self.assertEqual(
            completed_event[5]["ticket_status_recovery"]["reason"],
            "closure_not_required_by_prompt",
        )

    def test_orphaned_done_checkpoint_is_preserved_as_completion(self):
        module = load_task_tracker()
        executes = []
        events = []
        notes = []

        async def execute(query, *args):
            executes.append((query, args))

        async def fetchval(*args, **kwargs):
            return 9002

        async def log_event(*args):
            events.append(args)

        async def add_checkpoint_note(*args):
            notes.append(args)

        module.execute = execute
        module.fetchval = fetchval
        module.log_event = log_event
        module._add_checkpoint_note = add_checkpoint_note

        with tempfile.TemporaryDirectory() as tmp:
            checkpoint = {
                "step": "resolved",
                "status": "done",
                "progress_pct": 100,
                "output": "Codex finished before process tracker finalization.",
                "timestamp": "2026-05-21T15:07:25Z",
            }
            Path(tmp, "checkpoint.json").write_text(json.dumps(checkpoint), encoding="utf-8")
            task = {
                "id": 370,
                "agent_id": 373,
                "ticket_id": 1405,
                "task_type": "ticket_resolution",
                "work_dir": tmp,
                "checkpoints": [],
                "pid": 124,
            }
            asyncio.run(module._mark_orphaned(task, "Agent process is no longer running in the API container"))

        self.assertTrue(any("UPDATE agent_tasks SET status = 'completed'" in query for query, _ in executes))
        self.assertTrue(any("UPDATE agents SET status = 'finished'" in query for query, _ in executes))
        self.assertTrue(any(event[3] == "orphaned_process_preserved_done_checkpoint" for event in events))
        self.assertEqual(notes[0][0]["agent_id"], 373)
        self.assertEqual(notes[0][1:3], ("resolved", "done"))


if __name__ == "__main__":
    unittest.main()
