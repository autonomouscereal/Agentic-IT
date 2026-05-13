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


def _target_query_terms(q):
    value = (q or "").strip().lower()
    if "_" not in value:
        return []
    prefix, raw_id = value.rsplit("_", 1)
    if not raw_id.isdigit():
        return []
    key_map = {
        "ticket": "ticket_id",
        "agent": "agent_id",
        "change": "change_id",
        "postmortem": "postmortem_id",
        "workflow": "workflow_id",
        "workflow_run": "workflow_run_id",
        "cicd_run": "run_id",
    }
    key = key_map.get(prefix)
    if not key:
        return []
    return [key, raw_id]

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
        target_terms = _target_query_terms(q)
        where_clauses.append(
            f"(actor ILIKE ${param_idx} OR action ILIKE ${param_idx} OR "
            f"target ILIKE ${param_idx} OR details::text ILIKE ${param_idx}"
            + (f" OR (details->>${param_idx + 1}) = ${param_idx + 2}" if target_terms else "")
            + ")"
        )
        params.append(f"%{q}%")
        if target_terms:
            params.extend(target_terms)
            param_idx += 3
        else:
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


@router.get("/ops-metrics")
async def ops_metrics():
    """Return operational metrics for agents, gates, SLAs, workflows, CI/CD, and tools."""
    agent_rows = await fetchall("""
        WITH task_gate_wait AS (
            SELECT at.id AS task_id,
                   COALESCE(SUM(
                       GREATEST(0, EXTRACT(EPOCH FROM (
                           COALESCE(cr.approved_at, at.completed_at, NOW()) - COALESCE(cr.requested_at, NOW())
                       )))
                   ), 0) AS gate_wait_seconds
            FROM agent_tasks at
            LEFT JOIN change_requests cr
              ON cr.agent_id = at.agent_id
             AND cr.ticket_id = at.ticket_id
             AND cr.requested_at >= COALESCE(at.started_at, at.created_at)
             AND cr.requested_at <= COALESCE(at.completed_at, NOW())
             AND cr.status IN ('pending', 'approved', 'completed', 'rejected')
            GROUP BY at.id
        )
        SELECT at.task_type,
               COUNT(*) AS total_tasks,
               COUNT(*) FILTER (WHERE at.status = 'completed') AS completed_tasks,
               ROUND(AVG(GREATEST(0, EXTRACT(EPOCH FROM (
                   COALESCE(at.completed_at, NOW()) - COALESCE(at.started_at, at.created_at, NOW())
               )) - COALESCE(tgw.gate_wait_seconds, 0)))::numeric, 1) AS avg_work_seconds,
               ROUND(percentile_cont(0.5) WITHIN GROUP (ORDER BY GREATEST(0, EXTRACT(EPOCH FROM (
                   COALESCE(at.completed_at, NOW()) - COALESCE(at.started_at, at.created_at, NOW())
               )) - COALESCE(tgw.gate_wait_seconds, 0)))::numeric, 1) AS p50_work_seconds,
               ROUND(percentile_cont(0.95) WITHIN GROUP (ORDER BY GREATEST(0, EXTRACT(EPOCH FROM (
                   COALESCE(at.completed_at, NOW()) - COALESCE(at.started_at, at.created_at, NOW())
               )) - COALESCE(tgw.gate_wait_seconds, 0)))::numeric, 1) AS p95_work_seconds,
               ROUND(AVG(COALESCE(tgw.gate_wait_seconds, 0))::numeric, 1) AS avg_gate_wait_seconds
        FROM agent_tasks at
        LEFT JOIN task_gate_wait tgw ON tgw.task_id = at.id
        WHERE at.created_at > NOW() - INTERVAL '30 days'
        GROUP BY at.task_type
        ORDER BY completed_tasks DESC, total_tasks DESC
        LIMIT 12
    """)
    agent_summary = await fetchrow("""
        WITH task_gate_wait AS (
            SELECT at.id AS task_id,
                   COALESCE(SUM(
                       GREATEST(0, EXTRACT(EPOCH FROM (
                           COALESCE(cr.approved_at, at.completed_at, NOW()) - COALESCE(cr.requested_at, NOW())
                       )))
                   ), 0) AS gate_wait_seconds
            FROM agent_tasks at
            LEFT JOIN change_requests cr
              ON cr.agent_id = at.agent_id
             AND cr.ticket_id = at.ticket_id
             AND cr.requested_at >= COALESCE(at.started_at, at.created_at)
             AND cr.requested_at <= COALESCE(at.completed_at, NOW())
             AND cr.status IN ('pending', 'approved', 'completed', 'rejected')
            GROUP BY at.id
        )
        SELECT COUNT(*) AS tasks,
               COUNT(*) FILTER (WHERE at.status = 'completed') AS completed,
               ROUND(AVG(GREATEST(0, EXTRACT(EPOCH FROM (
                   COALESCE(at.completed_at, NOW()) - COALESCE(at.started_at, at.created_at, NOW())
               )) - COALESCE(tgw.gate_wait_seconds, 0)))::numeric, 1) AS avg_work_seconds,
               ROUND(AVG(COALESCE(tgw.gate_wait_seconds, 0))::numeric, 1) AS avg_gate_wait_seconds
        FROM agent_tasks at
        LEFT JOIN task_gate_wait tgw ON tgw.task_id = at.id
        WHERE at.created_at > NOW() - INTERVAL '30 days'
    """)
    sla = await fetchrow("""
        WITH ticket_sla AS (
            SELECT id, status, priority, created_at, updated_at,
                   CASE
                     WHEN upper(COALESCE(priority::text, '')) IN ('P1', '1', 'CRITICAL') THEN 4
                     WHEN upper(COALESCE(priority::text, '')) IN ('P2', '2', 'HIGH') THEN 8
                     WHEN upper(COALESCE(priority::text, '')) IN ('P3', '3', 'MEDIUM') THEN 24
                     ELSE 72
                   END AS sla_hours,
                   CASE WHEN lower(status) IN ('resolved', 'closed', 'closed/resolved', 'implemented') THEN updated_at ELSE NOW() END AS end_at
            FROM tickets
            WHERE created_at > NOW() - INTERVAL '30 days'
        )
        SELECT COUNT(*) AS tickets,
               COUNT(*) FILTER (WHERE lower(status) NOT IN ('resolved', 'closed', 'closed/resolved', 'implemented')) AS open_tickets,
               COUNT(*) FILTER (WHERE end_at <= created_at + (sla_hours || ' hours')::interval) AS within_sla,
               COUNT(*) FILTER (WHERE end_at > created_at + (sla_hours || ' hours')::interval) AS breached_sla,
               COUNT(*) FILTER (
                   WHERE lower(status) NOT IN ('resolved', 'closed', 'closed/resolved', 'implemented')
                     AND end_at > created_at + ((sla_hours * 0.8) || ' hours')::interval
                     AND end_at <= created_at + (sla_hours || ' hours')::interval
               ) AS at_risk,
               ROUND(100.0 * COUNT(*) FILTER (WHERE end_at <= created_at + (sla_hours || ' hours')::interval) / NULLIF(COUNT(*), 0), 1) AS compliance_pct
        FROM ticket_sla
    """)
    gates = await fetchrow("""
        SELECT COUNT(*) AS total,
               COUNT(*) FILTER (WHERE status = 'pending') AS pending,
               COUNT(*) FILTER (WHERE status = 'approved') AS approved,
               COUNT(*) FILTER (WHERE status = 'completed') AS completed,
               COUNT(*) FILTER (WHERE status = 'rejected') AS rejected,
               ROUND(AVG(GREATEST(0, EXTRACT(EPOCH FROM (
                   COALESCE(approved_at, NOW()) - COALESCE(requested_at, NOW())
               ))))::numeric, 1) AS avg_wait_seconds
        FROM change_requests
        WHERE requested_at > NOW() - INTERVAL '30 days'
    """)
    workflow = await fetchrow("""
        SELECT COUNT(*) AS total,
               COUNT(*) FILTER (WHERE status IN ('active', 'approved')) AS active,
               COUNT(*) FILTER (WHERE status = 'tested') AS tested,
               COUNT(*) FILTER (WHERE status IN ('draft', 'ready_for_review')) AS review_queue
        FROM agent_workflows
    """)
    workflow_runs = await fetchrow("""
        SELECT COUNT(*) AS total,
               COUNT(*) FILTER (WHERE status IN ('completed', 'passed')) AS completed,
               COUNT(*) FILTER (WHERE status IN ('failed', 'error')) AS failed
        FROM workflow_runs
        WHERE created_at > NOW() - INTERVAL '30 days'
    """)
    cicd = await fetchall("""
        SELECT status, COUNT(*) AS count
        FROM cicd_security_runs
        WHERE created_at > NOW() - INTERVAL '30 days'
        GROUP BY status
        ORDER BY count DESC
    """)
    auto_assignment = await fetchall("""
        SELECT action, COUNT(*) AS count
        FROM event_log
        WHERE category = 'agent'
          AND action LIKE 'auto_assignment%'
          AND created_at > NOW() - INTERVAL '30 days'
        GROUP BY action
        ORDER BY count DESC
    """)
    tool_health = await fetchrow("""
        SELECT COUNT(*) AS tools,
               COUNT(*) FILTER (WHERE COALESCE(tc.status, t.status, 'unknown') = 'healthy') AS healthy,
               COUNT(*) FILTER (WHERE COALESCE(tc.status, t.status, 'unknown') = 'down') AS down,
               COUNT(*) FILTER (WHERE COALESCE(tc.status, t.status, 'unknown') NOT IN ('healthy', 'down')) AS degraded_or_unknown
        FROM tools t
        LEFT JOIN LATERAL (
            SELECT status FROM tool_checks
            WHERE tool_id = t.id
            ORDER BY timestamp DESC
            LIMIT 1
        ) tc ON true
        WHERE lower(t.name) <> 'comfyui'
    """)
    return {
        "agent_summary": agent_summary or {},
        "agent_by_task_type": agent_rows,
        "sla": sla or {},
        "approval_gates": gates or {},
        "workflows": {**(workflow or {}), "runs": workflow_runs or {}},
        "cicd": cicd,
        "auto_assignment": auto_assignment,
        "tool_health": tool_health or {},
    }

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
