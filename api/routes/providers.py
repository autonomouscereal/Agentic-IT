from fastapi import APIRouter, Body
from services import provider_registry
from services.event_logger import log_event

router = APIRouter(prefix="/api/providers", tags=["providers"])


@router.get("")
async def list_providers():
    return {"providers": provider_registry.list_providers()}


@router.post("/{provider_name}/sync-all")
async def sync_provider(provider_name: str):
    result = await provider_registry.full_sync(provider_name)
    await log_event("sync", "info", "dashboard", "provider_sync_requested",
                    provider_name, result)
    return result


@router.post("/{provider_name}/sync-ticket")
async def sync_provider_ticket(
    provider_name: str,
    ticket_class: str = Body(...),
    ticket_ref: str = Body(...),
):
    result = await provider_registry.sync_ticket(provider_name, ticket_class, ticket_ref)
    await log_event("sync", "info", "dashboard", "provider_ticket_sync_requested",
                    provider_name, {"ticket_class": ticket_class, "ticket_ref": ticket_ref, "result": result})
    return result
