"""Ticket provider registry.

Provider-specific code lives behind this registry. The dashboard API uses
provider names and canonical tickets, so iTop can be swapped with ServiceNow,
Jira, or a local-only provider without changing the frontend contract.
"""
from services import itop_sync
from services.external_ticket_adapters import (
    GenericWebhookProvider,
    JiraProvider,
    ServiceNowProvider,
)


class LocalProvider:
    name = "local"
    ticket_classes = ["Incident", "UserRequest", "Change"]

    async def connect(self):
        return True

    async def is_connected(self):
        return True

    async def sync_ticket(self, ticket_class, ticket_key):
        return {"status": "local_only", "provider": self.name, "provider_ref": str(ticket_key)}

    async def full_sync(self):
        return {"synced": 0, "errors": 0, "new": 0, "provider": self.name}

    async def create_ticket(self, ticket_id, fields):
        return {"status": "local_only", "ticket_id": ticket_id, "provider": self.name}

    async def update_ticket(self, ticket_id, fields):
        return {"status": "local_only", "ticket_id": ticket_id, "fields": list((fields or {}).keys())}

    async def close_ticket(self, ticket_id, notes):
        return {"status": "local_only", "ticket_id": ticket_id}


_providers = {
    "local": LocalProvider(),
    "servicenow": ServiceNowProvider(),
    "jira": JiraProvider(),
    "generic-webhook": GenericWebhookProvider(),
}


def _itop_configured():
    return bool(itop_sync.ITOP_HOST and itop_sync.ITOP_USER and itop_sync.ITOP_PASSWORD)


def provider_configured(name):
    if name == "local":
        return True
    if name == "itop":
        return _itop_configured()
    provider = _providers.get(name)
    return bool(getattr(provider, "configured", False))


def default_ticket_provider(preferred=None):
    """Return the best outbound ticket provider for automatic sync.

    Local remains the fallback. External providers are selected only when their
    environment is configured, so callers can always request "sync if possible"
    without adding extra UI decisions.
    """
    import os

    candidates = []
    for value in (preferred, os.getenv("DEFAULT_TICKET_PROVIDER"), os.getenv("ACTIVE_TICKET_PROVIDER")):
        if value:
            candidates.append(value)
    candidates.extend(["itop", "servicenow", "jira", "generic-webhook"])
    for name in candidates:
        if name and name != "local" and provider_configured(name):
            return name
    return "local"


def list_providers():
    providers = [
        {
            "name": name,
            "ticket_classes": getattr(provider, "ticket_classes", []),
            "configured": bool(getattr(provider, "configured", True)),
        }
        for name, provider in sorted(_providers.items())
    ]
    providers.append({"name": "itop", "ticket_classes": itop_sync.TICKET_CLASSES, "configured": _itop_configured()})
    return providers


async def get_provider(name=None):
    provider_name = name or "local"
    if provider_name == "itop":
        return await itop_sync.get_provider()
    return _providers.get(provider_name)


async def sync_ticket(provider_name, ticket_class, ticket_ref):
    provider = await get_provider(provider_name)
    if not provider:
        return {"error": f"Provider not registered: {provider_name}"}
    return await provider.sync_ticket(ticket_class, ticket_ref)


async def create_ticket(provider_name, ticket_id, fields):
    provider = await get_provider(provider_name)
    if not provider:
        return {"error": f"Provider not registered: {provider_name}"}
    if not hasattr(provider, "create_ticket"):
        return {"error": f"Provider does not support outbound create: {provider_name}"}
    return await provider.create_ticket(ticket_id, fields)


async def full_sync(provider_name="itop"):
    provider = await get_provider(provider_name)
    if not provider:
        return {"error": f"Provider not registered: {provider_name}"}
    return await provider.full_sync()
