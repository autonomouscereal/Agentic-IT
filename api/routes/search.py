from fastapi import APIRouter, Query
try:
    from fastapi import Request
except ImportError:  # unit-test stubs do not expose Request
    class Request:
        pass

from database import fetchall
from services import access_control

router = APIRouter(prefix="/api/search", tags=["search"])


def _patterns(query):
    terms = [part for part in str(query or "").strip().split() if part]
    if not terms:
        return []
    return [f"%{term[:80]}%" for term in terms[:8]]


def _has(subject, permission):
    return access_control.capability_matches(subject.get("capabilities") or [], permission)


def _snippet(*values, max_len=240):
    text = " ".join(str(value or "").replace("\n", " ").strip() for value in values if value)
    text = " ".join(text.split())
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def _item(kind, row, title, snippet, url, updated_at=None, status=None, metadata=None):
    return {
        "type": kind,
        "id": row.get("id"),
        "title": title,
        "snippet": snippet,
        "url": url,
        "updated_at": updated_at or row.get("updated_at") or row.get("created_at"),
        "status": status,
        "metadata": metadata or {},
    }


async def _ticket_results(patterns, subject, limit):
    params = [patterns]
    scope_sql, scope_params, next_idx = access_control.ticket_filter_clause(subject, "t", 2)
    params.extend(scope_params)
    where = """
        (
            t.title ILIKE ANY($1::text[])
            OR COALESCE(t.description, '') ILIKE ANY($1::text[])
            OR COALESCE(t.itop_ref, '') ILIKE ANY($1::text[])
            OR COALESCE(t.provider_ref, '') ILIKE ANY($1::text[])
            OR t.id::text ILIKE ANY($1::text[])
        )
    """
    if scope_sql:
        where += f" AND {scope_sql}"
    params.append(limit)
    rows = await fetchall(f"""
        SELECT t.id, t.title, t.description, t.status, t.priority, t.itop_class,
               t.provider, t.provider_ref, t.updated_at
        FROM tickets t
        WHERE {where}
        ORDER BY t.updated_at DESC
        LIMIT ${next_idx}
    """, *params)
    return [
        _item(
            "ticket",
            row,
            f"Ticket #{row['id']}: {row.get('title') or ''}",
            _snippet(row.get("description")),
            f"#tickets:{row['id']}",
            status=row.get("status"),
            metadata={
                "priority": row.get("priority"),
                "class": row.get("itop_class"),
                "provider": row.get("provider"),
                "provider_ref": row.get("provider_ref"),
            },
        )
        for row in rows
    ]


async def _ticket_note_results(patterns, subject, limit):
    params = [patterns]
    scope_sql, scope_params, next_idx = access_control.ticket_filter_clause(subject, "t", 2)
    params.extend(scope_params)
    where = """
        (
            n.body ILIKE ANY($1::text[])
            OR n.author ILIKE ANY($1::text[])
            OR n.source ILIKE ANY($1::text[])
            OR t.title ILIKE ANY($1::text[])
        )
    """
    if scope_sql:
        where += f" AND {scope_sql}"
    params.append(limit)
    rows = await fetchall(f"""
        SELECT n.id, n.ticket_id, n.source, n.author, n.body, n.visibility,
               n.created_at, t.title AS ticket_title, t.status AS ticket_status
        FROM ticket_notes n
        JOIN tickets t ON t.id = n.ticket_id
        WHERE {where}
        ORDER BY n.created_at DESC
        LIMIT ${next_idx}
    """, *params)
    return [
        _item(
            "ticket_note",
            row,
            f"Ticket #{row['ticket_id']} note by {row.get('author') or 'unknown'}",
            _snippet(row.get("body")),
            f"#tickets:{row['ticket_id']}",
            updated_at=row.get("created_at"),
            status=row.get("ticket_status"),
            metadata={
                "ticket_id": row.get("ticket_id"),
                "ticket_title": row.get("ticket_title"),
                "source": row.get("source"),
                "visibility": row.get("visibility"),
            },
        )
        for row in rows
    ]


async def _simple_results(kind, query_sql, patterns, limit, mapper):
    rows = await fetchall(query_sql, patterns, limit)
    return [mapper(row) for row in rows]


@router.get("/global")
async def global_search(
    q: str = Query(..., min_length=2, max_length=160),
    limit: int = Query(40, ge=1, le=100),
    request: Request = None,
):
    subject = access_control.subject_from_request(request)
    patterns = _patterns(q)
    per_type_limit = max(3, min(12, limit // 4 if limit >= 12 else limit))
    results = []

    if _has(subject, "tickets:read"):
        results.extend(await _ticket_results(patterns, subject, per_type_limit))
        results.extend(await _ticket_note_results(patterns, subject, per_type_limit))

    if _has(subject, "agents:read"):
        results.extend(await _simple_results(
            "agent",
            """
            SELECT a.id, a.ticket_id, a.model, a.status, a.started_at, a.finished_at,
                   t.title AS ticket_title
            FROM agents a
            LEFT JOIN tickets t ON t.id = a.ticket_id
            WHERE a.id::text ILIKE ANY($1::text[])
               OR COALESCE(a.model, '') ILIKE ANY($1::text[])
               OR COALESCE(a.status, '') ILIKE ANY($1::text[])
               OR COALESCE(t.title, '') ILIKE ANY($1::text[])
            ORDER BY COALESCE(a.finished_at, a.started_at) DESC
            LIMIT $2
            """,
            patterns,
            per_type_limit,
            lambda row: _item(
                "agent",
                row,
                f"Agent #{row['id']} {row.get('status') or ''}",
                _snippet(row.get("model"), row.get("ticket_title")),
                "#agents",
                updated_at=row.get("finished_at") or row.get("started_at"),
                status=row.get("status"),
                metadata={"ticket_id": row.get("ticket_id")},
            ),
        ))

    if _has(subject, "changes:read"):
        results.extend(await _simple_results(
            "change",
            """
            SELECT id, ticket_id, action, target, reason, status, risk_level, requested_at, approved_at
            FROM change_requests
            WHERE action ILIKE ANY($1::text[])
               OR target ILIKE ANY($1::text[])
               OR COALESCE(reason, '') ILIKE ANY($1::text[])
               OR id::text ILIKE ANY($1::text[])
            ORDER BY requested_at DESC
            LIMIT $2
            """,
            patterns,
            per_type_limit,
            lambda row: _item(
                "change",
                row,
                f"Change #{row['id']}: {row.get('action') or ''}",
                _snippet(row.get("reason"), row.get("target")),
                "#changes",
                updated_at=row.get("approved_at") or row.get("requested_at"),
                status=row.get("status"),
                metadata={"ticket_id": row.get("ticket_id"), "risk_level": row.get("risk_level")},
            ),
        ))

    if _has(subject, "postmortems:read"):
        results.extend(await _simple_results(
            "postmortem",
            """
            SELECT id, ticket_id, status, summary, improvements, workflow_proposal, created_at, updated_at
            FROM postmortems
            WHERE COALESCE(summary, '') ILIKE ANY($1::text[])
               OR COALESCE(improvements, '') ILIKE ANY($1::text[])
               OR COALESCE(workflow_proposal, '') ILIKE ANY($1::text[])
               OR id::text ILIKE ANY($1::text[])
            ORDER BY updated_at DESC
            LIMIT $2
            """,
            patterns,
            per_type_limit,
            lambda row: _item(
                "postmortem",
                row,
                f"Postmortem #{row['id']}",
                _snippet(row.get("summary"), row.get("improvements")),
                f"#postmortems:{row['id']}",
                status=row.get("status"),
                metadata={"ticket_id": row.get("ticket_id")},
            ),
        ))

    if _has(subject, "workflows:read"):
        results.extend(await _simple_results(
            "workflow",
            """
            SELECT id, name, description, ticket_class, trigger_type, status, workflow_key, updated_at
            FROM agent_workflows
            WHERE name ILIKE ANY($1::text[])
               OR COALESCE(description, '') ILIKE ANY($1::text[])
               OR COALESCE(workflow_key, '') ILIKE ANY($1::text[])
               OR id::text ILIKE ANY($1::text[])
            ORDER BY updated_at DESC
            LIMIT $2
            """,
            patterns,
            per_type_limit,
            lambda row: _item(
                "workflow",
                row,
                f"Workflow #{row['id']}: {row.get('name') or ''}",
                _snippet(row.get("description"), row.get("workflow_key")),
                f"#workflows:{row['id']}",
                status=row.get("status"),
                metadata={"ticket_class": row.get("ticket_class"), "trigger_type": row.get("trigger_type")},
            ),
        ))

    if _has(subject, "cicd:read"):
        results.extend(await _simple_results(
            "cicd",
            """
            SELECT id, provider, repo_ref, branch, status, summary, ticket_id, change_id, created_at
            FROM cicd_security_runs
            WHERE repo_ref ILIKE ANY($1::text[])
               OR COALESCE(branch, '') ILIKE ANY($1::text[])
               OR COALESCE(summary, '') ILIKE ANY($1::text[])
               OR id::text ILIKE ANY($1::text[])
            ORDER BY created_at DESC
            LIMIT $2
            """,
            patterns,
            per_type_limit,
            lambda row: _item(
                "cicd",
                row,
                f"CI/CD Run #{row['id']}: {row.get('repo_ref') or ''}",
                _snippet(row.get("summary"), row.get("branch")),
                f"#cicd:{row['id']}",
                status=row.get("status"),
                metadata={"ticket_id": row.get("ticket_id"), "change_id": row.get("change_id")},
            ),
        ))

    if _has(subject, "tools:read"):
        results.extend(await _simple_results(
            "tool",
            """
            SELECT id, name, type, host, port, status, description, updated_at, created_at
            FROM tools
            WHERE name ILIKE ANY($1::text[])
               OR type ILIKE ANY($1::text[])
               OR COALESCE(description, '') ILIKE ANY($1::text[])
            ORDER BY updated_at DESC NULLS LAST, name ASC
            LIMIT $2
            """,
            patterns,
            per_type_limit,
            lambda row: _item(
                "tool",
                row,
                f"Tool: {row.get('name') or ''}",
                _snippet(row.get("description"), row.get("host")),
                "#tools",
                status=row.get("status"),
                metadata={"type": row.get("type"), "host": row.get("host"), "port": row.get("port")},
            ),
        ))

    if _has(subject, "audit:read"):
        results.extend(await _simple_results(
            "audit",
            """
            SELECT id, actor, action, target, created_at
            FROM audit_log
            WHERE actor ILIKE ANY($1::text[])
               OR action ILIKE ANY($1::text[])
               OR COALESCE(target, '') ILIKE ANY($1::text[])
               OR id::text ILIKE ANY($1::text[])
            ORDER BY created_at DESC
            LIMIT $2
            """,
            patterns,
            per_type_limit,
            lambda row: _item(
                "audit",
                row,
                f"Audit #{row['id']}: {row.get('action') or ''}",
                _snippet(row.get("actor"), row.get("target")),
                f"#audit:{row['id']}",
                updated_at=row.get("created_at"),
                metadata={"actor": row.get("actor"), "target": row.get("target")},
            ),
        ))

    results.sort(key=lambda item: str(item.get("updated_at") or ""), reverse=True)
    trimmed = results[:limit]
    grouped = {}
    for item in trimmed:
        grouped[item["type"]] = grouped.get(item["type"], 0) + 1
    return {
        "query": q,
        "total": len(trimmed),
        "available_total": len(results),
        "groups": grouped,
        "results": trimmed,
    }
