"""Provider-agnostic ticket facade.

The dashboard owns a canonical ticket record in PostgreSQL. Provider adapters
mirror that record to or from iTop, ServiceNow, Jira, etc. Route handlers should
prefer this service over calling provider-specific modules directly.
"""
from datetime import datetime
from database import fetchall, fetchrow, execute, fetchval, json_dumps
from services.event_logger import log_event
from services.ticket_links import external_ticket_url


def _local_ref():
    return f"LOCAL-{datetime.now().strftime('%Y%m%d%H%M%S%f')}"


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


async def create_ticket(
    title,
    description="",
    ticket_class="UserRequest",
    status="new",
    priority=None,
    provider="local",
    provider_ref=None,
    provider_class=None,
    sync_provider=False,
    created_by="dashboard",
):
    """Create a canonical local ticket.

    `sync_provider` is intentionally explicit. In production this can create an
    iTop/ServiceNow ticket through the active provider, but local/demo flows can
    stay local-only.
    """
    provider_ref = provider_ref or _local_ref()
    provider_class = provider_class or ticket_class
    itop_ref = provider_ref if provider == "itop" else provider_ref
    itop_class = provider_class
    sync_status = "pending_create" if sync_provider else ("local_only" if provider == "local" else "synced")
    synced_at = datetime.now() if sync_status == "synced" else None

    ticket_id = await fetchval("""
        INSERT INTO tickets (
            itop_ref, itop_class, title, description, status, priority,
            provider, provider_ref, provider_class, provider_sync_status,
            synced_at, created_at, updated_at
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, NOW(), NOW())
        ON CONFLICT (itop_ref, itop_class) DO UPDATE SET
            title = EXCLUDED.title,
            description = EXCLUDED.description,
            status = EXCLUDED.status,
            priority = EXCLUDED.priority,
            provider = EXCLUDED.provider,
            provider_ref = EXCLUDED.provider_ref,
            provider_class = EXCLUDED.provider_class,
            provider_sync_status = EXCLUDED.provider_sync_status,
            updated_at = NOW()
        RETURNING id
    """, itop_ref, itop_class, title, description, status, priority,
        provider, provider_ref, provider_class, sync_status, synced_at)

    await log_event("ticket", "info", created_by, "ticket_created",
                    f"ticket_{ticket_id}", {"provider": provider, "sync_provider": sync_provider})

    if sync_provider:
        from services import provider_registry
        provider_result = await provider_registry.create_ticket(provider, ticket_id, {
            "title": title,
            "description": description,
            "ticket_class": ticket_class,
            "provider_class": provider_class,
            "priority": priority,
            "created_by": created_by,
        })
        if provider_result.get("error"):
            await execute("""
                UPDATE tickets
                SET provider_sync_status = 'create_failed',
                    provider_last_error = $1,
                    provider_payload = $2,
                    updated_at = NOW()
                WHERE id = $3
            """, provider_result["error"], json_dumps(provider_result), ticket_id)
            await log_event("sync", "error", created_by, "provider_create_failed",
                            f"ticket_{ticket_id}", provider_result)
        elif provider_result.get("status") == "local_only":
            await execute("""
                UPDATE tickets
                SET provider_sync_status = 'local_only',
                    provider_payload = $1,
                    updated_at = NOW()
                WHERE id = $2
            """, json_dumps(provider_result), ticket_id)
        else:
            await execute("""
                UPDATE tickets
                SET provider = $1,
                    provider_ref = COALESCE($2, provider_ref),
                    provider_class = COALESCE($3, provider_class),
                    provider_url = COALESCE($4, provider_url),
                    provider_sync_status = 'synced',
                    provider_last_error = NULL,
                    provider_payload = $5,
                    synced_at = NOW(),
                    updated_at = NOW()
                WHERE id = $6
            """, provider_result.get("provider") or provider,
                provider_result.get("provider_ref"),
                provider_result.get("provider_class"),
                provider_result.get("provider_url"),
                json_dumps(provider_result),
                ticket_id)
            await log_event("sync", "info", created_by, "provider_create_complete",
                            f"ticket_{ticket_id}", provider_result)
    return await get_ticket(ticket_id)


async def get_ticket(ticket_id):
    ticket = await fetchrow("SELECT * FROM tickets WHERE id = $1", ticket_id)
    if ticket:
        ticket["external_url"] = ticket.get("provider_url") or external_ticket_url(ticket)
    return ticket


async def push_to_provider(ticket_id, provider=None):
    ticket = await fetchrow("SELECT * FROM tickets WHERE id = $1", ticket_id)
    if not ticket:
        return {"error": "Ticket not found"}

    target_provider = provider or ticket.get("provider") or "local"
    from services import provider_registry
    result = await provider_registry.create_ticket(target_provider, ticket_id, {
        "title": ticket.get("title"),
        "description": ticket.get("description"),
        "ticket_class": ticket.get("itop_class"),
        "provider_class": ticket.get("provider_class") or ticket.get("itop_class"),
        "priority": ticket.get("priority"),
        "created_by": "dashboard",
    })
    if result.get("error"):
        await execute("""
            UPDATE tickets
            SET provider = $1,
                provider_sync_status = 'create_failed',
                provider_last_error = $2,
                provider_payload = $3,
                updated_at = NOW()
            WHERE id = $4
        """, target_provider, result["error"], json_dumps(result), ticket_id)
        await log_event("sync", "error", "dashboard", "provider_push_failed",
                        f"ticket_{ticket_id}", result)
        return result

    if result.get("status") == "local_only":
        await execute("""
            UPDATE tickets
            SET provider = $1,
                provider_sync_status = 'local_only',
                provider_payload = $2,
                updated_at = NOW()
            WHERE id = $3
        """, target_provider, json_dumps(result), ticket_id)
    else:
        await execute("""
            UPDATE tickets
            SET provider = $1,
                provider_ref = COALESCE($2, provider_ref),
                provider_class = COALESCE($3, provider_class),
                provider_url = COALESCE($4, provider_url),
                provider_sync_status = 'synced',
                provider_last_error = NULL,
                provider_payload = $5,
                synced_at = NOW(),
                updated_at = NOW()
            WHERE id = $6
        """, result.get("provider") or target_provider,
            result.get("provider_ref"),
            result.get("provider_class"),
            result.get("provider_url"),
            json_dumps(result),
            ticket_id)

    await log_event("sync", "info", "dashboard", "provider_push_complete",
                    f"ticket_{ticket_id}", result)
    return result


async def add_note(ticket_id, body, author="dashboard", source="dashboard", visibility="internal", external_ref=None):
    if not await fetchrow("SELECT id FROM tickets WHERE id = $1", ticket_id):
        return {"error": "Ticket not found"}
    note_id = await fetchval("""
        INSERT INTO ticket_notes (ticket_id, source, author, body, visibility, external_ref)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id
    """, ticket_id, source, author, body, visibility, external_ref)
    await execute("UPDATE tickets SET updated_at = NOW() WHERE id = $1", ticket_id)
    await log_event("ticket", "info", author, "ticket_note_added",
                    f"ticket_{ticket_id}", {"note_id": note_id, "visibility": visibility})
    return {"id": note_id, "ticket_id": ticket_id, "status": "created"}


async def add_attachment_metadata(
    ticket_id,
    filename,
    content_type=None,
    storage_ref=None,
    sha256=None,
    size_bytes=None,
    note_id=None,
    metadata=None,
):
    if not await fetchrow("SELECT id FROM tickets WHERE id = $1", ticket_id):
        return {"error": "Ticket not found"}
    attachment_id = await fetchval("""
        INSERT INTO ticket_attachments (
            ticket_id, note_id, filename, content_type, storage_ref,
            sha256, size_bytes, metadata
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        RETURNING id
    """, ticket_id, note_id, filename, content_type, storage_ref,
        sha256, size_bytes, json_dumps(metadata or {}))
    await log_event("ticket", "info", "dashboard", "ticket_attachment_added",
                    f"ticket_{ticket_id}", {"attachment_id": attachment_id, "filename": filename})
    return {"id": attachment_id, "ticket_id": ticket_id, "status": "created"}


async def get_context(ticket_id):
    ticket = await get_ticket(ticket_id)
    if not ticket:
        return {"error": "Ticket not found"}

    notes = await fetchall(
        "SELECT * FROM ticket_notes WHERE ticket_id = $1 ORDER BY created_at ASC",
        ticket_id,
    )
    attachments = await fetchall(
        "SELECT * FROM ticket_attachments WHERE ticket_id = $1 ORDER BY created_at ASC",
        ticket_id,
    )
    changes = await fetchall(
        "SELECT * FROM change_requests WHERE ticket_id = $1 ORDER BY requested_at DESC",
        ticket_id,
    )
    tasks = await fetchall(
        "SELECT * FROM agent_tasks WHERE ticket_id = $1 ORDER BY created_at DESC LIMIT 20",
        ticket_id,
    )
    postmortems = await fetchall(
        "SELECT * FROM postmortems WHERE ticket_id = $1 ORDER BY created_at DESC",
        ticket_id,
    )
    related = await fetchall("""
        SELECT id, itop_ref, itop_class, title, status, provider, provider_ref, updated_at
        FROM tickets
        WHERE id <> $1
          AND (
            lower(title) = lower($2)
            OR itop_class = $3
            OR provider_class = $4
          )
        ORDER BY updated_at DESC
        LIMIT 10
    """, ticket_id, ticket.get("title") or "", ticket.get("itop_class"), ticket.get("provider_class"))
    articles = await fetchall("""
        SELECT * FROM knowledge_articles
        WHERE enabled = true
          AND (
            category IS NULL
            OR category ILIKE $1
            OR title ILIKE $2
            OR body ILIKE $2
          )
        ORDER BY updated_at DESC
        LIMIT 10
    """, f"%{ticket.get('itop_class') or ''}%", f"%{(ticket.get('title') or '')[:80]}%")
    workflows = await fetchall("""
        SELECT * FROM agent_workflows
        WHERE status IN ('draft', 'tested', 'approved', 'active')
          AND (ticket_class IS NULL OR ticket_class = $1 OR ticket_class = $2)
        ORDER BY updated_at DESC
        LIMIT 10
    """, ticket.get("itop_class"), ticket.get("provider_class"))
    skills = await fetchall(
        "SELECT id, name, description, category, prompt_template FROM agent_skills "
        "WHERE enabled = true AND assigned_to_all = true ORDER BY category, name"
    )

    return {
        "ticket": ticket,
        "notes": notes,
        "attachments": attachments,
        "change_requests": changes,
        "tasks": tasks,
        "postmortems": postmortems,
        "related_tickets": related,
        "knowledge_articles": articles,
        "workflows": workflows,
        "skills": skills,
    }


async def create_knowledge_article(title, body, category=None, source="dashboard", tags=None, external_ref=None):
    article_id = await fetchval("""
        INSERT INTO knowledge_articles (title, body, category, source, tags, external_ref)
        VALUES ($1, $2, $3, $4, $5, $6)
        RETURNING id
    """, title, body, category, source, json_dumps(_as_list(tags)), external_ref)
    await log_event("knowledge", "info", source, "knowledge_article_created",
                    f"article_{article_id}", {"category": category})
    return {"id": article_id, "status": "created"}
