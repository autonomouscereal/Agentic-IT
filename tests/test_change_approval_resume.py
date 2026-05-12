import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_changes_module():
    fastapi = types.ModuleType("fastapi")

    class APIRouter:
        def __init__(self, *args, **kwargs):
            pass

        def get(self, *args, **kwargs):
            return lambda fn: fn

        def post(self, *args, **kwargs):
            return lambda fn: fn

    fastapi.APIRouter = APIRouter
    fastapi.Query = lambda default=None, **kwargs: default
    fastapi.Body = lambda default=None, **kwargs: default
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

    event_logger = types.ModuleType("services.event_logger")

    async def log_event(*args, **kwargs):
        return None

    event_logger.log_event = log_event
    sys.modules["services.event_logger"] = event_logger

    spec = importlib.util.spec_from_file_location(
        "tested_changes",
        ROOT / "api" / "routes" / "changes.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ChangeApprovalResumeTests(unittest.TestCase):
    def test_change_completion_accepts_agent_evidence_alias(self):
        module = load_changes_module()

        result = module._completion_result_from_body({
            "agent_id": 85,
            "evidence": "Lab no-op URL block was verified.",
        })
        actor = module._completion_actor_from_body({
            "agent_id": 85,
            "evidence": "Lab no-op URL block was verified.",
        })

        self.assertEqual(result, "Lab no-op URL block was verified.")
        self.assertEqual(actor, "agent_85")

    def test_change_completion_rejects_blank_evidence(self):
        module = load_changes_module()

        result = module._completion_result_from_body({
            "result": "",
            "evidence": "   ",
            "output": None,
        })

        self.assertEqual(result, "")

    def test_resume_skips_when_ticket_already_has_active_agent(self):
        module = load_changes_module()
        calls = []

        async def fetchrow(query, *args):
            calls.append((query, args))
            if "FROM agent_tasks" in query and "WHERE agent_id" in query:
                return None
            if "FROM agents a" in query:
                return {"id": 85, "status": "working", "last_task_id": 83}
            self.fail(f"unexpected query after active ticket agent guard: {query}")

        module.fetchrow = fetchrow

        result = asyncio.run(module._resume_agent_after_approval({
            "id": 84,
            "agent_id": 81,
            "ticket_id": 312,
        }, "unit-approver"))

        self.assertEqual(result["status"], "already_active_ticket")
        self.assertEqual(result["agent_id"], 85)
        self.assertEqual(result["task_id"], 83)
        self.assertTrue(any("FROM agents a" in query for query, _ in calls))


if __name__ == "__main__":
    unittest.main()
