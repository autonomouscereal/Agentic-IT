import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_agent_runner():
    database = types.ModuleType("database")

    async def noop(*args, **kwargs):
        return None

    database.execute = noop
    database.fetchrow = noop
    database.fetchval = noop
    database.fetchall = noop
    sys.modules["database"] = database

    services = types.ModuleType("services")
    sys.modules["services"] = services

    event_logger = types.ModuleType("services.event_logger")
    event_logger.log_event = noop
    sys.modules["services.event_logger"] = event_logger

    agent_harness = types.ModuleType("services.agent_harness")
    agent_harness.get_harness = lambda name: None
    agent_harness.list_harnesses = lambda: [{"name": "unit-test"}]
    sys.modules["services.agent_harness"] = agent_harness

    spec = importlib.util.spec_from_file_location(
        "tested_agent_runner",
        ROOT / "api" / "services" / "agent_runner.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_agents_route():
    fastapi = types.ModuleType("fastapi")

    class APIRouter:
        def __init__(self, *args, **kwargs):
            pass

        def get(self, *args, **kwargs):
            return lambda fn: fn

        def post(self, *args, **kwargs):
            return lambda fn: fn

        def websocket(self, *args, **kwargs):
            return lambda fn: fn

    fastapi.APIRouter = APIRouter
    fastapi.Query = lambda default=None, **kwargs: default
    fastapi.Body = lambda default=None, **kwargs: default
    fastapi.WebSocket = object
    fastapi.WebSocketDisconnect = Exception
    sys.modules["fastapi"] = fastapi

    database = types.ModuleType("database")
    database.fetchall = None
    database.fetchrow = None
    database.execute = None
    database.fetchval = None
    database.json_dumps = lambda value: value
    database.json_loads = lambda value, default=None: value or default
    sys.modules["database"] = database

    services = types.ModuleType("services")
    sys.modules["services"] = services

    event_logger = types.ModuleType("services.event_logger")

    async def log_event(*args, **kwargs):
        return None

    event_logger.log_event = log_event
    sys.modules["services.event_logger"] = event_logger

    task_prompts = types.ModuleType("services.task_prompts")
    task_prompts.build_ticket_resolution_prompt = lambda ticket, extra_prompt=None: "prompt"
    sys.modules["services.task_prompts"] = task_prompts

    agent_runner = types.ModuleType("services.agent_runner")

    async def stop_agent_task(agent_id, reason="stopped via dashboard"):
        return {"status": "stopped", "task_id": 83, "reason": reason}

    agent_runner.stop_agent_task = stop_agent_task
    services.agent_runner = agent_runner
    sys.modules["services.agent_runner"] = agent_runner

    spec = importlib.util.spec_from_file_location(
        "tested_agents_route",
        ROOT / "api" / "routes" / "agents.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AgentLifecycleGuardTests(unittest.TestCase):
    def test_spawn_with_semaphore_skips_stopped_queued_task(self):
        module = load_agent_runner()
        events = []

        async def fetchrow(query, *args):
            return {
                "ticket_id": 312,
                "task_type": "ticket_resolution",
                "task_status": "stopped",
                "agent_status": "stopped",
            }

        async def log_event(*args):
            events.append(args)

        async def fail_run_agent(*args):
            raise AssertionError("_run_agent should not be called for stopped queued task")

        module.fetchrow = fetchrow
        module.log_event = log_event
        module._run_agent = fail_run_agent
        module._semaphore = asyncio.Semaphore(1)

        asyncio.run(module._spawn_with_semaphore("/tmp/work", "prompt", 86, 88))

        self.assertTrue(any(event[3] == "agent_spawn_skipped_not_runnable" for event in events))

    def test_stop_agent_task_marks_queued_task_stopped_with_reason(self):
        module = load_agent_runner()
        executes = []
        events = []

        async def fetchrow(query, *args):
            return {"id": 86, "pid": None}

        async def execute(*args):
            executes.append(args)

        async def log_event(*args):
            events.append(args)

        module.fetchrow = fetchrow
        module.execute = execute
        module.log_event = log_event

        result = asyncio.run(module.stop_agent_task(88, reason="duplicate queued agent"))

        self.assertEqual(result["status"], "stopped")
        self.assertEqual(result["task_id"], 86)
        self.assertTrue(any("UPDATE agent_tasks SET status = 'stopped'" in call[0] for call in executes))
        self.assertTrue(any("duplicate queued agent" in str(call) for call in executes))
        self.assertTrue(any(event[3] == "agent_stopped" for event in events))

    def test_stop_agent_reassigns_ticket_to_remaining_active_agent(self):
        module = load_agents_route()
        executes = []
        events = []

        async def fetchrow(query, *args):
            if "SELECT id, ticket_id FROM agents" in query:
                return {"id": 88, "ticket_id": 312}
            if "SELECT id, agent_id FROM tickets" in query:
                return {"id": 312, "agent_id": 88}
            if "SELECT id FROM agents" in query:
                return {"id": 85}
            return None

        async def execute(*args):
            executes.append(args)

        async def log_event(*args):
            events.append(args)

        module.fetchrow = fetchrow
        module.execute = execute
        module.log_event = log_event

        result = asyncio.run(module.stop_agent(88, {"reason": "duplicate approval resume"}))

        self.assertEqual(result["status"], "stopped")
        self.assertTrue(any("UPDATE tickets" in call[0] and call[1] == 85 and call[2] == 312 for call in executes))
        self.assertTrue(any(event[3] == "ticket_agent_reassigned_after_stop" for event in events))


if __name__ == "__main__":
    unittest.main()
