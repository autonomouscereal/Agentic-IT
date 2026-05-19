import asyncio
import importlib.util
import subprocess
import sys
import tempfile
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

        def put(self, *args, **kwargs):
            return lambda fn: fn

        def patch(self, *args, **kwargs):
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


class TransientModelRetryTests(unittest.TestCase):
    def test_detects_hermes_provider_capacity_errors(self):
        module = load_agent_runner()
        self.assertTrue(module._is_transient_model_capacity_error(
            "API call failed after 3 retries: HTTP 503: The requested model is temporarily unavailable due to upstream capacity limits."
        ))
        self.assertTrue(module._is_transient_model_capacity_error("HTTP 429 rate limit exceeded"))
        self.assertTrue(module._is_transient_model_capacity_error("provider overloaded"))

    def test_does_not_retry_prompt_or_permission_errors(self):
        module = load_agent_runner()
        self.assertFalse(module._is_transient_model_capacity_error("curl returned HTTP 403 missing_agent_vault_lease"))
        self.assertFalse(module._is_transient_model_capacity_error("agent wrote checkpoint waiting_for_access"))


def load_tickets_route():
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

        def patch(self, *args, **kwargs):
            return lambda fn: fn

    class HTTPException(Exception):
        def __init__(self, status_code=None, detail=None):
            self.status_code = status_code
            self.detail = detail
            super().__init__(detail)

    fastapi.APIRouter = APIRouter
    fastapi.Query = lambda default=None, **kwargs: default
    fastapi.Body = lambda default=None, **kwargs: default
    fastapi.HTTPException = HTTPException
    sys.modules["fastapi"] = fastapi

    database = types.ModuleType("database")
    database.fetchall = None
    database.fetchrow = None
    database.execute = None
    database.fetchval = None
    database.json_dumps = lambda value: value
    sys.modules["database"] = database

    services = types.ModuleType("services")
    services.provider_registry = types.SimpleNamespace()
    services.ticket_service = types.SimpleNamespace()
    sys.modules["services"] = services
    sys.modules["services.provider_registry"] = services.provider_registry

    ticket_service = types.ModuleType("services.ticket_service")
    ticket_service.compact_ticket_payload = lambda value: value
    sys.modules["services.ticket_service"] = ticket_service
    services.ticket_service = ticket_service

    ticket_links = types.ModuleType("services.ticket_links")
    ticket_links.external_ticket_url = lambda row: None
    sys.modules["services.ticket_links"] = ticket_links

    task_prompts = types.ModuleType("services.task_prompts")
    task_prompts.build_ticket_resolution_prompt = lambda ticket, extra_prompt=None: "ticket prompt"
    task_prompts.build_postmortem_prompt = lambda ticket, context=None: "postmortem prompt"
    task_prompts.build_workflow_prompt = lambda ticket, context=None: "workflow prompt"
    sys.modules["services.task_prompts"] = task_prompts

    event_logger = types.ModuleType("services.event_logger")

    async def log_event(*args, **kwargs):
        return None

    event_logger.log_event = log_event
    sys.modules["services.event_logger"] = event_logger

    spec = importlib.util.spec_from_file_location(
        "tested_tickets_route",
        ROOT / "api" / "routes" / "tickets.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_auto_assignment_service():
    database = types.ModuleType("database")
    database.fetchall = None
    database.fetchrow = None
    database.execute = None
    sys.modules["database"] = database

    services = types.ModuleType("services")
    sys.modules["services"] = services

    event_logger = types.ModuleType("services.event_logger")

    async def log_event(*args, **kwargs):
        return None

    event_logger.log_event = log_event
    sys.modules["services.event_logger"] = event_logger

    task_prompts = types.ModuleType("services.task_prompts")
    task_prompts.build_auto_assignment_prompt = lambda ticket, extra_prompt=None: "auto prompt"
    sys.modules["services.task_prompts"] = task_prompts

    spec = importlib.util.spec_from_file_location(
        "tested_auto_assignment",
        ROOT / "api" / "services" / "auto_assignment.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_postmortems_route():
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

    fastapi.APIRouter = APIRouter
    fastapi.Body = lambda default=None, **kwargs: default
    fastapi.Query = lambda default=None, **kwargs: default
    sys.modules["fastapi"] = fastapi

    database = types.ModuleType("database")
    database.fetchall = None
    database.fetchrow = None
    database.execute = None
    database.fetchval = None
    database.json_dumps = lambda value: value if isinstance(value, str) else __import__("json").dumps(value)
    sys.modules["database"] = database

    services = types.ModuleType("services")
    sys.modules["services"] = services

    event_logger = types.ModuleType("services.event_logger")

    async def log_event(*args, **kwargs):
        return None

    event_logger.log_event = log_event
    sys.modules["services.event_logger"] = event_logger

    synthesizer = types.ModuleType("services.postmortem_synthesizer")
    synthesizer.synthesize_postmortem = None
    sys.modules["services.postmortem_synthesizer"] = synthesizer

    ticket_service = types.ModuleType("services.ticket_service")
    ticket_service.compact_ticket_payload = lambda value: value
    sys.modules["services.ticket_service"] = ticket_service

    workflow_keys_spec = importlib.util.spec_from_file_location(
        "services.workflow_keys",
        ROOT / "api" / "services" / "workflow_keys.py",
    )
    workflow_keys = importlib.util.module_from_spec(workflow_keys_spec)
    workflow_keys_spec.loader.exec_module(workflow_keys)
    sys.modules["services.workflow_keys"] = workflow_keys

    spec = importlib.util.spec_from_file_location(
        "tested_postmortems_route",
        ROOT / "api" / "routes" / "postmortems.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AgentLifecycleGuardTests(unittest.TestCase):
    def test_blocking_checkpoint_watcher_terminates_owned_process(self):
        module = load_agent_runner()

        class FakeProcess:
            def __init__(self):
                self.returncode = None
                self.terminated = False
                self.killed = False

            def terminate(self):
                self.terminated = True
                self.returncode = -15

            def kill(self):
                self.killed = True
                self.returncode = -9

        process = FakeProcess()
        activity = {"last_output_at": 1}
        state = {}
        with tempfile.TemporaryDirectory() as tmpdir:
            checkpoint_path = Path(tmpdir) / "checkpoint.json"
            checkpoint_path.write_text(
                (
                    '{"step":"waiting-for-vault-access-unit",'
                    '"status":"waiting_for_access",'
                    '"output":"waiting for approved lease",'
                    '"progress_pct":45}'
                ),
                encoding="utf-8",
            )

            asyncio.run(
                module._terminate_after_blocking_checkpoint(
                    process,
                    tmpdir,
                    activity,
                    state,
                    poll_seconds=0.01,
                    grace_seconds=1,
                )
            )

        self.assertTrue(process.terminated)
        self.assertFalse(process.killed)
        self.assertEqual(state["checkpoint"]["status"], "waiting_for_access")
        self.assertIn("durable wait checkpoint", state["reason"])

    def test_process_snapshot_includes_db_pid_matches(self):
        module = load_agent_runner()

        class Completed:
            returncode = 0
            stdout = (
                "    PID    PPID STAT     ELAPSED COMMAND         COMMAND\n"
                "    265     258 Sl         01:48 claude          claude --model qwen/qwen3.6-27b\n"
            )

        async def fetchall(query, *args):
            self.assertIn("FROM agent_tasks", query)
            return [
                {"id": 185, "pid": 265},
                {"id": 186, "pid": 999999},
            ]

        original_which = module.shutil.which
        original_run = module.subprocess.run
        try:
            module.shutil.which = lambda name: "/usr/bin/ps"
            module.subprocess.run = lambda *args, **kwargs: Completed()
            module.fetchall = fetchall
            module._active_processes = {184: object()}

            result = asyncio.run(module.get_process_snapshot())

            self.assertEqual(result["active_processes"], [184, 185])
            self.assertEqual(len(result["processes"]), 1)
        finally:
            module.shutil.which = original_which
            module.subprocess.run = original_run

    def test_provider_close_retries_transient_itop_invalid_stimulus(self):
        module = load_agent_runner()
        calls = []
        notes = []
        events = []

        async def fetchrow(query, *args):
            return {"provider": "itop", "provider_ref": "244", "status": "resolved"}

        async def sleep(seconds):
            calls.append(("sleep", seconds))

        async def add_agent_note(*args, **kwargs):
            notes.append((args, kwargs))

        async def log_event(*args, **kwargs):
            events.append((args, kwargs))

        class Provider:
            async def close_ticket(self, ticket_id, note_text):
                calls.append(("close", ticket_id, note_text))
                close_count = len([item for item in calls if item[0] == "close"])
                if close_count == 1:
                    return {"error": "Invalid stimulus: 'ev_resolve' on the object I-000253 in state 'new'"}
                return {"status": "resolved"}

        itop_sync = types.ModuleType("services.itop_sync")
        itop_sync.iTopProvider = Provider
        sys.modules["services.itop_sync"] = itop_sync

        module.fetchrow = fetchrow
        module.asyncio.sleep = sleep
        module._add_agent_note = add_agent_note
        module.log_event = log_event

        result = asyncio.run(module._close_provider_ticket_if_needed(372, 134, 131, "done"))

        self.assertEqual(result["status"], "resolved")
        self.assertEqual([item[0] for item in calls], ["close", "sleep", "close"])
        self.assertEqual(notes, [])
        self.assertEqual(events[0][0][3], "provider_close_complete")

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

    def test_direct_spawn_checks_ticket_row_scope_before_runner(self):
        module = load_agents_route()

        async def fetchrow(query, *args):
            if "SELECT * FROM tickets" in query:
                return {
                    "id": 412,
                    "title": "hidden restricted ticket",
                    "description": "not visible",
                    "itop_class": "Incident",
                    "owning_group": "Dev Team Z",
                    "security_classification": "restricted",
                }
            return None

        async def fail_spawn(*args, **kwargs):
            raise AssertionError("runner must not be called when ticket scope denies spawn")

        module.fetchrow = fetchrow
        sys.modules["services"].agent_runner.spawn_agent = fail_spawn
        module.access_control = types.SimpleNamespace(
            subject_from_request=lambda request: {
                "identity": {"username": "dev-y"},
                "roles": ["analyst", "agent-operator"],
                "capabilities": ["agents:spawn", "tickets:read"],
                "scopes": [{"scope_type": "group", "scope_value": "Dev Team Y"}],
                "max_classification": "confidential",
            },
            ticket_access_decision=lambda ticket, subject, required_permission="tickets:read": {
                "allow": False,
                "reason": "ticket_outside_subject_scope",
            },
        )

        with self.assertRaises(module.HTTPException) as raised:
            asyncio.run(module.spawn_agent(412, prompt="should not spawn"))

        self.assertEqual(raised.exception.status_code, 403)
        self.assertEqual(raised.exception.detail["reason"], "ticket_outside_subject_scope")

    def test_ticket_assign_agent_forwards_requested_permissions(self):
        module = load_tickets_route()
        captured = {}

        async def fetchrow(query, *args):
            if "SELECT * FROM tickets" in query:
                return {
                    "id": 413,
                    "title": "visible ticket",
                    "description": "visible",
                    "itop_class": "Incident",
                    "owning_group": "Dev Team Y",
                    "security_classification": "confidential",
                }
            if "SELECT id, status FROM agents" in query:
                return None
            return None

        async def spawn_agent(ticket_id, model, prompt, task_type="ticket_resolution", actor_context=None, requested_permissions=None):
            captured["ticket_id"] = ticket_id
            captured["requested_permissions"] = requested_permissions
            captured["actor_context"] = actor_context
            return {"agent_id": 99, "task_id": 100}

        async def log_event(*args, **kwargs):
            return None

        module.fetchrow = fetchrow
        module.log_event = log_event
        sys.modules["services"].agent_runner = types.SimpleNamespace(spawn_agent=spawn_agent)
        module.access_control = types.SimpleNamespace(
            subject_from_request=lambda request: {
                "identity": {"username": "dev-y"},
                "roles": ["analyst", "agent-operator"],
                "capabilities": ["agents:spawn", "tickets:read", "tickets:note"],
                "scopes": [{"scope_type": "group", "scope_value": "Dev Team Y"}],
                "max_classification": "confidential",
            },
            ticket_access_decision=lambda ticket, subject, required_permission="tickets:read": {
                "allow": True,
                "reason": "owning_group_scope_match",
            },
        )

        result = asyncio.run(module.assign_agent(
            413,
            prompt="permission envelope probe",
            requested_permissions=["tickets:read", "access:admin"],
        ))

        self.assertEqual(result["agent_id"], 99)
        self.assertEqual(captured["ticket_id"], 413)
        self.assertEqual(captured["requested_permissions"], ["tickets:read", "access:admin"])
        self.assertEqual(captured["actor_context"]["identity"]["username"], "dev-y")

    def test_list_agents_qualifies_status_and_ticket_filters(self):
        module = load_agents_route()
        queries = []

        async def fetchall(query, *args):
            queries.append((query, args))
            return []

        module.fetchall = fetchall

        result = asyncio.run(module.list_agents(status="failed", ticket_id=312))

        self.assertEqual(result["total"], 0)
        query, args = queries[0]
        self.assertIn("a.status = $1", query)
        self.assertIn("a.ticket_id = $2", query)
        self.assertEqual(args, ("failed", 312))

    def test_list_agents_zeroes_stalled_timing_fields(self):
        module = load_agents_route()
        queries = []

        async def fetchall(query, *args):
            queries.append(query)
            return []

        module.fetchall = fetchall

        asyncio.run(module.list_agents())

        query = queries[0]
        self.assertIn("CASE WHEN a.status = 'stalled' THEN 0 ELSE GREATEST", query)
        self.assertIn("END AS running_seconds", query)
        self.assertIn("END AS task_working_seconds", query)

    def test_detect_completed_ticket_resolution_from_dashboard_evidence(self):
        module = load_agent_runner()
        calls = []

        async def fetchrow(query, *args):
            calls.append((query, args))
            if "FROM agent_tasks" in query:
                return {
                    "id": 92,
                    "agent_id": 95,
                    "ticket_id": 324,
                    "task_type": "ticket_resolution",
                    "started_at": "2026-05-12T20:42:11Z",
                    "created_at": "2026-05-12T20:42:11Z",
                }
            return {
                "completed_changes": 3,
                "open_changes": 0,
                "final_notes": 1,
                "postmortems": 1,
            }

        module.fetchrow = fetchrow

        result = asyncio.run(module._detect_completed_ticket_resolution(92, 95))

        self.assertEqual(result["ticket_id"], 324)
        self.assertEqual(result["completed_changes"], 3)
        self.assertEqual(result["final_notes"], 1)
        self.assertEqual(len(calls), 2)

    def test_detect_completed_ticket_resolution_rejects_open_approval_gate(self):
        module = load_agent_runner()

        async def fetchrow(query, *args):
            if "FROM agent_tasks" in query:
                return {
                    "id": 92,
                    "agent_id": 95,
                    "ticket_id": 324,
                    "task_type": "ticket_resolution",
                    "started_at": "2026-05-12T20:42:11Z",
                    "created_at": "2026-05-12T20:42:11Z",
                }
            return {
                "completed_changes": 2,
                "open_changes": 1,
                "final_notes": 1,
                "postmortems": 1,
            }

        module.fetchrow = fetchrow

        result = asyncio.run(module._detect_completed_ticket_resolution(92, 95))

        self.assertIsNone(result)

    def test_successful_agent_completion_does_not_close_ticket_implicitly(self):
        module = load_agent_runner()
        executes = []
        events = []
        fetch_calls = {"count": 0}

        async def fetchrow(query, *args):
            fetch_calls["count"] += 1
            if "JOIN agents" in query:
                return {
                    "ticket_id": 444,
                    "task_type": "ticket_resolution",
                    "task_status": "queued",
                    "agent_status": "spawned",
                }
            return {
                "ticket_id": 444,
                "task_type": "ticket_resolution",
                "started_at": "2026-05-12T23:00:00Z",
            }

        async def execute(*args):
            executes.append(args)

        async def log_event(*args):
            events.append(args)

        async def run_agent(*args):
            return {"exit_code": 0, "stdout": '{"type":"result","result":"done"}', "stderr": ""}

        async def mirror_checkpoint(*args):
            return {"status": "done", "output": "ticket resolved", "progress_pct": 100}

        async def complete_changes(*args, **kwargs):
            return {"completed": [], "skipped": []}

        async def add_note(*args, **kwargs):
            return 1

        module.fetchrow = fetchrow
        module.execute = execute
        module.log_event = log_event
        module._run_agent = run_agent
        module._mirror_checkpoint_to_task = mirror_checkpoint
        module.complete_approved_changes_for_task = complete_changes
        module._add_agent_note = add_note
        module._semaphore = asyncio.Semaphore(1)

        asyncio.run(module._spawn_with_semaphore("/tmp/work", "prompt", 201, 301))

        self.assertFalse(any("UPDATE tickets SET status = 'resolved'" in call[0] for call in executes))
        self.assertTrue(any(event[3] == "agent_completed" for event in events))

    def test_done_checkpoint_recovery_closes_ticket_when_prompt_required_closure(self):
        module = load_agent_runner()
        execute_calls = []
        note_calls = []
        event_calls = []
        provider_calls = []

        async def fetchrow(query, *args):
            if "JOIN tickets tk" in query:
                return {
                    "id": 211,
                    "agent_id": 214,
                    "ticket_id": 559,
                    "task_type": "ticket_resolution",
                    "prompt": "Clean the catalog, write evidence, and resolve the ticket.",
                    "started_at": "2026-05-15T15:09:10Z",
                    "created_at": "2026-05-15T15:09:10Z",
                    "ticket_status": "new",
                    "provider": "itop",
                    "provider_ref": "314",
                }
            if "FROM change_requests" in query and "open_access_requests" in query:
                return {"open_changes": 0, "open_access_requests": 0, "final_notes": 1}
            return None

        async def execute(query, *args):
            execute_calls.append((query, args))

        async def add_note(*args):
            note_calls.append(args)

        async def close_provider(*args):
            provider_calls.append(args)
            return {"status": "resolved"}

        async def log_event(*args):
            event_calls.append(args)

        module.fetchrow = fetchrow
        module.execute = execute
        module._add_agent_note = add_note
        module._close_provider_ticket_if_needed = close_provider
        module.log_event = log_event

        result = asyncio.run(module.recover_done_checkpoint_ticket_status(
            214,
            211,
            {"step": "learning_cleanup_complete", "status": "done", "progress_pct": 100},
            reason="unit_test_done_checkpoint",
        ))

        self.assertEqual(result["status"], "recovered")
        self.assertEqual(result["provider_result"]["status"], "resolved")
        self.assertTrue(any("UPDATE tickets SET status = 'resolved'" in call[0] for call in execute_calls))
        self.assertEqual(note_calls[0][0], 559)
        self.assertIn("done checkpoint recovery", note_calls[0][3].lower())
        self.assertEqual(provider_calls[0][0], 559)
        self.assertTrue(any(call[3] == "ticket_status_recovered_from_done_checkpoint" for call in event_calls))

    def test_done_checkpoint_recovery_skips_without_prompt_closure_requirement(self):
        module = load_agent_runner()
        execute_calls = []

        async def fetchrow(query, *args):
            if "JOIN tickets tk" in query:
                return {
                    "id": 212,
                    "agent_id": 215,
                    "ticket_id": 560,
                    "task_type": "ticket_resolution",
                    "prompt": "Collect evidence and leave the ticket for human review.",
                    "started_at": "2026-05-15T15:09:10Z",
                    "created_at": "2026-05-15T15:09:10Z",
                    "ticket_status": "in_progress",
                    "provider": "itop",
                    "provider_ref": "358",
                }
            raise AssertionError("evidence query should not run without closure intent")

        async def execute(query, *args):
            execute_calls.append((query, args))

        module.fetchrow = fetchrow
        module.execute = execute

        result = asyncio.run(module.recover_done_checkpoint_ticket_status(
            215,
            212,
            {"status": "done", "progress_pct": 100},
        ))

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "closure_not_required_by_prompt")
        self.assertEqual(execute_calls, [])

    def test_successful_agent_completion_writes_terminal_checkpoint_when_missing(self):
        module = load_agent_runner()

        async def fetchrow(query, *args):
            if "JOIN agents" in query:
                return {
                    "ticket_id": 537,
                    "task_type": "ticket_resolution",
                    "task_status": "queued",
                    "agent_status": "spawned",
                }
            return {
                "ticket_id": 537,
                "task_type": "ticket_resolution",
                "started_at": "2026-05-15T05:00:00Z",
            }

        async def execute(*args):
            return None

        async def log_event(*args):
            return None

        async def run_agent(*args):
            return {"exit_code": 0, "stdout": '{"type":"result","result":"closed ticket"}', "stderr": ""}

        async def mirror_checkpoint(*args):
            return None

        async def complete_changes(*args, **kwargs):
            return {"completed": [], "skipped": []}

        async def add_note(*args, **kwargs):
            return 1

        module.fetchrow = fetchrow
        module.execute = execute
        module.log_event = log_event
        module._run_agent = run_agent
        module._mirror_checkpoint_to_task = mirror_checkpoint
        module.complete_approved_changes_for_task = complete_changes
        module._add_agent_note = add_note
        module._semaphore = asyncio.Semaphore(1)

        with tempfile.TemporaryDirectory() as tmp:
            asyncio.run(module._spawn_with_semaphore(tmp, "prompt", 203, 200))
            checkpoint = Path(tmp, "checkpoint.json").read_text(encoding="utf-8")

        self.assertIn('"status": "done"', checkpoint)
        self.assertIn('"progress_pct": 100', checkpoint)
        self.assertIn('"step": "agent_runner_success"', checkpoint)

    def test_curl_guard_blocks_broad_dashboard_endpoints(self):
        module = load_agent_runner()
        with tempfile.TemporaryDirectory() as tmp:
            guard = module._write_curl_guard(
                tmp,
                real_curl=sys.executable,
                blocked_paths=["/openapi.json", "/api/tools"],
                max_output_bytes=80,
            )
            result = subprocess.run(
                [sys.executable, guard, "http://localhost:8000/openapi.json"],
                capture_output=True,
                text=True,
                timeout=10,
            )

        self.assertEqual(result.returncode, 64)
        self.assertIn("blocked broad dashboard endpoint", result.stderr)

    def test_curl_guard_truncates_oversized_allowed_output(self):
        module = load_agent_runner()
        with tempfile.TemporaryDirectory() as tmp:
            fake_curl = Path(tmp) / "fake_curl.py"
            fake_curl.write_text("import sys\nsys.stdout.write('x' * 120)\n", encoding="utf-8")
            guard = module._write_curl_guard(
                tmp,
                real_curl=sys.executable,
                blocked_paths=["/openapi.json"],
                max_output_bytes=25,
            )
            result = subprocess.run(
                [sys.executable, guard, str(fake_curl), "http://localhost:8000/api/tickets/327"],
                capture_output=True,
                text=True,
                timeout=10,
            )

        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "x" * 25)
        self.assertIn("stdout truncated from 120 bytes to 25 bytes", result.stderr)

    def test_postmortem_list_fields_accept_scalar_agent_payloads(self):
        module = load_postmortems_route()

        self.assertEqual(module._ensure_list("rerun EDR marker test"), ["rerun EDR marker test"])
        self.assertEqual(module._ensure_list('["one", "two"]'), ["one", "two"])
        self.assertEqual(module._ensure_list({"name": "guard"}), [{"name": "guard"}])

    def test_postmortem_text_fields_accept_list_and_dict_agent_payloads(self):
        module = load_postmortems_route()

        self.assertEqual(module._ensure_text(None), "")
        self.assertEqual(module._ensure_text("already text"), "already text")
        self.assertEqual(
            module._ensure_text(["rerun phishing test", {"name": "approve gates", "description": "required"}]),
            "- rerun phishing test\n- approve gates: required",
        )
        self.assertEqual(
            module._ensure_text({"root_cause": "agent sent list-shaped improvements"}),
            '{"root_cause": "agent sent list-shaped improvements"}',
        )

    def test_ticket_notes_accept_content_alias_from_agents(self):
        module = load_tickets_route()
        calls = []

        async def add_note(ticket_id, text, author, source, visibility, external_ref):
            calls.append((ticket_id, text, author, source, visibility, external_ref))
            return {"id": 420, "ticket_id": ticket_id, "status": "created"}

        module.ticket_service.add_note = add_note

        result = asyncio.run(
            module.add_ticket_note(
                340,
                content="Full evidence body from local agent",
                title="Agent closure proof - triage",
            )
        )

        self.assertEqual(result["status"], "created")
        self.assertIn("Agent closure proof - triage", calls[0][1])
        self.assertIn("Full evidence body from local agent", calls[0][1])

    def test_auto_assignment_skips_when_rule_capacity_reached(self):
        module = load_auto_assignment_service()
        events = []

        ticket = {
            "id": 350,
            "title": "[SIEM] Sysmon: Network connection from suspicious binary",
            "description": "EDR marker test",
            "itop_class": "Incident",
            "provider_class": "Incident",
            "assignee_team": "",
        }
        rule = {
            "id": 17,
            "name": "EDR/SIEM security alert",
            "assignment_group": "Security Operations",
            "keywords": '["sysmon", "edr", "siem alert"]',
            "ticket_class": "Incident",
            "auto_agent_model": "qwen/qwen3.6-27b",
            "auto_agent_prompt": "bounded prompt",
        }
        active = {
            "agent_id": 114,
            "ticket_id": 343,
            "title": "[SIEM] SysmonForLinux: Connection to suspicious port potential C2",
            "description": "EDR marker test already running",
            "itop_class": "Incident",
            "provider_class": "Incident",
            "assignee_team": "",
        }

        async def fetchrow(query, *args):
            if "SELECT * FROM tickets" in query:
                return ticket
            return None

        async def fetchall(query, *args):
            if "FROM service_raci_rules" in query:
                return [rule]
            if "FROM agents a" in query:
                return [active]
            return []

        async def log_event(*args):
            events.append(args)

        module.fetchrow = fetchrow
        module.fetchall = fetchall
        module.log_event = log_event
        module.DEFAULT_MAX_ACTIVE_PER_RULE = 1

        result = asyncio.run(module.maybe_auto_assign(350, source="unit-test"))

        self.assertEqual(result["status"], "skipped")
        self.assertEqual(result["reason"], "auto_assignment_capacity_reached")
        self.assertEqual(result["active_agent_ids"], [114])
        self.assertTrue(any(event[3] == "auto_assignment_capacity_reached" for event in events))

    def test_no_output_watchdog_stops_silent_process(self):
        module = load_agent_runner()

        async def run_watchdog():
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-c",
                "import time; time.sleep(30)",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            state = {"stalled": False, "reason": None}
            activity = {"last_output_at": module.time.monotonic() - 5}
            await module._terminate_after_no_output(process, 0.1, activity, state)
            await process.wait()
            return state, process.returncode

        state, returncode = asyncio.run(run_watchdog())

        self.assertTrue(state["stalled"])
        self.assertIn("produced no output", state["reason"])
        self.assertNotEqual(returncode, 0)

    def test_watchdog_stops_malformed_tool_use_without_tool_payload(self):
        module = load_agent_runner()

        async def run_watchdog():
            process = await asyncio.create_subprocess_exec(
                sys.executable,
                "-c",
                "import time; time.sleep(30)",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            state = {"stalled": False, "reason": None}
            activity = {
                "last_output_at": module.time.monotonic(),
                "malformed_tool_use_at": module.time.monotonic() - 2,
            }
            await module._terminate_after_no_output(process, 0.1, activity, state)
            await process.wait()
            return state, process.returncode

        state, returncode = asyncio.run(run_watchdog())

        self.assertTrue(state["stalled"])
        self.assertIn("tool_use", state["reason"])
        self.assertNotEqual(returncode, 0)

    def test_ticket_priority_rank_orders_high_priority_before_low(self):
        module = load_agent_runner()

        self.assertLess(module._ticket_priority_rank("P1"), module._ticket_priority_rank("P4"))
        self.assertGreater(
            module._ticket_priority_rank("P1", "postmortem"),
            module._ticket_priority_rank("P1", "ticket_resolution"),
        )

    def test_checkpoint_wait_gate_blocks_completion(self):
        module = load_agent_runner()

        checkpoint = {
            "step": "waiting-for-devsecops-access",
            "status": "waiting_for_access",
            "output": "Repository API returned 403",
            "progress_pct": 45,
        }

        self.assertTrue(module._checkpoint_blocks_completion(checkpoint))
        self.assertEqual(module._blocked_task_status(checkpoint), "awaiting_access")

    def test_wait_checkpoint_is_obsolete_after_gate_approval(self):
        module = load_agent_runner()

        checkpoint = {
            "step": "waiting-for-wazuh-access",
            "status": "waiting_for_access",
            "output": "waiting on Wazuh read access",
            "progress_pct": 45,
        }
        gate_state = {
            "pending": [],
            "approved": [{"id": 157, "status": "approved"}],
            "completed": [],
        }

        self.assertTrue(module._wait_checkpoint_obsolete(checkpoint, gate_state))

    def test_wait_checkpoint_is_not_obsolete_when_gate_still_pending(self):
        module = load_agent_runner()

        checkpoint = {
            "step": "waiting-for-wazuh-access",
            "status": "waiting_for_access",
            "output": "waiting on Wazuh read access",
            "progress_pct": 45,
        }
        gate_state = {
            "pending": [{"id": 157, "status": "pending"}],
            "approved": [],
            "completed": [],
        }

        self.assertFalse(module._wait_checkpoint_obsolete(checkpoint, gate_state))

    def test_done_checkpoint_does_not_block_completion(self):
        module = load_agent_runner()

        checkpoint = {
            "step": "access-resume-complete",
            "status": "done",
            "output": "Access grant verified and ticket resolved",
            "progress_pct": 100,
        }

        self.assertFalse(module._checkpoint_blocks_completion(checkpoint))

    def test_agent_priority_queue_dequeues_high_priority_first(self):
        module = load_agent_runner()
        ran = []
        events = []

        async def fake_spawn(work_dir, prompt, task_id, agent_id):
            ran.append((task_id, agent_id, prompt))

        async def fake_log_event(*args):
            events.append(args)

        async def exercise():
            module._agent_queue = asyncio.PriorityQueue()
            module._queue_workers = set()
            module._spawn_with_semaphore = fake_spawn
            module.log_event = fake_log_event
            await module._agent_queue.put((3, 1, "/tmp/low", "low", 10, 20))
            await module._agent_queue.put((0, 2, "/tmp/high", "high", 11, 21))
            worker = asyncio.create_task(module._agent_queue_worker())
            await module._agent_queue.join()
            worker.cancel()
            try:
                await worker
            except asyncio.CancelledError:
                pass

        asyncio.run(exercise())

        self.assertEqual([item[0] for item in ran], [11, 10])
        self.assertTrue(any(event[3] == "agent_queue_dequeued" for event in events))

    def test_manual_completion_skip_dedupe_uses_event_log_window(self):
        module = load_agent_runner()
        calls = []

        async def fetchval(query, *args):
            calls.append((query, args))
            return 1

        module.fetchval = fetchval

        result = asyncio.run(module._recent_manual_completion_skip(127, 155, 3600))

        self.assertTrue(result)
        self.assertIn("change_auto_complete_skipped", calls[0][0])
        self.assertEqual(calls[0][1], ("change_127", "155", "3600"))

    def test_completed_ticket_detection_counts_agent_source_notes(self):
        module = load_agent_runner()
        evidence_queries = []

        async def fetchrow(query, *args):
            if "FROM agent_tasks" in query:
                return {
                    "id": 162,
                    "agent_id": 165,
                    "ticket_id": 452,
                    "task_type": "ticket_resolution",
                    "started_at": "2026-05-14T00:27:28",
                    "created_at": "2026-05-14T00:27:28",
                }
            evidence_queries.append((query, args))
            return {
                "ticket_status": "closed",
                "completed_changes": 1,
                "open_changes": 0,
                "final_notes": 1,
                "postmortems": 1,
                "promoted_postmortems": 1,
            }

        module.fetchrow = fetchrow

        result = asyncio.run(module._detect_completed_ticket_resolution(162, 165))

        self.assertEqual(result["ticket_id"], 452)
        self.assertEqual(result["ticket_status"], "closed")
        self.assertEqual(result["final_notes"], 1)
        self.assertIn("source LIKE 'agent%'", evidence_queries[0][0])
        self.assertIn("author = ('agent-' || $4::text)", evidence_queries[0][0])
        self.assertEqual(evidence_queries[0][1][3], "165")

    def test_recover_completed_ticket_resolution_finalizes_running_task(self):
        module = load_agent_runner()
        execute_calls = []
        note_calls = []
        event_calls = []
        query_calls = []

        async def fetchrow(query, *args):
            query_calls.append(query)
            if "SELECT id, agent_id, ticket_id, task_type, status, pid, output" in query:
                return {
                    "id": 162,
                    "agent_id": 165,
                    "ticket_id": 452,
                    "task_type": "ticket_resolution",
                    "status": "running",
                    "pid": None,
                    "output": "",
                }
            if "FROM agent_tasks" in query:
                return {
                    "id": 162,
                    "agent_id": 165,
                    "ticket_id": 452,
                    "task_type": "ticket_resolution",
                    "started_at": "2026-05-14T00:27:28",
                    "created_at": "2026-05-14T00:27:28",
                }
            return {
                "ticket_status": "closed",
                "completed_changes": 1,
                "open_changes": 0,
                "final_notes": 1,
                "postmortems": 1,
                "promoted_postmortems": 1,
            }

        async def execute(query, *args):
            execute_calls.append((query, args))

        async def log_event(*args):
            event_calls.append(args)

        async def add_note(*args):
            note_calls.append(args)

        module.fetchrow = fetchrow
        module.execute = execute
        module.log_event = log_event
        module._add_agent_note = add_note

        result = asyncio.run(
            module.recover_completed_ticket_resolution(
                165,
                162,
                reason="unit_test_terminal_evidence",
            )
        )

        self.assertEqual(result["status"], "recovered")
        self.assertTrue(any("UPDATE agent_tasks SET status = 'completed'" in call[0] for call in execute_calls))
        self.assertTrue(any("UPDATE agents SET status = 'finished'" in call[0] for call in execute_calls))
        self.assertTrue(any(call[3] == "agent_terminal_completion_recovered" for call in event_calls))
        self.assertEqual(note_calls[0][0], 452)
        self.assertIn("terminal evidence recovery", note_calls[0][3].lower())

    def test_recover_completed_ticket_resolution_resolves_promoted_open_ticket(self):
        module = load_agent_runner()
        execute_calls = []
        note_calls = []
        event_calls = []

        async def fetchrow(query, *args):
            if "SELECT id, agent_id, ticket_id, task_type, status, pid, output" in query:
                return {
                    "id": 193,
                    "agent_id": 196,
                    "ticket_id": 531,
                    "task_type": "ticket_resolution",
                    "status": "running",
                    "pid": None,
                    "output": "",
                }
            if "FROM agent_tasks" in query:
                return {
                    "id": 193,
                    "agent_id": 196,
                    "ticket_id": 531,
                    "task_type": "ticket_resolution",
                    "started_at": "2026-05-14T23:00:45",
                    "created_at": "2026-05-14T23:00:45",
                }
            return {
                "ticket_status": "in_progress",
                "completed_changes": 2,
                "open_changes": 0,
                "final_notes": 1,
                "postmortems": 1,
                "promoted_postmortems": 1,
            }

        async def execute(query, *args):
            execute_calls.append((query, args))

        async def log_event(*args):
            event_calls.append(args)

        async def add_note(*args):
            note_calls.append(args)

        module.fetchrow = fetchrow
        module.execute = execute
        module.log_event = log_event
        module._add_agent_note = add_note

        result = asyncio.run(
            module.recover_completed_ticket_resolution(
                196,
                193,
                reason="unit_test_promoted_ticket_finalization",
            )
        )

        self.assertEqual(result["status"], "recovered")
        self.assertTrue(result["evidence"]["auto_resolved"])
        self.assertTrue(any("UPDATE tickets SET status = 'resolved'" in call[0] for call in execute_calls))
        self.assertTrue(any(call[3] == "ticket_status_recovered_from_terminal_evidence" for call in event_calls))
        self.assertEqual(note_calls[0][0], 531)
        self.assertIn("terminal evidence recovery", note_calls[-1][3].lower())


if __name__ == "__main__":
    unittest.main()
