from fastapi import APIRouter, HTTPException, Query

from database import fetchrow
from services import access_control, wazuh_client
from services.event_logger import log_event


router = APIRouter(prefix="/api/agents/{agent_id}/wazuh", tags=["wazuh"])


def _transport_error(data):
    """True for dashboard/client transport errors, not Wazuh semantic errors.

    Wazuh API payloads use an integer `error` field where `0` is success and
    `1` can mean "no rule returned." That should stay visible to the agent as
    provider evidence instead of becoming a dashboard 502.
    """
    return isinstance((data or {}).get("error"), str)


async def _require_wazuh_read(agent_id: int, resource_type="api", resource_id="wazuh.manager"):
    agent = await fetchrow("SELECT id, ticket_id FROM agents WHERE id = $1", agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    result = await access_control.request_agent_vault_lease(
        agent_id,
        "wazuh",
        resource_type,
        resource_id,
        "read",
    )
    if not result.get("allow"):
        raise HTTPException(status_code=403, detail=result)
    await log_event(
        "access",
        "info",
        f"agent_{agent_id}",
        "wazuh_provider_access_allowed",
        f"agent_{agent_id}",
        {
            "ticket_id": agent.get("ticket_id"),
            "resource_type": resource_type,
            "resource_id": resource_id,
            "lease_id": result.get("lease_id"),
            "credential_ref": result.get("credential_ref"),
            "secret_values_returned": False,
        },
    )
    return result


@router.get("/manager/status")
async def get_manager_status(agent_id: int):
    """Return Wazuh manager status after validating the agent's scoped lease."""
    lease = await _require_wazuh_read(agent_id)
    data = await wazuh_client.manager_status()
    if _transport_error(data):
        await log_event("tool", "error", f"agent_{agent_id}", "wazuh_manager_status_failed",
                        f"agent_{agent_id}", {"error": data, "lease_id": lease.get("lease_id")})
        raise HTTPException(status_code=502, detail=data)
    await log_event("tool", "info", f"agent_{agent_id}", "wazuh_manager_status_read",
                    f"agent_{agent_id}", {"lease_id": lease.get("lease_id")})
    return {
        "agent_id": agent_id,
        "lease_id": lease.get("lease_id"),
        "credential_ref": lease.get("credential_ref"),
        "secret_values_returned": False,
        "data": data,
    }


@router.get("/rules/{rule_id}")
async def get_rule(agent_id: int, rule_id: str):
    """Return Wazuh rule metadata after validating the agent's scoped lease."""
    lease = await _require_wazuh_read(agent_id)
    data = await wazuh_client.rule(rule_id)
    if _transport_error(data):
        await log_event("tool", "error", f"agent_{agent_id}", "wazuh_rule_lookup_failed",
                        f"wazuh_rule_{rule_id}", {"error": data, "lease_id": lease.get("lease_id")})
        raise HTTPException(status_code=502, detail=data)
    await log_event("tool", "info", f"agent_{agent_id}", "wazuh_rule_lookup",
                    f"wazuh_rule_{rule_id}", {
                        "lease_id": lease.get("lease_id"),
                        "wazuh_error": data.get("error"),
                        "returned": ((data.get("data") or {}).get("total_affected_items")),
                    })
    return {
        "agent_id": agent_id,
        "rule_id": str(rule_id),
        "lease_id": lease.get("lease_id"),
        "credential_ref": lease.get("credential_ref"),
        "secret_values_returned": False,
        "data": data,
    }


@router.get("/alerts/search")
async def search_alerts(
    agent_id: int,
    rule_id: str = Query(None),
    source_ip: str = Query(None),
    limit: int = Query(10, ge=1, le=50),
):
    """Search Wazuh indexer alerts after validating the agent's scoped lease."""
    lease = await _require_wazuh_read(agent_id)
    data = await wazuh_client.search_alerts(rule_id=rule_id, source_ip=source_ip, limit=limit)
    if _transport_error(data):
        await log_event("tool", "error", f"agent_{agent_id}", "wazuh_alert_search_failed",
                        f"agent_{agent_id}", {"error": data, "lease_id": lease.get("lease_id")})
        raise HTTPException(status_code=502, detail=data)
    await log_event("tool", "info", f"agent_{agent_id}", "wazuh_alert_search",
                    f"agent_{agent_id}", {
                        "lease_id": lease.get("lease_id"),
                        "rule_id": rule_id,
                        "source_ip": source_ip,
                        "returned": len(data.get("alerts") or []),
                    })
    return {
        "agent_id": agent_id,
        "lease_id": lease.get("lease_id"),
        "credential_ref": lease.get("credential_ref"),
        "secret_values_returned": False,
        "query": {"rule_id": rule_id, "source_ip": source_ip, "limit": limit},
        "data": data,
    }
