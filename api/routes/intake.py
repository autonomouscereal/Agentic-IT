from fastapi import APIRouter, Body, Query
import json
import re

from database import fetchall, fetchrow, fetchval, execute, json_dumps
from services import ticket_service
from services.event_logger import log_event

router = APIRouter(prefix="/api/intake", tags=["intake"])


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else [parsed]
        except json.JSONDecodeError:
            return [value]
    return [value]


def _json_value(value, default):
    if value is None:
        return default
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return default
    return value


def _tokens(text):
    return [part for part in re.split(r"[^a-z0-9._@/-]+", (text or "").lower()) if len(part) >= 4]


def _score_rule(rule, text):
    keywords = _as_list(rule.get("keywords"))
    if not keywords:
        return 0
    score = 0
    for keyword in keywords:
        keyword_text = str(keyword).lower().strip()
        if keyword_text and keyword_text in text:
            score += max(1, len(keyword_text.split()))
    return score


async def _best_rule(message, title=None, category=None):
    text = " ".join([title or "", category or "", message or ""]).lower()
    rules = await fetchall("""
        SELECT * FROM service_raci_rules
        WHERE enabled = true
        ORDER BY id ASC
    """)
    if not rules:
        return None, 0
    scored = [(rule, _score_rule(rule, text)) for rule in rules]
    scored.sort(key=lambda item: item[1], reverse=True)
    best, score = scored[0]
    if score <= 0:
        for rule in rules:
            if rule.get("intent") == "general":
                return rule, 0
    return best, score


async def _correlate(message, title=None, rule=None):
    terms = _tokens(" ".join([title or "", message or ""]))[:8]
    patterns = [f"%{term}%" for term in terms]
    related_tickets = []
    knowledge = []
    if patterns:
        related_tickets = await fetchall("""
            SELECT id, itop_ref, itop_class, title, status, provider, provider_ref, updated_at
            FROM tickets
            WHERE title ILIKE ANY($1::text[])
               OR description ILIKE ANY($1::text[])
            ORDER BY updated_at DESC
            LIMIT 8
        """, patterns)
        knowledge = await fetchall("""
            SELECT id, title, category, source, tags, updated_at
            FROM knowledge_articles
            WHERE enabled = true
              AND (title ILIKE ANY($1::text[]) OR body ILIKE ANY($1::text[]))
            ORDER BY updated_at DESC
            LIMIT 8
        """, patterns)

    tags = _json_value(rule.get("knowledge_tags") if rule else None, [])
    if tags:
        tagged = await fetchall("""
            SELECT id, title, category, source, tags, updated_at
            FROM knowledge_articles
            WHERE enabled = true
              AND tags ?| $1::text[]
            ORDER BY updated_at DESC
            LIMIT 8
        """, [str(tag) for tag in tags])
        seen = {item["id"] for item in knowledge}
        knowledge.extend([item for item in tagged if item["id"] not in seen])

    return {
        "related_tickets": related_tickets[:8],
        "knowledge_articles": knowledge[:8],
    }


def _classification(rule, score, correlation):
    if not rule:
        return {
            "intent": "general",
            "confidence": 0.1,
            "ticket_class": "UserRequest",
            "priority": "P4",
            "assignment_group": "Business Applications",
            "approval_required": False,
            "raci": {},
            "related_tickets": [],
            "knowledge_articles": [],
        }
    keywords = _as_list(rule.get("keywords"))
    confidence = min(0.95, 0.35 + (score * 0.12)) if keywords else 0.3
    return {
        "rule_id": rule.get("id"),
        "rule_name": rule.get("name"),
        "intent": rule.get("intent"),
        "confidence": confidence,
        "ticket_class": rule.get("ticket_class") or "UserRequest",
        "priority": rule.get("priority") or "P3",
        "assignment_group": rule.get("assignment_group"),
        "approval_required": bool(rule.get("approval_required")),
        "approval_action": rule.get("approval_action"),
        "risk_level": rule.get("risk_level") or "low",
        "auto_assign_agent": bool(rule.get("auto_assign_agent")),
        "auto_agent_model": rule.get("auto_agent_model"),
        "auto_agent_prompt": rule.get("auto_agent_prompt"),
        "raci": {
            "responsible": rule.get("responsible"),
            "accountable": rule.get("accountable"),
            "consulted": _json_value(rule.get("consulted"), []),
            "informed": _json_value(rule.get("informed"), []),
        },
        "knowledge_tags": _json_value(rule.get("knowledge_tags"), []),
        "related_tickets": correlation.get("related_tickets", []),
        "knowledge_articles": correlation.get("knowledge_articles", []),
    }


@router.get("/raci")
async def get_raci():
    groups = await fetchall("""
        SELECT * FROM service_groups WHERE enabled = true ORDER BY name ASC
    """)
    rules = await fetchall("""
        SELECT * FROM service_raci_rules WHERE enabled = true ORDER BY id ASC
    """)
    return {"groups": groups, "rules": rules}


@router.post("/raci/groups")
async def create_group(body: dict = Body({})):
    name = (body or {}).get("name")
    if not name:
        return {"error": "name is required"}
    group_id = await fetchval("""
        INSERT INTO service_groups (name, description, default_assignee, risk_level, enabled)
        VALUES ($1, $2, $3, $4, COALESCE($5, true))
        ON CONFLICT (name) DO UPDATE SET
            description = EXCLUDED.description,
            default_assignee = EXCLUDED.default_assignee,
            risk_level = EXCLUDED.risk_level,
            enabled = EXCLUDED.enabled,
            updated_at = NOW()
        RETURNING id
    """, name, (body or {}).get("description"), (body or {}).get("default_assignee"),
        (body or {}).get("risk_level") or "low", (body or {}).get("enabled", True))
    await log_event("intake", "info", "dashboard", "raci_group_saved", f"group_{group_id}", {"name": name})
    return {"id": group_id, "status": "saved"}


@router.put("/raci/groups/{group_id}")
async def update_group(group_id: int, body: dict = Body({})):
    fields = []
    params = []
    idx = 1
    for key in ("name", "description", "default_assignee", "risk_level", "enabled"):
        if key in (body or {}):
            fields.append(f"{key} = ${idx}")
            params.append((body or {}).get(key))
            idx += 1
    if not fields:
        return {"error": "No fields to update"}
    fields.append("updated_at = NOW()")
    params.append(group_id)
    await execute(f"UPDATE service_groups SET {', '.join(fields)} WHERE id = ${idx}", *params)
    await log_event("intake", "info", "dashboard", "raci_group_updated", f"group_{group_id}", {"fields": list((body or {}).keys())})
    return {"id": group_id, "status": "updated"}


@router.delete("/raci/groups/{group_id}")
async def delete_group(group_id: int):
    await execute("UPDATE service_groups SET enabled = false, updated_at = NOW() WHERE id = $1", group_id)
    await log_event("intake", "warning", "dashboard", "raci_group_disabled", f"group_{group_id}")
    return {"id": group_id, "status": "disabled"}


@router.post("/raci/rules")
async def create_rule(body: dict = Body({})):
    name = (body or {}).get("name")
    if not name:
        return {"error": "name is required"}
    rule_id = await fetchval("""
        INSERT INTO service_raci_rules (
            name, intent, keywords, ticket_class, priority, assignment_group,
            responsible, accountable, consulted, informed, approval_required,
            approval_action, risk_level, knowledge_tags, auto_assign_agent,
            auto_agent_model, auto_agent_prompt, enabled
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14,
                COALESCE($15, false), $16, $17, COALESCE($18, true))
        ON CONFLICT (name) DO UPDATE SET
            intent = EXCLUDED.intent,
            keywords = EXCLUDED.keywords,
            ticket_class = EXCLUDED.ticket_class,
            priority = EXCLUDED.priority,
            assignment_group = EXCLUDED.assignment_group,
            responsible = EXCLUDED.responsible,
            accountable = EXCLUDED.accountable,
            consulted = EXCLUDED.consulted,
            informed = EXCLUDED.informed,
            approval_required = EXCLUDED.approval_required,
            approval_action = EXCLUDED.approval_action,
            risk_level = EXCLUDED.risk_level,
            knowledge_tags = EXCLUDED.knowledge_tags,
            auto_assign_agent = EXCLUDED.auto_assign_agent,
            auto_agent_model = EXCLUDED.auto_agent_model,
            auto_agent_prompt = EXCLUDED.auto_agent_prompt,
            enabled = EXCLUDED.enabled,
            updated_at = NOW()
        RETURNING id
    """, name, (body or {}).get("intent") or "general",
        json_dumps(_as_list((body or {}).get("keywords"))),
        (body or {}).get("ticket_class") or "UserRequest",
        (body or {}).get("priority") or "P3",
        (body or {}).get("assignment_group") or "Business Applications",
        (body or {}).get("responsible") or "Business Applications",
        (body or {}).get("accountable") or "Service Desk Manager",
        json_dumps(_as_list((body or {}).get("consulted"))),
        json_dumps(_as_list((body or {}).get("informed"))),
        bool((body or {}).get("approval_required", False)),
        (body or {}).get("approval_action"),
        (body or {}).get("risk_level") or "low",
        json_dumps(_as_list((body or {}).get("knowledge_tags"))),
        bool((body or {}).get("auto_assign_agent", False)),
        (body or {}).get("auto_agent_model") or "deepseek/deepseek-v4-flash",
        (body or {}).get("auto_agent_prompt"),
        (body or {}).get("enabled", True))
    await log_event("intake", "info", "dashboard", "raci_rule_saved", f"rule_{rule_id}", {"name": name})
    return {"id": rule_id, "status": "saved"}


@router.put("/raci/rules/{rule_id}")
async def update_rule(rule_id: int, body: dict = Body({})):
    json_fields = {"keywords", "consulted", "informed", "knowledge_tags"}
    allowed = {
        "name", "intent", "keywords", "ticket_class", "priority", "assignment_group",
        "responsible", "accountable", "consulted", "informed", "approval_required",
        "approval_action", "risk_level", "knowledge_tags", "auto_assign_agent",
        "auto_agent_model", "auto_agent_prompt", "enabled",
    }
    fields = []
    params = []
    idx = 1
    for key in allowed:
        if key in (body or {}):
            fields.append(f"{key} = ${idx}")
            value = _as_list((body or {}).get(key)) if key in json_fields else (body or {}).get(key)
            params.append(json_dumps(value) if key in json_fields else value)
            idx += 1
    if not fields:
        return {"error": "No fields to update"}
    fields.append("updated_at = NOW()")
    params.append(rule_id)
    await execute(f"UPDATE service_raci_rules SET {', '.join(fields)} WHERE id = ${idx}", *params)
    await log_event("intake", "info", "dashboard", "raci_rule_updated", f"rule_{rule_id}", {"fields": list((body or {}).keys())})
    return {"id": rule_id, "status": "updated"}


@router.delete("/raci/rules/{rule_id}")
async def delete_rule(rule_id: int):
    await execute("UPDATE service_raci_rules SET enabled = false, updated_at = NOW() WHERE id = $1", rule_id)
    await log_event("intake", "warning", "dashboard", "raci_rule_disabled", f"rule_{rule_id}")
    return {"id": rule_id, "status": "disabled"}


@router.post("/clarify")
async def clarify_intake(body: dict = Body({})):
    message = (body or {}).get("message", "")
    title = (body or {}).get("title", "")
    rule, score = await _best_rule(message, title, (body or {}).get("category"))
    correlation = await _correlate(message, title, rule)
    classification = _classification(rule, score, correlation)
    text = f"{title}\n{message}".lower()
    questions = []
    if classification.get("intent") == "phishing":
        if "sender" not in text and "from:" not in text:
            questions.append("Who sent the suspicious message, or can you attach the original email headers?")
        if "http" not in text and "url" not in text and "link" not in text:
            questions.append("What suspicious URL or attachment name did the user see?")
        if "clicked" not in text and "opened" not in text:
            questions.append("Did anyone click the link, open the attachment, or enter credentials?")
    elif classification.get("intent") in ("access-request", "identity-help"):
        if "manager" not in text and "owner" not in text:
            questions.append("Who should approve this access or identity change?")
        if "group" not in text and "role" not in text and "app" not in text:
            questions.append("Which application, role, group, or mailbox is involved?")
    else:
        if len(message.strip()) < 40:
            questions.append("What happened, who is affected, and when did it start?")
        if not (body or {}).get("requester_email"):
            questions.append("What email address should updates be sent to?")
    return {"classification": classification, "questions": questions[:4], "needs_clarification": bool(questions)}


@router.post("/classify")
async def classify_intake(body: dict = Body({})):
    message = (body or {}).get("message", "")
    title = (body or {}).get("title", "")
    category = (body or {}).get("category", "")
    if not message.strip() and not title.strip():
        return {"error": "message or title is required"}

    rule, score = await _best_rule(message, title, category)
    correlation = await _correlate(message, title, rule)
    classification = _classification(rule, score, correlation)
    await log_event("intake", "info", "dashboard", "intake_classified",
                    classification.get("intent"), {
                        "rule": classification.get("rule_name"),
                        "assignment_group": classification.get("assignment_group"),
                        "approval_required": classification.get("approval_required"),
                    })
    return {"classification": classification}


@router.post("/submit")
async def submit_intake(body: dict = Body({})):
    message = (body or {}).get("message", "")
    title = (body or {}).get("title") or (message.strip().splitlines()[0][:120] if message.strip() else "")
    requester_name = (body or {}).get("requester_name") or "Requester"
    requester_email = (body or {}).get("requester_email")
    affected_user_name = (body or {}).get("affected_user_name") or requester_name
    affected_user_email = (body or {}).get("affected_user_email") or requester_email
    channel = (body or {}).get("channel") or "dashboard"
    attachments = _as_list((body or {}).get("attachments"))
    sync_provider = (body or {}).get("sync_provider")
    auto_assign = bool((body or {}).get("auto_assign", True))

    if not message.strip() and not title.strip():
        return {"error": "message or title is required"}

    rule, score = await _best_rule(message, title, (body or {}).get("category"))
    correlation = await _correlate(message, title, rule)
    classification = _classification(rule, score, correlation)
    description = "\n".join([
        f"Requester: {requester_name} <{requester_email or 'not provided'}>",
        f"Channel: {channel}",
        f"Intent: {classification.get('intent')} ({classification.get('confidence')})",
        f"Assignment group: {classification.get('assignment_group')}",
        "",
        "User message:",
        message,
    ])

    ticket = await ticket_service.create_ticket(
        title=title or "Service desk intake",
        description=description,
        ticket_class=classification.get("ticket_class") or "UserRequest",
        status="new",
        priority=classification.get("priority"),
        provider=(body or {}).get("provider"),
        sync_provider=sync_provider,
        assignee_team=classification.get("assignment_group"),
        opened_by_name=requester_name,
        opened_by_email=requester_email,
        requester_name=requester_name,
        requester_email=requester_email,
        affected_user_name=affected_user_name,
        affected_user_email=affected_user_email,
        created_by="service-desk-intake",
        auto_assign=False,
    )
    ticket_id = ticket["id"]

    note_lines = [
        "Service desk intake classification",
        f"- Intent: {classification.get('intent')}",
        f"- Assignment group: {classification.get('assignment_group')}",
        f"- Priority: {classification.get('priority')}",
        f"- Approval required: {classification.get('approval_required')}",
        f"- RACI responsible: {classification.get('raci', {}).get('responsible')}",
        f"- RACI accountable: {classification.get('raci', {}).get('accountable')}",
    ]
    if classification.get("related_tickets"):
        note_lines.append(f"- Related tickets found: {len(classification['related_tickets'])}")
    if classification.get("knowledge_articles"):
        note_lines.append(f"- Knowledge articles found: {len(classification['knowledge_articles'])}")
    note = await ticket_service.add_note(
        ticket_id,
        "\n".join(note_lines),
        author="service-desk-intake",
        source="intake",
        visibility="internal",
    )

    for attachment in attachments:
        if isinstance(attachment, str):
            attachment = {"filename": attachment}
        filename = attachment.get("filename") if isinstance(attachment, dict) else None
        if filename:
            await ticket_service.add_attachment_metadata(
                ticket_id,
                filename,
                content_type=attachment.get("content_type"),
                storage_ref=attachment.get("storage_ref"),
                sha256=attachment.get("sha256"),
                size_bytes=attachment.get("size_bytes"),
                note_id=note.get("id"),
                metadata=attachment,
            )

    change_id = None
    if classification.get("approval_required"):
        change_id = await fetchval("""
            INSERT INTO change_requests (
                ticket_id, action, target, reason, risk_level, approval_policy,
                status, requested_by, requested_at, expires_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, 'pending', 'service-desk-intake',
                    NOW(), NOW() + INTERVAL '7 days')
            RETURNING id
        """, ticket_id,
            classification.get("approval_action") or "Approve routed service request",
            f"ticket_{ticket_id}",
            "Intake route indicates approval is required before environment-changing work.",
            classification.get("risk_level") or "medium",
            json_dumps({"source": "service-desk-intake", "raci": classification.get("raci", {})}))

    intake_id = await fetchval("""
        INSERT INTO service_intake_sessions (
            requester_name, requester_email, channel, message, attachments,
            classification, ticket_id, status
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, 'ticket_created')
        RETURNING id
    """, requester_name, requester_email, channel, message,
        json_dumps(attachments), json_dumps(classification), ticket_id)

    await execute("""
        INSERT INTO audit_log (actor, action, target, details)
        VALUES ($1, $2, $3, $4)
    """, "service-desk-intake", "intake_ticket_created", f"ticket_{ticket_id}",
        json_dumps({"intake_id": intake_id, "change_id": change_id, "classification": classification}))
    await log_event("intake", "info", "service-desk-intake", "intake_ticket_created",
                    f"ticket_{ticket_id}", {
                        "intake_id": intake_id,
                        "change_id": change_id,
                        "assignment_group": classification.get("assignment_group"),
                    })

    if auto_assign:
        try:
            from services import auto_assignment
            auto_assignment_result = await auto_assignment.maybe_auto_assign(ticket_id, source="service-desk-intake")
        except Exception as exc:
            auto_assignment_result = {"status": "error", "error": str(exc)}
            await log_event("agent", "error", "service-desk-intake", "auto_assignment_failed",
                            f"ticket_{ticket_id}", {"error": str(exc)})
    else:
        auto_assignment_result = {"status": "skipped", "reason": "request_disabled"}

    return {
        "intake_id": intake_id,
        "ticket": ticket,
        "change_id": change_id,
        "classification": classification,
        "auto_assignment": auto_assignment_result,
    }


@router.get("/sessions")
async def list_sessions(limit: int = Query(50, ge=1, le=200)):
    rows = await fetchall("""
        SELECT s.*, t.title AS ticket_title, t.status AS ticket_status
        FROM service_intake_sessions s
        LEFT JOIN tickets t ON t.id = s.ticket_id
        ORDER BY s.created_at DESC
        LIMIT $1
    """, limit)
    for row in rows:
        row["classification"] = _json_value(row.get("classification"), {})
        row["attachments"] = _json_value(row.get("attachments"), [])
    return {"sessions": rows, "total": len(rows)}
