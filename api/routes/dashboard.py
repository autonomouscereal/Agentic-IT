from fastapi import APIRouter
import json
from datetime import datetime, timedelta
from database import fetchall, fetchrow, execute, fetchval, json_dumps

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


def _detail_value(details, *keys):
    if isinstance(details, str):
        try:
            details = json.loads(details)
        except Exception:
            return None
    if not isinstance(details, dict):
        return None
    for key in keys:
        value = details.get(key)
        if value not in (None, "", []):
            return value


def _normalize_details(row):
    details = row.get("details")
    if isinstance(details, str):
        try:
            details = json.loads(details)
            row["details"] = details
        except Exception:
            pass
    return row.get("details")


def _audit_summary(row):
    actor = row.get("actor") or "system"
    action = (row.get("action") or "").replace("_", " ")
    target = row.get("target") or ""
    details = row.get("details")
    ticket_id = _detail_value(details, "ticket_id")
    agent_id = _detail_value(details, "agent_id")
    model = _detail_value(details, "model")
    status = _detail_value(details, "status")
    if ticket_id and f"ticket_{ticket_id}" not in target:
        target = f"{target} ticket_{ticket_id}".strip()
    if agent_id and f"agent_{agent_id}" not in target:
        target = f"{target} agent_{agent_id}".strip()
    suffix = []
    if model:
        suffix.append(f"model {model}")
    if status:
        suffix.append(f"status {status}")
    if row.get("source") == "note":
        body = _detail_value(details, "body")
        note_summary = f"{actor} added a note"
        if target:
            note_summary = f"{note_summary} on {target}"
        if body:
            note_summary = f"{note_summary}: {body[:180]}"
        return note_summary

    summary = f"{actor} {action}".strip()
    if target:
        summary = f"{summary} on {target}"
    if suffix:
        summary = f"{summary} ({', '.join(suffix)})"
    return summary

@router.get("/stats")
async def dashboard_stats():
    # Ticket stats
    ticket_total = await fetchval("SELECT COUNT(*) FROM tickets") or 0
    ticket_new = await fetchval("SELECT COUNT(*) FROM tickets WHERE lower(status) = 'new'") or 0
    ticket_assigned = await fetchval("SELECT COUNT(*) FROM tickets WHERE lower(status) IN ('assigned', 'in_progress')") or 0
    ticket_resolved = await fetchval("SELECT COUNT(*) FROM tickets WHERE lower(status) = 'resolved'") or 0
    ticket_closed = await fetchval("SELECT COUNT(*) FROM tickets WHERE lower(status) LIKE '%closed%'") or 0

    # Agent stats
    agent_active = await fetchval("SELECT COUNT(*) FROM agents WHERE status IN ('spawned', 'running', 'working')") or 0
    agent_total = await fetchval("SELECT COUNT(*) FROM agents") or 0

    # Change request stats
    change_pending = await fetchval("SELECT COUNT(*) FROM change_requests WHERE status = 'pending'") or 0

    # Tool stats
    tool_total = await fetchval("SELECT COUNT(*) FROM tools") or 0
    tool_healthy = await fetchval("""
        SELECT COUNT(DISTINCT t.id) FROM tools t
        JOIN tool_checks tc ON t.id = tc.tool_id
        WHERE tc.status = 'healthy'
        AND tc.timestamp > NOW() - INTERVAL '5 minutes'
    """) or 0

    # Recent activity
    recent_audit = await fetchall("""
        SELECT id, actor, action, target, details, created_at, source
        FROM (
            SELECT id, actor, action, target, details, created_at, 'audit' AS source
            FROM audit_log
            UNION ALL
            SELECT id, COALESCE(actor, 'system') AS actor, action, target, details, created_at, 'event' AS source
            FROM event_log
            UNION ALL
            SELECT id,
                   author AS actor,
                   'ticket_note_added' AS action,
                   'ticket_' || ticket_id::text AS target,
                   jsonb_build_object(
                       'ticket_id', ticket_id,
                       'note_id', id,
                       'source', source,
                       'visibility', visibility,
                       'body', left(body, 500)
                   ) AS details,
                   created_at,
                   'note' AS source
            FROM ticket_notes
        ) activity
        ORDER BY created_at DESC LIMIT 30
    """)
    for row in recent_audit:
        details = _normalize_details(row)
        row["summary"] = _audit_summary(row)
        row["ticket_id"] = _detail_value(details, "ticket_id")
        row["agent_id"] = _detail_value(details, "agent_id")

    # Ticket trend (last 7 days)
    ticket_trend = await fetchall("""
        SELECT DATE(created_at) AS date, COUNT(*) AS count
        FROM tickets
        WHERE created_at > NOW() - INTERVAL '7 days'
        GROUP BY DATE(created_at)
        ORDER BY date
    """)

    # Agent status distribution
    agent_dist = await fetchall("""
        SELECT status, COUNT(*) AS count FROM agents GROUP BY status
    """)

    return {
        "tickets": {
            "total": ticket_total,
            "new": ticket_new,
            "assigned": ticket_assigned,
            "resolved": ticket_resolved,
            "closed": ticket_closed,
            "trend": ticket_trend,
        },
        "agents": {
            "active": agent_active,
            "total": agent_total,
            "distribution": agent_dist,
        },
        "changes": {
            "pending": change_pending,
        },
        "tools": {
            "total": tool_total,
            "healthy": tool_healthy,
        },
        "recent_activity": recent_audit,
    }

@router.get("/audit")
async def audit_log(
    limit: int = 50,
    actor: str = None,
    action: str = None,
    source: str = None,
    category: str = None,
    level: str = None,
    target: str = None,
    q: str = None,
    ticket_id: int = None,
    agent_id: int = None,
):
    where_clauses = []
    params = []
    param_idx = 1

    if actor:
        where_clauses.append(f"actor ILIKE ${param_idx}")
        params.append(f"%{actor}%")
        param_idx += 1
    if action:
        where_clauses.append(f"action ILIKE ${param_idx}")
        params.append(f"%{action}%")
        param_idx += 1
    if source:
        where_clauses.append(f"source = ${param_idx}")
        params.append(source)
        param_idx += 1
    if category:
        where_clauses.append(f"category ILIKE ${param_idx}")
        params.append(f"%{category}%")
        param_idx += 1
    if level:
        where_clauses.append(f"level = ${param_idx}")
        params.append(level)
        param_idx += 1
    if target:
        where_clauses.append(f"target ILIKE ${param_idx}")
        params.append(f"%{target}%")
        param_idx += 1
    if q:
        where_clauses.append(
            f"(actor ILIKE ${param_idx} OR action ILIKE ${param_idx} OR "
            f"target ILIKE ${param_idx} OR details::text ILIKE ${param_idx})"
        )
        params.append(f"%{q}%")
        param_idx += 1
    if ticket_id:
        where_clauses.append(
            f"(target ILIKE ${param_idx} OR details::text ILIKE ${param_idx} "
            f"OR details::text ILIKE ${param_idx + 1})"
        )
        params.extend([f"%ticket_{ticket_id}%", f"%\"ticket_id\": {ticket_id}%"])
        param_idx += 2
    if agent_id:
        where_clauses.append(
            f"(target ILIKE ${param_idx} OR details::text ILIKE ${param_idx} "
            f"OR details::text ILIKE ${param_idx + 1})"
        )
        params.extend([f"%agent_{agent_id}%", f"%\"agent_id\": {agent_id}%"])
        param_idx += 2

    where_sql = " WHERE " + " AND ".join(where_clauses) if where_clauses else ""

    rows = await fetchall(f"""
        SELECT *
        FROM (
            SELECT id, actor, action, target, details, created_at,
                   'audit' AS source, NULL::text AS category, NULL::text AS level
            FROM audit_log
            UNION ALL
            SELECT id, COALESCE(actor, 'system') AS actor, action, target, details, created_at,
                   'event' AS source, category, level
            FROM event_log
            UNION ALL
            SELECT id,
                   author AS actor,
                   'ticket_note_added' AS action,
                   'ticket_' || ticket_id::text AS target,
                   jsonb_build_object(
                       'ticket_id', ticket_id,
                       'note_id', id,
                       'source', source,
                       'visibility', visibility,
                       'body', body
                   ) AS details,
                   created_at,
                   'note' AS source,
                   'ticket-note' AS category,
                   'info' AS level
            FROM ticket_notes
        ) entries
        {where_sql}
        ORDER BY created_at DESC LIMIT ${param_idx}
    """, *params, limit)
    for row in rows:
        details = _normalize_details(row)
        row["summary"] = _audit_summary(row)
        row["ticket_id"] = _detail_value(details, "ticket_id")
        row["agent_id"] = _detail_value(details, "agent_id")

    return {"audit": rows, "count": len(rows)}

@router.get("/ticket-chart")
async def ticket_chart_data(days: int = 30):
    since = datetime.now() - timedelta(days=days)
    rows = await fetchall("""
        SELECT DATE(created_at) AS date,
               status,
               COUNT(*) AS count
        FROM tickets
        WHERE created_at > $1
        GROUP BY DATE(created_at), status
        ORDER BY date, status
    """, since)
    return {"data": rows, "days": days}

@router.get("/agent-performance")
async def agent_performance():
    rows = await fetchall("""
        SELECT a.id, a.model, a.status,
               EXTRACT(EPOCH FROM (a.finished_at - a.started_at)) AS duration_seconds,
               t.title AS ticket_title
        FROM agents a
        LEFT JOIN tickets t ON a.ticket_id = t.id
        WHERE a.finished_at IS NOT NULL
        ORDER BY a.finished_at DESC
        LIMIT 50
    """)
    return {"agents": rows}

@router.get("/tool-uptime")
async def tool_uptime(days: int = 7):
    since = datetime.now() - timedelta(days=days)
    rows = await fetchall("""
        SELECT t.name,
               COUNT(*) AS total_checks,
               COUNT(*) FILTER (WHERE tc.status = 'healthy') AS healthy_checks,
               ROUND(100.0 * COUNT(*) FILTER (WHERE tc.status = 'healthy') / NULLIF(COUNT(*), 0), 1) AS uptime_pct
        FROM tool_checks tc
        JOIN tools t ON tc.tool_id = t.id
        WHERE tc.timestamp > $1
        GROUP BY t.name
        ORDER BY uptime_pct DESC
    """, since)
    return {"tools": rows, "days": days}
