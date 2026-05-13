import unittest
import importlib.util
import sys
import types
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_itop_sync():
    database = types.ModuleType("database")
    database.fetchall = lambda *args, **kwargs: None
    database.fetchrow = lambda *args, **kwargs: None
    database.fetchval = lambda *args, **kwargs: None
    database.execute = lambda *args, **kwargs: None
    database.json_dumps = lambda value: value
    sys.modules["database"] = database

    services = types.ModuleType("services")
    sys.modules["services"] = services

    ticket_provider = types.ModuleType("services.ticket_provider")

    class TicketProvider:
        pass

    ticket_provider.TicketProvider = TicketProvider
    sys.modules["services.ticket_provider"] = ticket_provider

    event_logger = types.ModuleType("services.event_logger")
    event_logger.log_event = lambda *args, **kwargs: None
    sys.modules["services.event_logger"] = event_logger

    spec = importlib.util.spec_from_file_location(
        "itop_sync_under_test", ROOT / "api" / "services" / "itop_sync.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


itop_sync = load_itop_sync()


class ITopSyncStatusTests(unittest.TestCase):
    def test_active_agent_preserves_in_progress_over_new_provider_state(self):
        self.assertEqual(
            itop_sync._effective_local_status("new", "in_progress", has_active_agent=True),
            "in_progress",
        )

    def test_active_agent_preserves_waiting_state(self):
        self.assertEqual(
            itop_sync._effective_local_status("new", "awaiting_user_response", has_active_agent=True),
            "awaiting_user_response",
        )

    def test_terminal_provider_state_wins(self):
        self.assertEqual(
            itop_sync._effective_local_status("resolved", "in_progress", has_active_agent=True),
            "resolved",
        )

    def test_provider_state_used_without_active_agent(self):
        self.assertEqual(
            itop_sync._effective_local_status("assigned", "new", has_active_agent=False),
            "assigned",
        )


if __name__ == "__main__":
    unittest.main()
