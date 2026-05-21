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

    def test_approval_actor_prefers_authenticated_ui_identity(self):
        module = load_changes_module()

        request = types.SimpleNamespace(
            state=types.SimpleNamespace(
                access_decision={
                    "identity": {
                        "username": "demo_account_1",
                        "auth_mode": "signed-session",
                    }
                }
            )
        )

        actor = module._approval_actor_from_request(
            request,
            {"approved_by": "spoofed-ui-body"},
            "approved_by",
            default="dashboard",
        )

        self.assertEqual(actor, "demo_account_1")

    def test_approval_actor_allows_service_token_named_automation(self):
        module = load_changes_module()

        request = types.SimpleNamespace(
            state=types.SimpleNamespace(
                access_decision={
                    "identity": {
                        "username": "complex-proof-runner",
                        "auth_mode": "service-token",
                    }
                }
            )
        )

        actor = module._approval_actor_from_request(
            request,
            {"approved_by": "complex-access-approver"},
            "approved_by",
            default="dashboard",
        )

        self.assertEqual(actor, "complex-access-approver")

    def test_demo_account_manual_approval_is_not_auto_approval(self):
        module = load_changes_module()

        self.assertFalse(module._is_auto_approver("demo_account_1"))
        self.assertFalse(module._is_auto_approver("demo-operator"))
        self.assertTrue(module._is_auto_approver("report-phish-demo-auto-approver"))
        self.assertTrue(module._is_auto_approver("regression-auto-approver"))

    def test_change_completion_returns_access_sync_evidence(self):
        module = load_changes_module()
        sync_calls = []

        async def fetchrow(query, *args):
            return {
                "id": 146,
                "agent_id": 172,
                "ticket_id": 486,
                "action": "Grant least-privilege account access",
                "target": "iTop ticket team-z/incident-999",
            }

        async def execute(*args):
            return None

        async def log_event(*args, **kwargs):
            return None

        async def add_gate_note(*args, **kwargs):
            return 99

        async def sync_access(change, status, actor, evidence=None):
            sync_calls.append((change, status, actor, evidence))
            return {
                "status": "granted",
                "access_request_id": 6,
                "granted_leases": [{"status": "granted", "agent_id": 172}],
            }

        module.fetchrow = fetchrow
        module.execute = execute
        module.log_event = log_event
        module._add_gate_note = add_gate_note
        module._sync_access_request_status = sync_access

        result = asyncio.run(module.complete_change(146, {
            "completed_by": "agent_172",
            "result": "lease grant proof",
        }))

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["access_sync"]["status"], "granted")
        self.assertEqual(result["access_sync"]["granted_leases"][0]["agent_id"], 172)
        self.assertEqual(sync_calls[0][1:], ("completed", "agent_172", "lease grant proof"))

    def test_completed_access_request_infers_missing_wazuh_lease_request(self):
        module = load_changes_module()
        grants = []
        events = []

        async def fetchrow(query, *args):
            if "UPDATE access_requests" in query:
                return {
                    "id": 14,
                    "parent_ticket_id": 533,
                    "access_ticket_id": None,
                    "agent_id": 197,
                    "change_id": 157,
                    "resource": "wazuh.manager API",
                    "permission": "read",
                    "account_ref": "wazuh.manager",
                    "status": "granted",
                }
            self.fail(f"unexpected query: {query}")

        async def add_gate_note(*args, **kwargs):
            return 901

        async def log_event(*args, **kwargs):
            events.append(args)

        async def grant_agent_vault_lease(agent_id, lease_request, granted_by="access-gate", evidence=None):
            grants.append({
                "agent_id": agent_id,
                "lease_request": lease_request,
                "granted_by": granted_by,
                "evidence": evidence,
            })
            return {"status": "granted", "agent_id": agent_id, **lease_request}

        module.fetchrow = fetchrow
        module._add_gate_note = add_gate_note
        module.log_event = log_event
        module.infer_lease_request = lambda resource, permission, account_ref: {
            "system": "wazuh",
            "resource_type": "api",
            "resource_id": "wazuh.manager",
            "action": "read",
        }
        module.access_control.grant_agent_vault_lease = grant_agent_vault_lease

        result = asyncio.run(module._sync_access_request_status({
            "id": 157,
            "approval_policy": {"access_request": True},
        }, "completed", "agent_197", "Wazuh read grant approved."))

        self.assertEqual(result["status"], "granted")
        self.assertEqual(result["granted_leases"][0]["system"], "wazuh")
        self.assertEqual(grants[0]["agent_id"], 197)
        self.assertEqual(grants[0]["lease_request"]["resource_id"], "wazuh.manager")
        self.assertTrue(any(event[3] == "access_request_lease_inferred_on_completion" for event in events))

    def test_resume_skips_when_ticket_already_has_active_agent(self):
        module = load_changes_module()
        calls = []
        handoffs = []

        async def fetchrow(query, *args):
            calls.append((query, args))
            if "FROM agent_tasks" in query and "WHERE agent_id" in query:
                return None
            if "FROM agents a" in query:
                return {"id": 85, "status": "working", "last_task_id": 83}
            if "SELECT error_message, last_task_id FROM agents" in query:
                return {"error_message": "waiting at gate", "last_task_id": 81}
            self.fail(f"unexpected query after active ticket agent guard: {query}")

        async def record_handoff(change, source_agent, result, approved_by):
            handoffs.append((change, source_agent, result, approved_by))
            return {"status": "recorded", "replacement_agent_id": result["agent_id"]}

        module.fetchrow = fetchrow
        module._record_resume_handoff = record_handoff

        result = asyncio.run(module._resume_agent_after_approval({
            "id": 84,
            "agent_id": 81,
            "ticket_id": 312,
        }, "unit-approver"))

        self.assertEqual(result["status"], "already_active_ticket")
        self.assertEqual(result["agent_id"], 85)
        self.assertEqual(result["task_id"], 83)
        self.assertEqual(result["handoff"]["status"], "recorded")
        self.assertEqual(handoffs[0][1]["last_task_id"], 81)
        self.assertTrue(any("FROM agents a" in query for query, _ in calls))

    def test_resume_delivers_approval_update_to_already_running_agent(self):
        module = load_changes_module()
        steering_calls = []
        events = []

        async def fetchrow(query, *args):
            if "FROM agent_tasks" in query and "WHERE agent_id" in query:
                return {"id": 194, "status": "running", "work_dir": "/app/agent_work/197"}
            self.fail(f"unexpected query after active task guard: {query}")

        async def record_ticket_note(ticket_id, note_id, body, author="dashboard", source="dashboard", visibility="internal", external_ref=None):
            steering_calls.append({
                "ticket_id": ticket_id,
                "note_id": note_id,
                "body": body,
                "author": author,
                "source": source,
            })
            return {"status": "created", "events": [{"agent_id": 197, "task_id": 194}]}

        async def log_event(*args, **kwargs):
            events.append((args, kwargs))

        agent_steering = types.ModuleType("services.agent_steering")
        agent_steering.record_ticket_note = record_ticket_note
        sys.modules["services"].agent_steering = agent_steering
        sys.modules["services.agent_steering"] = agent_steering
        module.fetchrow = fetchrow
        module.log_event = log_event

        result = asyncio.run(module._resume_agent_after_approval({
            "id": 157,
            "agent_id": 197,
            "ticket_id": 533,
            "action": "Grant least-privilege account access",
            "target": "wazuh.manager API",
        }, "dashboard"))

        self.assertEqual(result["status"], "already_active")
        self.assertEqual(result["task_id"], 194)
        self.assertEqual(result["steering"]["status"], "created")
        self.assertEqual(steering_calls[0]["source"], "dashboard")
        self.assertIn("already running", steering_calls[0]["body"])
        self.assertTrue(any(call[0][3] == "approval_update_delivered_to_active_agent" for call in events))

    def test_approve_is_idempotent_and_resumes_after_active_agent_later_blocks(self):
        module = load_changes_module()

        async def fetchrow(query, *args):
            return {
                "id": 156,
                "agent_id": 195,
                "ticket_id": 531,
                "action": "lab-safe phishing and EDR containment",
                "target": "finance host",
                "status": "approved",
            }

        async def resume(change, approved_by):
            return {
                "status": "resumed",
                "agent_id": 196,
                "task_id": 193,
                "approved_by": approved_by,
                "change_id": change["id"],
            }

        module.fetchrow = fetchrow
        module._resume_agent_after_approval = resume

        result = asyncio.run(module.approve_change(156, {
            "approved_by": "unit-approver",
        }))

        self.assertEqual(result["status"], "approved")
        self.assertTrue(result["already_approved"])
        self.assertEqual(result["resume"]["status"], "resumed")
        self.assertEqual(result["resume"]["task_id"], 193)

    def test_resume_records_ticket_handoff_and_marks_source_agent(self):
        module = load_changes_module()
        queries = []
        updates = []
        notes = []
        spawns = []

        async def fetchrow(query, *args):
            queries.append((query, args))
            if "FROM agent_tasks" in query and "status IN ('queued', 'running')" in query:
                return None
            if "FROM agents a" in query:
                return None
            if "SELECT model, selected_model, error_message, last_task_id FROM agents" in query:
                return {
                    "model": "qwen/qwen3.6-27b",
                    "selected_model": "qwen/qwen3.6-27b",
                    "error_message": "COMPLEX_CONTAINMENT_GATE marker",
                    "last_task_id": 192,
                }
            if "SELECT prompt, task_type FROM agent_tasks" in query:
                return {
                    "prompt": "Original ticket objective.",
                    "task_type": "ticket_resolution",
                }
            self.fail(f"unexpected query: {query}")

        async def execute(query, *args):
            updates.append((query, args))
            return None

        async def add_gate_note(ticket_id, change_id, title, body, actor="approval-gate", source="approval-gate"):
            notes.append({
                "ticket_id": ticket_id,
                "change_id": change_id,
                "title": title,
                "body": body,
                "actor": actor,
                "source": source,
            })
            return 812

        async def log_event(*args, **kwargs):
            return None

        async def load_agent_subject(agent_id):
            return {"identity": {"username": "dev-y"}, "capabilities": ["tickets:read"]}

        async def spawn_agent(ticket_id, model, prompt, task_type, actor_context=None):
            spawns.append({
                "ticket_id": ticket_id,
                "model": model,
                "prompt": prompt,
                "task_type": task_type,
                "actor_context": actor_context,
            })
            return {"agent_id": 196, "task_id": 193}

        agent_runner = types.ModuleType("services.agent_runner")
        agent_runner.spawn_agent = spawn_agent
        sys.modules["services.agent_runner"] = agent_runner
        setattr(sys.modules["services"], "agent_runner", agent_runner)

        module.fetchrow = fetchrow
        module.execute = execute
        module._add_gate_note = add_gate_note
        module.log_event = log_event
        module.access_control.load_agent_subject = load_agent_subject

        result = asyncio.run(module._resume_agent_after_approval({
            "id": 156,
            "agent_id": 195,
            "ticket_id": 531,
        }, "unit-approver"))

        self.assertEqual(result["status"], "resumed")
        self.assertEqual(result["agent_id"], 196)
        self.assertEqual(result["handoff"]["status"], "recorded")
        self.assertEqual(notes[0]["source"], "agent-lifecycle")
        self.assertIn("195 -> 196", notes[0]["title"])
        self.assertIn("should not be expected to keep running indefinitely", notes[0]["body"])
        self.assertTrue(any("UPDATE agents" in query and "status = 'finished'" in query and "continuation agent 196" in args[0] for query, args in updates))
        self.assertTrue(any("UPDATE agent_tasks" in query and "status = 'completed'" in query and args[1] == 192 for query, args in updates))
        self.assertIn("Approval update", spawns[0]["prompt"])


if __name__ == "__main__":
    unittest.main()
