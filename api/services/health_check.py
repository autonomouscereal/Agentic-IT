import os
import asyncio
import time
import socket
from datetime import datetime
from database import fetchall, execute, json_dumps
from services.event_logger import log_event

HEALTH_CHECK_INTERVAL = int(os.getenv("HEALTH_CHECK_INTERVAL", "60"))


async def check_port(host, port, timeout=3):
    """Check if a port is open on a host."""
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port), timeout=timeout
        )
        writer.close()
        await writer.wait_closed()
        return True
    except:
        return False


async def check_http(host, port, path="/", timeout=5):
    """Check if an HTTP endpoint responds."""
    try:
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"http://{host}:{port}{path}",
                timeout=aiohttp.ClientTimeout(total=timeout),
                ssl=False,
            ) as resp:
                return resp.status < 500
    except:
        return False


async def check_tool(tool_id: int):
    """Check health of a single tool."""
    import asyncio

    tool = await fetchall("SELECT * FROM tools WHERE id = $1", tool_id)
    if not tool:
        return {"error": "Tool not found"}
    tool = tool[0]

    start = time.time()
    status = "down"
    error = None

    try:
        host = tool.get("host") or "localhost"
        port = tool.get("port")

        if port:
            tool_type = tool.get("type", "")
            if tool_type in ("siem-ui", "soc-platform", "iam", "vcs", "search"):
                ok = await check_http(host, port)
            elif tool_type == "email":
                ok = await check_port(host, port, timeout=2)
            else:
                ok = await check_port(host, port)

            if ok:
                status = "healthy"
            else:
                status = "down"
                error = f"Port {port} unreachable on {host}"
        else:
            status = "unknown"
            error = "No port configured for health check"

    except Exception as e:
        status = "down"
        error = str(e)

    response_time = int((time.time() - start) * 1000)

    # Record check result
    await execute("""
        INSERT INTO tool_checks (tool_id, timestamp, status, response_time_ms, error)
        VALUES ($1, NOW(), $2, $3, $4)
    """, tool_id, status, response_time, error)

    # Update tool status
    await execute("""
        UPDATE tools SET status = $1, last_check = NOW(), updated_at = NOW()
        WHERE id = $2
    """, status, tool_id)

    # Log status changes
    if status != "healthy":
        await log_event("health", "warning" if status == "unknown" else "error",
                        "health_check", f"tool_{status}",
                        tool["name"], {"status": status, "error": error, "response_time_ms": response_time})

    return {"tool_id": tool_id, "name": tool["name"], "status": status,
            "response_time_ms": response_time, "error": error}


async def check_all_tools():
    """Check health of all tools."""
    tools = await fetchall("SELECT id FROM tools")
    results = []
    for tool in tools:
        result = await check_tool(tool["id"])
        results.append(result)
    await log_event("health", "info", "health_check", "check_cycle_complete",
                    str(len(results)))
    return results


async def health_loop():
    """Background health check loop."""
    enabled = True
    try:
        settings = await fetchval("SELECT value FROM dashboard_settings WHERE key = 'health_check_enabled'")
        if settings:
            enabled = json.loads(settings).get("enabled", True)
    except:
        pass

    if not enabled:
        return

    print(f"Health check loop started (interval: {HEALTH_CHECK_INTERVAL}s)")
    await log_event("system", "info", "health_check", "loop_started",
                    f"interval={HEALTH_CHECK_INTERVAL}s")
    while True:
        try:
            await check_all_tools()
        except Exception as e:
            print(f"Health check error: {e}")
            await log_event("health", "error", "health_check", "loop_error", str(e))
        await asyncio.sleep(HEALTH_CHECK_INTERVAL)
