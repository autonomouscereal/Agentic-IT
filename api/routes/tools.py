from fastapi import APIRouter
from datetime import datetime, timedelta
from database import fetchall, fetchrow, execute, executemany, json_dumps
from services import platform_manifest
from services.event_logger import log_event

router = APIRouter(prefix="/api/tools", tags=["tools"])


async def cleanup_tool_inventory():
    await execute("DELETE FROM tools WHERE lower(name) = 'comfyui'")
    await execute("DELETE FROM tools WHERE lower(name) = 'thehive' AND port IS NULL")


@router.get("")
async def list_tools():
    await cleanup_tool_inventory()
    rows = await fetchall("""
        SELECT t.*, tc.status AS last_check_status, tc.response_time_ms
        FROM tools t
        LEFT JOIN (
            SELECT tool_id, status, response_time_ms,
                   ROW_NUMBER() OVER (PARTITION BY tool_id ORDER BY timestamp DESC) as rn
            FROM tool_checks
        ) tc ON t.id = tc.tool_id AND tc.rn = 1
        WHERE lower(t.name) <> 'comfyui'
          AND NOT (lower(t.name) = 'thehive' AND t.port IS NULL)
        ORDER BY t.type, t.name
    """)
    manifest = platform_manifest.load_manifest()
    modules = [
        {
            "id": module.get("id"),
            "name": module.get("name"),
            "category": module.get("category"),
            "status": module.get("status"),
            "deployable": module.get("deployable"),
            "health_checks": module.get("health_checks", []),
            "skill": module.get("skill"),
            "provider_contract": module.get("provider_contract"),
        }
        for module in manifest.get("modules", [])
        if module.get("status") in ("implemented", "blueprint") and module.get("id") not in ("comfyui",)
    ]
    return {"tools": rows, "total": len(rows), "setup_modules": modules}

@router.get("/status")
async def tools_status_summary():
    await cleanup_tool_inventory()
    rows = await fetchall("""
        SELECT t.name, t.status, t.last_check, tc.status AS last_check_status
        FROM tools t
        LEFT JOIN (
            SELECT tool_id, status,
                   ROW_NUMBER() OVER (PARTITION BY tool_id ORDER BY timestamp DESC) as rn
            FROM tool_checks
        ) tc ON t.id = tc.tool_id AND tc.rn = 1
    """)
    summary = {"healthy": 0, "degraded": 0, "down": 0, "unknown": 0, "tools": []}
    for row in rows:
        status = row.get("last_check_status") or row.get("status") or "unknown"
        if status == "healthy":
            summary["healthy"] += 1
        elif status == "degraded":
            summary["degraded"] += 1
        elif status == "down":
            summary["down"] += 1
        else:
            summary["unknown"] += 1
        summary["tools"].append({"name": row["name"], "status": status})
    summary["setup_modules"] = len(platform_manifest.load_manifest().get("modules", []))
    return summary


@router.post("/sync-manifest")
async def sync_manifest_tools(body: dict = None):
    """Reconcile dashboard-visible tools with the setup manifest.

    This removes excluded inventory rows and records a manifest sync event. It
    deliberately avoids inserting every blueprint module as a port-checked tool;
    the setup page remains the source for modules that are not actually in use.
    """
    await cleanup_tool_inventory()
    await executemany("""
        INSERT INTO tools (name, type, host, port, description)
        VALUES ($1, $2, $3, $4, $5)
        ON CONFLICT (name) DO UPDATE SET
            type = EXCLUDED.type,
            host = EXCLUDED.host,
            port = EXCLUDED.port,
            description = EXCLUDED.description,
            updated_at = NOW()
    """, [
        ("iTop ITSM", "itsm", "host.docker.internal", 25432,
         "Reference ITSM/ticket provider used for provider-sync demos"),
        ("Wazuh SIEM", "siem", "host.docker.internal", 26500,
         "Wazuh manager API for SIEM/EDR investigation workflows"),
        ("Wazuh Indexer", "siem", "host.docker.internal", 26920,
         "Wazuh/OpenSearch indexer for alert evidence"),
        ("Wazuh Dashboard", "siem-ui", "host.docker.internal", 26443,
         "Wazuh dashboard UI for security operations demos"),
        ("Zeek IDS", "ids", "host.docker.internal", 26001,
         "Zeek reference IDS service"),
        ("Suricata IDS", "ids", None, None,
         "Suricata reference IDS service"),
        ("GitLab", "vcs", "host.docker.internal", 80,
         "GitLab CE reference source-control and CI/CD provider"),
        ("SearXNG", "search", "host.docker.internal", 7999,
         "Private web research/search provider for agents"),
        ("Keycloak", "iam", "host.docker.internal", 8443,
         "Keycloak identity provider and Admin Console"),
        ("Mailcow", "email-api", "host.docker.internal", 8081,
         "Reference Mailcow email module via the working API/UI shim"),
        ("Mailcow API/UI Shim", "email-api", "host.docker.internal", 8081,
         "Optional Mailcow compatibility API and demo admin UI sidecar"),
        ("Roundcube Webmail", "email-ui", "host.docker.internal", 2581,
         "Roundcube webmail client for Mailcow demo/report-phish workflows"),
        ("Element Ops Chat", "chat-ui", "host.docker.internal", 3301,
         "Element Web Matrix client connected to the Agentic Operations intake bridge"),
        ("Matrix Synapse Ops Chat", "chat", "host.docker.internal", 3302,
         "Matrix Synapse homeserver for real chat intake with Keycloak OIDC"),
        ("Ops Chat Matrix Bridge", "bridge", "ops-chat-bridge", 29318,
         "Matrix application-service bridge that creates dashboard tickets and queues real agents"),
        ("Agent Memory", "memory", "agent-memory-db", 5432,
         "Shared PostgreSQL/pgvector memory service for dashboard agents"),
    ])
    await execute("DELETE FROM tools WHERE name = 'Open WebUI Ops Chat'")
    manifest = platform_manifest.load_manifest()
    excluded = [item.get("id") for item in manifest.get("excluded_modules", [])]
    await log_event("health", "info", "dashboard", "tool_manifest_synced",
                    "tools", {"excluded": excluded})
    return {"status": "synced", "excluded": excluded, "module_count": len(manifest.get("modules", []))}

@router.get("/{tool_id}")
async def get_tool(tool_id: int):
    tool = await fetchrow("SELECT * FROM tools WHERE id = $1", tool_id)
    if not tool:
        return {"error": "Tool not found"}
    checks = await fetchall("""
        SELECT * FROM tool_checks WHERE tool_id = $1
        ORDER BY timestamp DESC LIMIT 50
    """, tool_id)
    tool["recent_checks"] = checks
    return tool

@router.get("/{tool_id}/history")
async def tool_history(tool_id: int, hours: int = 24):
    since = datetime.now() - timedelta(hours=hours)
    checks = await fetchall("""
        SELECT * FROM tool_checks
        WHERE tool_id = $1 AND timestamp > $2
        ORDER BY timestamp DESC
    """, tool_id, since)
    return {"tool_id": tool_id, "checks": checks, "count": len(checks)}

@router.post("/{tool_id}/check")
async def trigger_check(tool_id: int):
    from services import health_check
    result = await health_check.check_tool(tool_id)
    return result

@router.post("/check-all")
async def trigger_all_checks():
    from services import health_check
    results = await health_check.check_all_tools()
    return {"results": results, "count": len(results)}
