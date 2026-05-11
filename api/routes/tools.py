from fastapi import APIRouter
from datetime import datetime, timedelta
from database import fetchall, fetchrow, execute, executemany

router = APIRouter(prefix="/api/tools", tags=["tools"])

@router.get("")
async def list_tools():
    rows = await fetchall("""
        SELECT t.*, tc.status AS last_check_status, tc.response_time_ms
        FROM tools t
        LEFT JOIN (
            SELECT tool_id, status, response_time_ms,
                   ROW_NUMBER() OVER (PARTITION BY tool_id ORDER BY timestamp DESC) as rn
            FROM tool_checks
        ) tc ON t.id = tc.tool_id AND tc.rn = 1
        ORDER BY t.type, t.name
    """)
    return {"tools": rows, "total": len(rows)}

@router.get("/status")
async def tools_status_summary():
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
    return summary

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
