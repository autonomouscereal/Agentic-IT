#!/usr/bin/env python3
"""Smoke test RACI auto-assignment policy without spawning a real agent."""
import asyncio
import json
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))

database = types.ModuleType("database")


async def unused_db_call(*args, **kwargs):
    raise AssertionError("database call was not patched")


database.fetchall = unused_db_call
database.fetchrow = unused_db_call
database.execute = unused_db_call
sys.modules["database"] = database

from services import auto_assignment  # noqa: E402


RULES = [
    {
        "id": 11,
        "name": "Phishing report",
        "intent": "phishing",
        "keywords": ["phishing", "suspicious email", "bad link"],
        "ticket_class": "Incident",
        "assignment_group": "Security Operations",
        "auto_assign_agent": True,
        "auto_agent_model": "qwen/qwen3.6-27b",
        "auto_agent_prompt": "Smoke auto assignment prompt.",
    }
]

TICKETS = {
    101: {
        "id": 101,
        "title": "Suspicious email with bad link",
        "description": "User reported phishing message with suspicious email headers.",
        "itop_class": "Incident",
        "provider_class": "Incident",
        "assignee_team": "Security Operations",
        "provider": "itop",
        "agent_id": None,
    },
    102: {
        "id": 102,
        "title": "Request software install",
        "description": "User needs a normal desktop application installed.",
        "itop_class": "UserRequest",
        "provider_class": "UserRequest",
        "assignee_team": "Endpoint Support",
        "provider": "local",
        "agent_id": None,
    },
    103: {
        "id": 103,
        "title": "Already assigned phishing ticket",
        "description": "phishing",
        "itop_class": "Incident",
        "provider_class": "Incident",
        "assignee_team": "Security Operations",
        "provider": "itop",
        "agent_id": 7,
    },
}

CALLS = {"spawned": [], "notes": [], "events": []}


async def fake_fetchrow(query, *args):
    if "FROM tickets WHERE id" in query:
        return TICKETS.get(args[0])
    if "FROM agents" in query:
        return None
    raise AssertionError(f"unexpected fetchrow: {query}")


async def fake_fetchall(query, *args):
    if "FROM service_raci_rules" in query:
        return RULES
    raise AssertionError(f"unexpected fetchall: {query}")


async def fake_execute(query, *args):
    if "INSERT INTO ticket_notes" in query:
        CALLS["notes"].append(args)
        return "INSERT 0 1"
    raise AssertionError(f"unexpected execute: {query}")


async def fake_log_event(*args):
    CALLS["events"].append(args)


async def fake_spawn_agent(ticket_id, model, prompt, task_type="ticket_resolution"):
    CALLS["spawned"].append({
        "ticket_id": ticket_id,
        "model": model,
        "prompt": prompt,
        "task_type": task_type,
    })
    return {"agent_id": 501, "task_id": 601}


def require(condition, message):
    if not condition:
        raise SystemExit(message)


async def main():
    auto_assignment.fetchall = fake_fetchall
    auto_assignment.fetchrow = fake_fetchrow
    auto_assignment.execute = fake_execute
    auto_assignment.log_event = fake_log_event
    sys.modules["services.agent_runner"] = types.SimpleNamespace(spawn_agent=fake_spawn_agent)

    assigned = await auto_assignment.maybe_auto_assign(101, source="smoke")
    skipped = await auto_assignment.maybe_auto_assign(102, source="smoke")
    duplicate = await auto_assignment.maybe_auto_assign(103, source="smoke")

    require(assigned.get("status") == "assigned", f"expected assignment, got {assigned}")
    require(assigned.get("rule_id") == 11, f"expected phishing rule, got {assigned}")
    require(len(CALLS["spawned"]) == 1, f"expected one spawn, got {CALLS['spawned']}")
    require(CALLS["spawned"][0]["ticket_id"] == 101, "spawned wrong ticket")
    require("Smoke auto assignment prompt." in CALLS["spawned"][0]["prompt"], "missing policy prompt")
    require(len(CALLS["notes"]) == 1, "missing auto-assignment ticket note")
    require(skipped.get("reason") == "no_matching_policy", f"expected no match, got {skipped}")
    require(duplicate.get("reason") == "ticket_already_has_agent", f"expected duplicate skip, got {duplicate}")

    print(json.dumps({
        "ok": True,
        "assigned": assigned,
        "manual_queue_skip": skipped,
        "duplicate_skip": duplicate,
        "spawn_calls": len(CALLS["spawned"]),
        "note_calls": len(CALLS["notes"]),
    }))


if __name__ == "__main__":
    asyncio.run(main())
