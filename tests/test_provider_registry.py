import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_provider_registry():
    services = types.ModuleType("services")
    sys.modules["services"] = services

    itop_sync = types.ModuleType("services.itop_sync")
    itop_sync.ITOP_HOST = "itop.local"
    itop_sync.ITOP_USER = "api-user"
    itop_sync.ITOP_PASSWORD = "from-env"
    itop_sync.TICKET_CLASSES = ["Incident", "UserRequest"]
    sys.modules["services.itop_sync"] = itop_sync

    external_ticket_adapters = types.ModuleType("services.external_ticket_adapters")

    class Provider:
        configured = False
        ticket_classes = []

    external_ticket_adapters.GenericWebhookProvider = Provider
    external_ticket_adapters.JiraProvider = Provider
    external_ticket_adapters.ServiceNowProvider = Provider
    sys.modules["services.external_ticket_adapters"] = external_ticket_adapters

    spec = importlib.util.spec_from_file_location(
        "tested_provider_registry",
        ROOT / "api" / "services" / "provider_registry.py",
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ProviderRegistryTests(unittest.TestCase):
    def test_explicit_local_preference_stays_local_when_itop_configured(self):
        module = load_provider_registry()
        self.assertEqual(module.default_ticket_provider("local"), "local")

    def test_automatic_selection_prefers_configured_itop(self):
        old_default = os.environ.pop("DEFAULT_TICKET_PROVIDER", None)
        old_active = os.environ.pop("ACTIVE_TICKET_PROVIDER", None)
        try:
            module = load_provider_registry()
            self.assertEqual(module.default_ticket_provider(), "itop")
        finally:
            if old_default is not None:
                os.environ["DEFAULT_TICKET_PROVIDER"] = old_default
            if old_active is not None:
                os.environ["ACTIVE_TICKET_PROVIDER"] = old_active


if __name__ == "__main__":
    unittest.main()
