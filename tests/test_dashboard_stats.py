import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_dashboard_module():
    fastapi = types.ModuleType("fastapi")

    class APIRouter:
        def __init__(self, *args, **kwargs):
            pass

        def get(self, *args, **kwargs):
            return lambda fn: fn

    fastapi.APIRouter = APIRouter
    sys.modules["fastapi"] = fastapi

    database = types.ModuleType("database")

    async def noop(*args, **kwargs):
        return None

    database.fetchall = noop
    database.fetchrow = noop
    database.execute = noop
    database.fetchval = noop
    database.json_dumps = lambda value: value
    sys.modules["database"] = database

    spec = importlib.util.spec_from_file_location(
        "tested_dashboard",
        ROOT / "api" / "routes" / "dashboard.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DashboardStatsTests(unittest.TestCase):
    def test_dashboard_stats_returns_agent_lifecycle_counts(self):
        module = load_dashboard_module()
        values = iter([531, 356, 67, 71, 26, 195, 39, 13, 13])
        lifecycle_queries = []

        async def fetchval(query, *args):
            return next(values)

        async def fetchrow(query, *args):
            lifecycle_queries.append(query)
            return {
                "active": 1,
                "queued": 0,
                "waiting": 4,
                "stalled": 2,
                "history": 111,
                "open": 5,
            }

        async def fetchall(query, *args):
            if "SELECT status, COUNT(*) AS count FROM agents" in query:
                return [
                    {"status": "working", "count": 1},
                    {"status": "awaiting_access", "count": 4},
                ]
            return []

        module.fetchval = fetchval
        module.fetchrow = fetchrow
        module.fetchall = fetchall

        result = asyncio.run(module.dashboard_stats())

        self.assertEqual(result["agents"]["active"], 1)
        self.assertEqual(result["agents"]["waiting"], 4)
        self.assertEqual(result["agents"]["open"], 5)
        self.assertEqual(result["agents"]["total"], 195)
        self.assertIn("latest_task", lifecycle_queries[0])
        self.assertIn("awaiting_access", lifecycle_queries[0])


if __name__ == "__main__":
    unittest.main()
