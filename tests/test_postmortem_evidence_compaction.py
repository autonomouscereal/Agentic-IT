import importlib.util
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_postmortems_route():
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

        def delete(self, *args, **kwargs):
            return lambda func: func

    fastapi.APIRouter = APIRouter
    fastapi.Body = lambda default=None, *args, **kwargs: default
    fastapi.Query = lambda default=None, *args, **kwargs: default
    sys.modules["fastapi"] = fastapi

    database = types.ModuleType("database")
    database.fetchall = lambda *args, **kwargs: None
    database.fetchrow = lambda *args, **kwargs: None
    database.fetchval = lambda *args, **kwargs: None
    database.execute = lambda *args, **kwargs: None
    database.json_dumps = lambda value: value
    sys.modules["database"] = database

    services = types.ModuleType("services")
    sys.modules["services"] = services

    event_logger = types.ModuleType("services.event_logger")
    event_logger.log_event = lambda *args, **kwargs: None
    sys.modules["services.event_logger"] = event_logger

    synthesizer = types.ModuleType("services.postmortem_synthesizer")
    synthesizer.synthesize_postmortem = lambda *args, **kwargs: {}
    sys.modules["services.postmortem_synthesizer"] = synthesizer

    ticket_service = types.ModuleType("services.ticket_service")
    ticket_service.compact_ticket_payload = lambda ticket: ticket
    sys.modules["services.ticket_service"] = ticket_service

    workflow_keys_spec = importlib.util.spec_from_file_location(
        "services.workflow_keys",
        ROOT / "api" / "services" / "workflow_keys.py",
    )
    workflow_keys = importlib.util.module_from_spec(workflow_keys_spec)
    workflow_keys_spec.loader.exec_module(workflow_keys)
    sys.modules["services.workflow_keys"] = workflow_keys

    spec = importlib.util.spec_from_file_location(
        "tested_postmortems",
        ROOT / "api" / "routes" / "postmortems.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PostmortemEvidenceCompactionTests(unittest.TestCase):
    def test_evidence_terms_preserve_security_signal_words(self):
        module = load_postmortems_route()
        terms = module._evidence_terms({
            "title": "[SIEM] SysmonForLinux: Persistence mechanism file creation",
            "description": "Rule ID 100225 on wazuh.manager",
            "provider_class": "Incident",
        })

        self.assertIn("sysmonforlinux", terms)
        self.assertIn("persistence", terms)
        self.assertIn("100225", terms)
        self.assertNotIn("incident", terms)

    def test_rank_evidence_items_prefers_ticket_relevant_assets(self):
        module = load_postmortems_route()
        terms = ["sysmonforlinux", "persistence", "100225"]
        rows = [
            {"id": 1, "title": "Phishing workflow", "body": "Handle credential harvest."},
            {"id": 2, "title": "Sysmon persistence triage", "body": "Rule 100225 for SysmonForLinux."},
        ]

        ranked = module._rank_evidence_items(rows, terms, ("title", "body"), limit=2)

        self.assertEqual(ranked[0]["id"], 2)


if __name__ == "__main__":
    unittest.main()
