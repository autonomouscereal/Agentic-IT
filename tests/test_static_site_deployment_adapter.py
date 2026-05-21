import asyncio
import sys
import tempfile
import types
import unittest
from pathlib import Path
from types import SimpleNamespace

from api.services.static_deployments import publish_static_site


def load_agents_route():
    fastapi = types.ModuleType("fastapi")

    class APIRouter:
        def __init__(self, *args, **kwargs):
            pass

        def get(self, *args, **kwargs):
            return lambda fn: fn

        def post(self, *args, **kwargs):
            return lambda fn: fn

        def put(self, *args, **kwargs):
            return lambda fn: fn

        def delete(self, *args, **kwargs):
            return lambda fn: fn

        def patch(self, *args, **kwargs):
            return lambda fn: fn

        def websocket(self, *args, **kwargs):
            return lambda fn: fn

    class HTTPException(Exception):
        def __init__(self, status_code=None, detail=None):
            self.status_code = status_code
            self.detail = detail
            super().__init__(detail)

    fastapi.APIRouter = APIRouter
    fastapi.Query = lambda default=None, **kwargs: default
    fastapi.WebSocket = object
    fastapi.WebSocketDisconnect = Exception
    fastapi.Body = lambda default=None, **kwargs: default
    fastapi.HTTPException = HTTPException
    fastapi.Request = object
    sys.modules["fastapi"] = fastapi

    database = types.ModuleType("database")
    database.fetchall = None
    database.fetchrow = None
    database.execute = None
    database.fetchval = None
    database.json_dumps = lambda value: __import__("json").dumps(value)
    database.json_loads = lambda value: __import__("json").loads(value) if value else None
    sys.modules["database"] = database

    services = types.ModuleType("services")
    sys.modules["services"] = services

    import api.services.static_deployments as static_deployments
    import api.services.task_prompts as task_prompts
    sys.modules["services.static_deployments"] = static_deployments
    sys.modules["services.task_prompts"] = task_prompts

    event_logger = types.ModuleType("services.event_logger")

    async def log_event(*args, **kwargs):
        return None

    event_logger.log_event = log_event
    sys.modules["services.event_logger"] = event_logger

    import importlib
    return importlib.import_module("api.routes.agents")


class StaticSiteDeploymentAdapterTests(unittest.TestCase):
    def test_publish_static_site_copies_valid_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = root / "agent-work"
            site = work / "hello"
            published = root / "published"
            site.mkdir(parents=True)
            (site / "index.html").write_text("<h1>Hello</h1>", encoding="utf-8")
            (site / "styles.css").write_text("body{font-family:sans-serif}", encoding="utf-8")

            result = publish_static_site(work, "hello", "Hello Site!", published)

            self.assertEqual(result["slug"], "hello-site")
            self.assertEqual(result["file_count"], 2)
            self.assertTrue((published / "hello-site" / "index.html").exists())
            self.assertEqual(result["relative_url"], "/published/hello-site/")

    def test_publish_static_site_rejects_path_escape(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = root / "agent-work"
            work.mkdir()
            outside = root / "outside"
            outside.mkdir()
            (outside / "index.html").write_text("<h1>nope</h1>", encoding="utf-8")

            with self.assertRaises(ValueError):
                publish_static_site(work, "../outside", "escape", root / "published")

    def test_publish_static_site_requires_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            work = root / "agent-work"
            site = work / "hello"
            site.mkdir(parents=True)
            (site / "readme.txt").write_text("missing index", encoding="utf-8")

            with self.assertRaises(ValueError):
                publish_static_site(work, "hello", "hello", root / "published")


class AgentStaticDeployRouteTests(unittest.TestCase):
    def test_agent_static_deploy_requires_approved_gate_and_completes_it(self):
        agents_route = load_agents_route()
        calls = []
        original_fetchrow = agents_route.fetchrow
        original_fetchval = agents_route.fetchval
        original_execute = agents_route.execute
        original_log_event = agents_route.log_event
        original_publish = agents_route.publish_static_site

        async def fake_fetchrow(query, *args):
            if "FROM agents" in query:
                return {"id": 5, "ticket_id": 99}
            if "FROM agent_tasks" in query:
                return {"id": 7, "work_dir": "/app/agent_work/5"}
            if "FROM change_requests" in query:
                return {"id": 11, "agent_id": 5, "ticket_id": 99, "status": "approved"}
            return None

        async def fake_fetchval(query, *args):
            calls.append(("fetchval", query, args))
            return 123

        async def fake_execute(query, *args):
            calls.append(("execute", query, args))
            return None

        async def fake_log_event(*args, **kwargs):
            calls.append(("log_event", args, kwargs))

        def fake_publish(work_dir, source_dir, slug):
            self.assertEqual(work_dir, "/app/agent_work/5")
            self.assertEqual(source_dir, "hello")
            return {
                "slug": "hello",
                "source_dir": "/app/agent_work/5/hello",
                "target_dir": "/app/data/published_sites/hello",
                "relative_url": "/published/hello/",
                "file_count": 3,
                "total_bytes": 2048,
            }

        try:
            agents_route.fetchrow = fake_fetchrow
            agents_route.fetchval = fake_fetchval
            agents_route.execute = fake_execute
            agents_route.log_event = fake_log_event
            agents_route.publish_static_site = fake_publish

            result = asyncio.run(agents_route.deploy_static_site(
                5,
                {"change_id": 11, "source_dir": "hello", "slug": "hello"},
                SimpleNamespace(base_url="https://ops.example.local/"),
            ))
        finally:
            agents_route.fetchrow = original_fetchrow
            agents_route.fetchval = original_fetchval
            agents_route.execute = original_execute
            agents_route.log_event = original_log_event
            agents_route.publish_static_site = original_publish

        self.assertEqual(result["status"], "deployed")
        self.assertEqual(result["deployment"]["public_url"], "https://ops.example.local/published/hello/")
        self.assertTrue(any(
            call[0] == "execute"
            and "UPDATE change_requests SET status = 'completed'" in call[1]
            for call in calls
        ))
        self.assertTrue(any(
            call[0] == "execute"
            and "static_site_deployed" in call[1]
            for call in calls
        ))


if __name__ == "__main__":
    unittest.main()
