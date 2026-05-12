import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_auto_assignment():
    database = types.ModuleType("database")

    async def fetchall(*args, **kwargs):
        return []

    async def fetchrow(*args, **kwargs):
        return None

    async def execute(*args, **kwargs):
        return None

    database.fetchall = fetchall
    database.fetchrow = fetchrow
    database.execute = execute
    sys.modules["database"] = database

    services = types.ModuleType("services")
    sys.modules["services"] = services

    event_logger = types.ModuleType("services.event_logger")

    async def log_event(*args, **kwargs):
        return None

    event_logger.log_event = log_event
    sys.modules["services.event_logger"] = event_logger

    task_prompts = types.ModuleType("services.task_prompts")

    def build_ticket_resolution_prompt(ticket, extra_prompt=None):
        return f"ticket={ticket.get('id')} prompt={extra_prompt or ''}"

    task_prompts.build_ticket_resolution_prompt = build_ticket_resolution_prompt
    sys.modules["services.task_prompts"] = task_prompts

    agent_runner = types.ModuleType("services.agent_runner")

    async def spawn_agent(ticket_id, model, prompt, task_type="ticket_resolution"):
        return {
            "status": "spawned",
            "ticket_id": ticket_id,
            "agent_id": 42,
            "task_id": 77,
            "model": model,
            "prompt": prompt,
            "task_type": task_type,
        }

    agent_runner.spawn_agent = spawn_agent
    services.agent_runner = agent_runner
    sys.modules["services.agent_runner"] = agent_runner

    spec = importlib.util.spec_from_file_location(
        "tested_auto_assignment",
        ROOT / "api" / "services" / "auto_assignment.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AutoAssignmentTests(unittest.TestCase):
    def test_matching_phishing_rule_spawns_agent(self):
        module = load_auto_assignment()
        calls = {"execute": []}

        async def fetchrow(query, *args):
            if "FROM tickets" in query:
                return {
                    "id": 10,
                    "title": "Phishing report",
                    "description": "User reported suspicious email with bad link.",
                    "itop_class": "Incident",
                    "provider_class": "Incident",
                    "assignee_team": "Security Operations",
                    "agent_id": None,
                }
            return None

        async def fetchall(*args):
            return [{
                "id": 3,
                "name": "Phishing report",
                "intent": "phishing",
                "keywords": ["phishing", "bad link"],
                "ticket_class": "Incident",
                "assignment_group": "Security Operations",
                "auto_agent_model": "qwen/qwen3.6-27b",
                "auto_agent_prompt": "Work phishing safely.",
            }]

        async def execute(*args):
            calls["execute"].append(args)
            return None

        module.fetchrow = fetchrow
        module.fetchall = fetchall
        module.execute = execute

        result = asyncio.run(module.maybe_auto_assign(10, source="unit-test"))
        self.assertEqual(result["status"], "assigned")
        self.assertEqual(result["agent_id"], 42)
        self.assertGreaterEqual(result["score"], 1)
        self.assertTrue(calls["execute"])

    def test_non_matching_rule_stays_manual(self):
        module = load_auto_assignment()

        async def fetchrow(query, *args):
            if "FROM tickets" in query:
                return {
                    "id": 11,
                    "title": "General service request",
                    "description": "Please update the dashboard label.",
                    "itop_class": "UserRequest",
                    "provider_class": "UserRequest",
                    "assignee_team": "Business Applications",
                    "agent_id": None,
                }
            return None

        async def fetchall(*args):
            return [{
                "id": 3,
                "name": "Phishing report",
                "intent": "phishing",
                "keywords": ["phishing", "bad link"],
                "ticket_class": "Incident",
                "assignment_group": "Security Operations",
            }]

        module.fetchrow = fetchrow
        module.fetchall = fetchall

        result = asyncio.run(module.maybe_auto_assign(11, source="unit-test"))
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "no_matching_policy")

    def test_existing_agent_is_not_duplicated(self):
        module = load_auto_assignment()

        async def fetchrow(query, *args):
            if "FROM tickets" in query:
                return {"id": 12, "agent_id": 99}
            return None

        module.fetchrow = fetchrow
        result = asyncio.run(module.maybe_auto_assign(12, source="unit-test"))
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "ticket_already_has_agent")
        self.assertEqual(result["agent_id"], 99)


if __name__ == "__main__":
    unittest.main()
