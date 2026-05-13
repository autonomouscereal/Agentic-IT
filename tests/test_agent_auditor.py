import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_agent_auditor():
    database = types.ModuleType("database")

    async def noop(*args, **kwargs):
        return None

    database.fetchall = noop
    database.fetchrow = noop
    database.fetchval = noop
    database.execute = noop
    database.json_dumps = lambda value: value
    sys.modules["database"] = database

    services = types.ModuleType("services")
    sys.modules["services"] = services

    event_logger = types.ModuleType("services.event_logger")
    event_logger.log_event = noop
    sys.modules["services.event_logger"] = event_logger

    spec = importlib.util.spec_from_file_location(
        "tested_agent_auditor",
        ROOT / "api" / "services" / "agent_auditor.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AgentAuditorTests(unittest.TestCase):
    def test_failed_task_suppresses_recent_ticket_duplicate(self):
        module = load_agent_auditor()
        records = []

        async def recent_duplicate(task_id, finding, minutes=15):
            return None

        async def recent_ticket_duplicate(ticket_id, finding, minutes=60):
            return {"id": 44}

        async def record(*args, **kwargs):
            records.append((args, kwargs))

        module._recent_duplicate = recent_duplicate
        module._recent_ticket_duplicate = recent_ticket_duplicate
        module._record = record

        row = {
            "agent_id": 88,
            "ticket_id": 312,
            "model": "qwen/qwen3.6-27b",
            "selected_model": "qwen/qwen3.6-27b5",
            "attempts": 0,
            "task_id": 86,
            "task_status": "failed",
            "prompt": "work ticket",
            "task_type": "ticket_resolution",
            "checkpoints": [],
            "started_at": None,
        }
        asyncio.run(module._audit_task(row))

        self.assertEqual(records, [])

    def test_completed_task_records_terminal_audit_evidence(self):
        module = load_agent_auditor()
        records = []

        async def recent_duplicate(task_id, finding, minutes=15):
            return None

        async def completed_task_evidence(agent, task):
            return {
                "ticket_status": "resolved",
                "task_status": "completed",
                "progress_pct": 100,
                "open_changes": 0,
                "completed_changes": 3,
                "postmortems": 1,
            }

        async def record(*args, **kwargs):
            records.append((args, kwargs))

        async def complete_approved_changes_for_task(*args, **kwargs):
            return {"completed": 0}

        agent_runner = types.ModuleType("services.agent_runner")
        agent_runner.complete_approved_changes_for_task = complete_approved_changes_for_task
        sys.modules["services.agent_runner"] = agent_runner
        sys.modules["services"].agent_runner = agent_runner

        module._recent_duplicate = recent_duplicate
        module._completed_task_evidence = completed_task_evidence
        module._record = record

        row = {
            "agent_id": 129,
            "ticket_id": 366,
            "model": "qwen/qwen3.6-27b",
            "selected_model": "qwen/qwen3.6-27b",
            "attempts": 0,
            "task_id": 126,
            "task_status": "completed",
            "prompt": "work ticket",
            "task_type": "ticket_resolution",
            "checkpoints": [],
            "started_at": None,
            "completed_at": "2026-05-13T03:49:21Z",
        }
        asyncio.run(module._audit_task(row))

        self.assertEqual(records[0][0][4], "agent_task_completed")
        details = records[0][0][8]
        self.assertEqual(details["ticket_status"], "resolved")
        self.assertEqual(details["open_changes"], 0)
        self.assertEqual(details["completed_changes"], 3)
        self.assertEqual(details["postmortems"], 1)


if __name__ == "__main__":
    unittest.main()
