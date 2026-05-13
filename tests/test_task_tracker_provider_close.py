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

    def test_completed_checkpoint_closes_itop_provider_ticket(self):
        module = load_task_tracker()
        executes = []
        events = []
        provider_closes = []

        async def execute(query, *args):
            executes.append((query, args))

        async def fetchval(*args, **kwargs):
            return 9001

        async def log_event(*args):
            events.append(args)

        async def complete_approved_changes_for_task(*args, **kwargs):
            return {"completed": [], "skipped": []}

        async def close_provider(ticket_id, agent_id, task_id, notes):
            provider_closes.append((ticket_id, agent_id, task_id, notes))
            return {"status": "resolved"}

        agent_runner = types.ModuleType("services.agent_runner")
        agent_runner.complete_approved_changes_for_task = complete_approved_changes_for_task
        agent_runner._close_provider_ticket_if_needed = close_provider
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

        self.assertEqual(provider_closes, [(342, 113, 110, "provider close proof complete")])
        self.assertTrue(any("UPDATE tickets SET status = 'resolved'" in call[0] for call in executes))
        completed_event = [event for event in events if event[3] == "task_completed"][0]
        self.assertEqual(completed_event[5]["provider_close"]["status"], "resolved")


if __name__ == "__main__":
    unittest.main()
