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


if __name__ == "__main__":
    unittest.main()
