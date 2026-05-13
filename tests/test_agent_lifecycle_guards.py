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


def load_tickets_route():
    fastapi = types.ModuleType("fastapi")

    class APIRouter:
        def __init__(self, *args, **kwargs):
            pass

        def get(self, *args, **kwargs):
            return lambda fn: fn

        def post(self, *args, **kwargs):
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

    spec = importlib.util.spec_from_file_location(
        "tested_postmortems_route",
        ROOT / "api" / "routes" / "postmortems.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AgentLifecycleGuardTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
