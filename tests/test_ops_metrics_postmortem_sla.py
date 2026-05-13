import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_dashboard_route(calls):
    fastapi = types.ModuleType("fastapi")

    class APIRouter:
        def __init__(self, *args, **kwargs):
            pass

        def get(self, *args, **kwargs):
            return lambda func: func

        def post(self, *args, **kwargs):
            return lambda func: func

    fastapi.APIRouter = APIRouter
    sys.modules["fastapi"] = fastapi

    database = types.ModuleType("database")

    async def fetchall(query, *args):
        calls.append(("fetchall", query))
        return []

    async def fetchrow(query, *args):
        calls.append(("fetchrow", query))
        if "FROM postmortem_sla" in query:
            return {
                "tickets_requiring_postmortem": 3,
                "tickets_with_postmortem": 2,
                "within_sla": 2,
                "total_postmortems": 7,
                "missing_postmortem": 1,
                "breached_sla": 0,
                "at_risk": 1,
                "avg_postmortem_latency_seconds": 120.0,
                "compliance_pct": 66.7,
                "target_hours": 24,
            }
        return {}

    async def fetchval(*args, **kwargs):
        return 0

    async def execute(*args, **kwargs):
        return None

    database.fetchall = fetchall
    database.fetchrow = fetchrow
    database.fetchval = fetchval
    database.execute = execute
    database.json_dumps = lambda value: value
    sys.modules["database"] = database

    spec = importlib.util.spec_from_file_location(
        "tested_dashboard_route",
        ROOT / "api" / "routes" / "dashboard.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class OpsMetricsPostmortemSlaTests(unittest.TestCase):
    def test_ops_metrics_includes_postmortem_sla_from_resolved_ticket_artifacts(self):
        calls = []
        module = load_dashboard_route(calls)

        result = asyncio.run(module.ops_metrics())

        self.assertIn("postmortem_sla", result)
        self.assertEqual(result["postmortem_sla"]["tickets_requiring_postmortem"], 3)
        self.assertEqual(result["postmortem_sla"]["total_postmortems"], 7)
        self.assertEqual(result["postmortem_sla"]["missing_postmortem"], 1)
        queries = "\n".join(query for _, query in calls)
        self.assertIn("first_postmortem", queries)
        self.assertIn("FROM postmortems", queries)
        self.assertIn("task_type = 'ticket_resolution'", queries)


if __name__ == "__main__":
    unittest.main()
