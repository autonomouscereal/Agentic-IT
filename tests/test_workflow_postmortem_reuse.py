import asyncio
import importlib.util
import json
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def install_fastapi_stub():
    fastapi = types.ModuleType("fastapi")

    class APIRouter:
        def __init__(self, *args, **kwargs):
            pass

        def get(self, *args, **kwargs):
            return lambda func: func

        def post(self, *args, **kwargs):
            return lambda func: func

        def put(self, *args, **kwargs):
            return lambda func: func

    fastapi.APIRouter = APIRouter
    fastapi.Body = lambda default=None, *args, **kwargs: default
    fastapi.Query = lambda default=None, *args, **kwargs: default
    sys.modules["fastapi"] = fastapi


def install_common_stubs():
    install_fastapi_stub()

    database = types.ModuleType("database")
    database.fetchall = lambda *args, **kwargs: None
    database.fetchrow = lambda *args, **kwargs: None
    database.fetchval = lambda *args, **kwargs: None
    database.execute = lambda *args, **kwargs: None
    database.json_dumps = lambda value: json.dumps(value)
    sys.modules["database"] = database

    services = types.ModuleType("services")
    sys.modules["services"] = services

    event_logger = types.ModuleType("services.event_logger")

    async def log_event(*args, **kwargs):
        return None

    event_logger.log_event = log_event
    sys.modules["services.event_logger"] = event_logger

    workflow_keys_spec = importlib.util.spec_from_file_location(
        "services.workflow_keys",
        ROOT / "api" / "services" / "workflow_keys.py",
    )
    workflow_keys = importlib.util.module_from_spec(workflow_keys_spec)
    workflow_keys_spec.loader.exec_module(workflow_keys)
    sys.modules["services.workflow_keys"] = workflow_keys


def load_workflows_route():
    install_common_stubs()
    spec = importlib.util.spec_from_file_location(
        "tested_workflows_route",
        ROOT / "api" / "routes" / "workflows.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_postmortems_route():
    install_common_stubs()
    synthesizer = types.ModuleType("services.postmortem_synthesizer")
    synthesizer.synthesize_postmortem = lambda *args, **kwargs: {}
    sys.modules["services.postmortem_synthesizer"] = synthesizer

    ticket_service = types.ModuleType("services.ticket_service")
    ticket_service.compact_ticket_payload = lambda ticket: ticket
    sys.modules["services.ticket_service"] = ticket_service

    spec = importlib.util.spec_from_file_location(
        "tested_postmortems_route_reuse",
        ROOT / "api" / "routes" / "postmortems.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class WorkflowReuseTests(unittest.IsolatedAsyncioTestCase):
    async def test_post_workflow_updates_existing_key_even_when_name_differs(self):
        module = load_workflows_route()
        calls = []

        async def fetchrow(query, *params):
            calls.append(("fetchrow", query, params))
            if "WHERE workflow_key = $1" in query:
                return {"id": 77, "name": "Existing phishing procedure"}
            return None

        async def fetchval(query, *params):
            calls.append(("fetchval", query, params))
            return 77

        module.fetchrow = fetchrow
        module.fetchval = fetchval

        result = await module.create_workflow(
            name="Ticket 531 credential harvest",
            blueprint="Triage phishing headers, check URL reputation, and request URL block approval.",
            description="Credential harvest phishing workflow",
            ticket_class="Incident",
            trigger_type="manual",
            status="active",
            created_by="unit-test",
        )

        self.assertEqual(result["id"], 77)
        self.assertEqual(result["action"], "updated")
        self.assertEqual(result["workflow_key"], "incident:phishing")
        update_call = [call for call in calls if call[0] == "fetchval"][0]
        self.assertIn("UPDATE agent_workflows", update_call[1])
        self.assertIn("ready_for_review", update_call[2])
        self.assertIn("incident:phishing", update_call[2])

    async def test_explicit_policy_workflow_key_is_preserved(self):
        module = load_workflows_route()
        captured = {}

        async def fetchrow(query, *params):
            return None

        async def fetchval(query, *params):
            captured["params"] = params
            return 88

        module.fetchrow = fetchrow
        module.fetchval = fetchval

        result = await module.create_workflow(
            name="Custom access workflow",
            blueprint="Use provider-specific account access request gates.",
            description="custom",
            approval_policy={"workflow_key": "request:access-custom"},
            created_by="unit-test",
        )

        self.assertEqual(result["workflow_key"], "request:access-custom")
        self.assertIn("request:access-custom", captured["params"])

    async def test_review_supersedes_active_siblings_before_activation(self):
        module = load_workflows_route()
        calls = []

        async def fetchrow(query, *params):
            if "SELECT id, workflow_key FROM agent_workflows" in query:
                return {"id": 22, "workflow_key": "incident:phishing"}
            return None

        async def fetchall(query, *params):
            calls.append(("fetchall", query, params))
            if "WHERE workflow_key = $1" in query:
                return [{"id": 11}, {"id": 12}]
            return []

        async def execute(query, *params):
            calls.append(("execute", query, params))
            return None

        module.fetchrow = fetchrow
        module.fetchall = fetchall
        module.execute = execute

        result = await module.review_workflow(
            22,
            reviewed_by="unit-test",
            approved=True,
            review_notes="approve canonical phishing workflow",
        )

        self.assertEqual(result["status"], "active")
        self.assertEqual(result["superseded_workflow_ids"], [11, 12])
        supersede_call = [call for call in calls if "status = 'superseded'" in call[1]][0]
        self.assertEqual(supersede_call[2][0], [11, 12])
        self.assertEqual(supersede_call[2][1], "22")
        review_call = [call for call in calls if "UPDATE agent_workflows" in call[1] and "reviewed_at" in call[1]][0]
        self.assertEqual(review_call[2][0], "active")

    async def test_active_workflow_key_change_is_regated_for_review(self):
        module = load_workflows_route()
        update_params = {}

        async def fetchrow(query, *params):
            if "SELECT * FROM agent_workflows" in query:
                return {
                    "id": 31,
                    "name": "Current canonical workflow",
                    "description": "Current",
                    "ticket_class": "Incident",
                    "trigger_type": "manual",
                    "status": "active",
                    "blueprint": "Current blueprint",
                    "approval_policy": {"workflow_key": "incident:old"},
                    "workflow_key": "incident:old",
                }
            return None

        async def execute(query, *params):
            update_params["query"] = query
            update_params["params"] = params
            return None

        module.fetchrow = fetchrow
        module.execute = execute

        result = await module.update_workflow(
            31,
            approval_policy={"workflow_key": "incident:new"},
        )

        self.assertEqual(result["status"], "updated")
        self.assertIn("status =", update_params["query"])
        self.assertIn("ready_for_review", update_params["params"])
        self.assertIn("incident:new", update_params["params"])


class PostmortemPromotionReuseTests(unittest.IsolatedAsyncioTestCase):
    async def test_promote_updates_existing_workflow_by_key(self):
        module = load_postmortems_route()
        fetchval_queries = []
        executed = []

        postmortem = {
            "id": 501,
            "ticket_id": 531,
            "summary": "Credential phishing email was triaged and URL blocking needed approval.",
            "improvements": "Reuse phishing triage workflow and document approval gates.",
            "workflow_proposal": "Triage phishing headers, verify URL reputation, request URL block approval, then close with evidence.",
            "skill_proposals": [],
            "test_cases": [{"name": "phish with blocked URL", "expected": "approval gate then completion"}],
            "guardrails": [{"name": "no blanket blocking", "approval": "required"}],
        }
        ticket = {
            "id": 531,
            "title": "Reported phishing email with credential harvest URL",
            "provider_class": "Incident",
        }
        existing = {
            "id": 19,
            "name": "Canonical phishing response",
            "description": "Existing phishing workflow",
            "ticket_class": "Incident",
            "status": "draft",
            "reviewed_at": "2026-05-13T15:15:29Z",
            "blueprint": "Original phishing triage.",
            "test_plan": "Original tests.",
            "test_results": "Original evidence.",
            "approval_policy": {"workflow_key": "incident:phishing", "guardrails": [{"name": "old"}]},
            "skill_ids": [3],
        }

        async def fetchrow(query, *params):
            if "FROM postmortems" in query:
                return postmortem
            if "FROM tickets" in query:
                return ticket
            if "FROM agent_workflows" in query:
                return existing
            if "FROM knowledge_articles" in query:
                return None
            return None

        async def fetchall(query, *params):
            return []

        async def fetchval(query, *params):
            fetchval_queries.append((query, params))
            if "UPDATE agent_workflows" in query:
                return existing["id"]
            if "INSERT INTO knowledge_articles" in query:
                return 44
            return 999

        async def execute(query, *params):
            executed.append((query, params))
            return None

        module.fetchrow = fetchrow
        module.fetchall = fetchall
        module.fetchval = fetchval
        module.execute = execute

        result = await module.promote_postmortem(501, create_skills=False, created_by="unit-test")

        self.assertEqual(result["workflow_id"], 19)
        self.assertEqual(result["workflow_action"], "updated")
        self.assertEqual(result["workflow_key"], "incident:phishing")
        workflow_update = [call for call in fetchval_queries if "UPDATE agent_workflows" in call[0]][0]
        self.assertIn("active", workflow_update[1])
        self.assertTrue(any("Postmortem 501 workflow lesson" in str(param) for param in workflow_update[1]))
        article_insert = [call for call in fetchval_queries if "INSERT INTO knowledge_articles" in call[0]][0]
        self.assertIn("workflow:incident:phishing:knowledge", article_insert[1])
        audit_insert = [call for call in executed if "INSERT INTO audit_log" in call[0]][0]
        self.assertIn("incident:phishing", audit_insert[1][3])

    async def test_postmortem_lookup_falls_back_to_workflow_key(self):
        module = load_postmortems_route()
        postmortem = {
            "id": 502,
            "ticket_id": 532,
            "summary": "Sysmon EDR persistence alert investigated.",
            "improvements": "Reuse EDR workflow.",
            "workflow_proposal": "Collect process tree, validate parent process, request isolation only after approval.",
            "test_cases": [],
            "guardrails": [],
        }
        ticket = {
            "id": 532,
            "title": "Sysmon persistence alert",
            "provider_class": "Incident",
        }
        workflow = {
            "id": 55,
            "name": "Canonical EDR triage",
            "status": "tested",
            "version": 4,
            "workflow_key": "incident:edr-sysmon",
        }

        async def fetchrow(query, *params):
            if "FROM postmortems" in query:
                return postmortem
            if "FROM tickets" in query:
                return ticket
            if "FROM audit_log" in query:
                return None
            if "FROM agent_workflows" in query:
                self.assertEqual(params[0], "incident:edr-sysmon")
                return workflow
            return None

        async def fetchall(query, *params):
            return []

        module.fetchrow = fetchrow
        module.fetchall = fetchall

        result = await module.get_postmortem(502)

        self.assertEqual(result["promotion_assets"]["workflow"]["id"], 55)
        self.assertEqual(result["promotion_assets"]["workflow_key"], "incident:edr-sysmon")


if __name__ == "__main__":
    unittest.main()
