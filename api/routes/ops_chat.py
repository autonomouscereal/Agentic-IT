from fastapi import APIRouter, Body, Request
import json
import os
import time

from database import fetchall, fetchrow, fetchval, execute, json_dumps
from services import ticket_service
from services.event_logger import log_event
from services.task_prompts import build_auto_assignment_prompt, build_ticket_resolution_prompt
from routes import intake as intake_route

router = APIRouter(prefix="/api/ops-chat", tags=["ops-chat"])

OPS_CHAT_MODEL = "agentic-ops-intake"
DEFAULT_AGENT_MODEL = os.getenv("OPS_CHAT_AGENT_MODEL") or os.getenv("AGENT_DEFAULT_MODEL") or "local/agent-default"


def _chat_agent_model(classification=None):
    """Return the model for chat-originated agent work.

    Ops Chat is a demo/customer entrypoint, so it should follow the active route
    switch. A RACI rule may still set `auto_agent_model` for normal ticket
    auto-assignment, but chat handoff uses OPS_CHAT_AGENT_MODEL/AGENT_DEFAULT_MODEL
    first so stale per-rule values cannot silently route chat to the wrong lane.
    """
    return (
        os.getenv("OPS_CHAT_AGENT_MODEL")
        or os.getenv("AGENT_DEFAULT_MODEL")
        or ((classification or {}).get("auto_agent_model"))
        or DEFAULT_AGENT_MODEL
    )


def _json(value, default):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _last_user_message(messages):
    for message in reversed(messages or []):
        if message.get("role") == "user":
            return str(message.get("content") or "").strip()
    return ""


def _looks_like_work(message, classification):
    text = (message or "").lower()
    if (classification or {}).get("intent") not in (None, "", "general"):
        return True
    work_terms = (
        "can't log", "cannot log", "locked out", "password", "mfa", "access",
        "install", "software", "phish", "suspicious", "email", "alert",
        "outage", "down", "broken", "deploy", "pipeline", "ticket",
        "request", "approval", "vpn", "account", "permissions", "research",
        "investigate", "fix", "change", "onboard", "offboard", "audit",
    )
    return any(term in text for term in work_terms)


async def _ensure_session(session_id, requester_name, requester_email, channel, external_thread_id=None):
    if session_id:
        existing = await fetchrow("SELECT id FROM ops_chat_sessions WHERE id = $1", int(session_id))
        if existing:
            return existing["id"]
    if external_thread_id:
        existing = await fetchrow("""
            SELECT id
            FROM ops_chat_sessions
            WHERE external_thread_id = $1
            ORDER BY updated_at DESC
            LIMIT 1
        """, external_thread_id)
        if existing:
            await execute("""
                UPDATE ops_chat_sessions
                SET requester_name = COALESCE($2, requester_name),
                    requester_email = COALESCE($3, requester_email),
                    channel = COALESCE($4, channel),
                    updated_at = NOW()
                WHERE id = $1
            """, existing["id"], requester_name, requester_email, channel)
            return existing["id"]
    return await fetchval("""
        INSERT INTO ops_chat_sessions (requester_name, requester_email, channel, external_thread_id)
        VALUES ($1, $2, $3, $4)
        RETURNING id
    """, requester_name or "Chat User", requester_email, channel or "matrix", external_thread_id)


async def _record_message(session_id, role, body, metadata=None, ticket_id=None):
    message_id = await fetchval("""
        INSERT INTO ops_chat_messages (session_id, role, body, metadata, ticket_id)
        VALUES ($1, $2, $3, $4::jsonb, $5)
        RETURNING id
    """, session_id, role, body, json_dumps(metadata or {}), ticket_id)
    await execute("""
        UPDATE ops_chat_sessions
        SET latest_ticket_id = COALESCE($2, latest_ticket_id),
            updated_at = NOW()
        WHERE id = $1
    """, session_id, ticket_id)
    return message_id


async def _session_ticket_id(session_id):
    row = await fetchrow("""
        SELECT latest_ticket_id
        FROM ops_chat_sessions
        WHERE id = $1
    """, session_id)
    if row and row.get("latest_ticket_id"):
        return row["latest_ticket_id"]
    row = await fetchrow("""
        SELECT ticket_id
        FROM ops_chat_messages
        WHERE session_id = $1 AND ticket_id IS NOT NULL
        ORDER BY created_at DESC, id DESC
        LIMIT 1
    """, session_id)
    return row.get("ticket_id") if row else None


async def _active_ticket_agent(ticket_id):
    return await fetchrow("""
        SELECT a.id, a.model, a.selected_model, a.status, t.id AS task_id, t.status AS task_status
        FROM agents a
        LEFT JOIN agent_tasks t ON t.agent_id = a.id
        WHERE a.ticket_id = $1
          AND a.status IN ('spawned', 'running', 'working', 'pending_approval', 'awaiting_access', 'awaiting_user_response', 'blocked')
          AND (t.id IS NULL OR t.status IN ('queued', 'running', 'pending_approval', 'awaiting_access', 'awaiting_user_response', 'blocked'))
        ORDER BY COALESCE(t.created_at, a.started_at) DESC
        LIMIT 1
    """, ticket_id)


async def _spawn_chat_agent(ticket_id, classification, message, requester_name=None, channel="matrix"):
    active = await _active_ticket_agent(ticket_id)
    if active and active.get("status") in ("spawned", "running", "working"):
        return {
            "status": "already_active",
            "agent_id": active.get("id"),
            "task_id": active.get("task_id"),
            "agent_status": active.get("status"),
        }
    ticket = await fetchrow("SELECT * FROM tickets WHERE id = $1", ticket_id)
    if not ticket:
        return {"status": "error", "error": "ticket_not_found"}
    model = _chat_agent_model(classification)
    extra_prompt = "\n".join([
        "This ticket originated from the real Matrix/Element Ops Chat client.",
        f"Requester: {requester_name or 'Chat User'}",
        f"Channel: {channel or 'matrix'}",
        "Use the dashboard ticket as the system of record. Reply to the user by writing clear ticket notes; the Matrix bridge will surface ticket and agent status back to the room.",
        "Ask one concise clarification with /api/tickets/{ticket_id}/request-info if needed. Do not do hidden work outside the ticket.",
        "Original chat message:",
        message,
    ])
    from services import agent_runner
    result = await agent_runner.spawn_agent(
        ticket_id,
        model,
        build_auto_assignment_prompt(ticket, extra_prompt),
        "ticket_resolution",
    )
    await log_event("ops-chat", "info", "ops-chat-agent", "chat_agent_spawn_requested",
                    f"ticket_{ticket_id}", {
                        "agent_id": result.get("agent_id"),
                        "task_id": result.get("task_id"),
                        "model": model,
                        "channel": channel,
                    })
    return result


async def _create_routed_ticket(message, requester_name, requester_email, channel, classification, spawn_agent):
    title = message.strip().splitlines()[0][:120] if message.strip() else "Ops chat request"
    description = "\n".join([
        f"Requester: {requester_name or 'Chat User'} <{requester_email or 'not provided'}>",
        f"Channel: {channel or 'matrix'}",
        f"Intent: {classification.get('intent')} ({classification.get('confidence')})",
        f"Assignment group: {classification.get('assignment_group')}",
        "",
        "Chat message:",
        message,
    ])
    ticket = await ticket_service.create_ticket(
        title=title,
        description=description,
        ticket_class=classification.get("ticket_class") or "UserRequest",
        status="new",
        priority=classification.get("priority") or "P3",
        provider="local",
        sync_provider=False,
        assignee_team=classification.get("assignment_group"),
        created_by="ops-chat-agent",
        auto_assign=False,
    )
    ticket_id = ticket["id"]
    note = await ticket_service.add_note(
        ticket_id,
        "\n".join([
            "Ops Chat intake classification",
            f"- Intent: {classification.get('intent')}",
            f"- Assignment group: {classification.get('assignment_group')}",
            f"- Priority: {classification.get('priority')}",
            f"- Approval required: {classification.get('approval_required')}",
            "- Agent harness: dashboard queue via Hermes or Claude Code, routed through the configured AI proxy.",
            "",
            "The ticket was created from a Matrix/Element chat request so the work is traceable.",
        ]),
        author="ops-chat-agent",
        source="ops-chat",
        visibility="internal",
    )
    change_id = None
    if classification.get("approval_required"):
        change_id = await fetchval("""
            INSERT INTO change_requests (
                ticket_id, action, target, reason, risk_level, approval_policy,
                status, requested_by, requested_at, expires_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, 'pending', 'ops-chat-agent',
                    NOW(), NOW() + INTERVAL '7 days')
            RETURNING id
        """, ticket_id,
            classification.get("approval_action") or "Approve routed chat request",
            f"ticket_{ticket_id}",
            "Ops Chat route indicates approval is required before environment-changing work.",
            classification.get("risk_level") or "medium",
            json_dumps({"source": "ops-chat", "raci": classification.get("raci", {})}))
    await execute("""
        INSERT INTO service_intake_sessions (
            requester_name, requester_email, channel, message, attachments,
            classification, ticket_id, status
        )
        VALUES ($1, $2, $3, $4, '[]'::jsonb, $5::jsonb, $6, 'ticket_created')
    """, requester_name or "Chat User", requester_email, channel or "matrix",
        message, json_dumps(classification), ticket_id)

    agent_result = {"status": "skipped", "reason": "spawn_agent_disabled"}
    if spawn_agent:
        try:
            agent_result = await _spawn_chat_agent(ticket_id, classification, message, requester_name, channel)
            agent_id = (agent_result or {}).get("agent_id")
            if change_id and agent_id:
                await execute("""
                    UPDATE change_requests
                    SET agent_id = $1
                    WHERE id = $2
                      AND agent_id IS NULL
                """, int(agent_id), change_id)
                await log_event("ops-chat", "info", "ops-chat-agent", "chat_approval_gate_bound_to_agent",
                                f"change_{change_id}", {
                                    "ticket_id": ticket_id,
                                    "agent_id": agent_id,
                                    "change_id": change_id,
                                })
        except Exception as exc:
            agent_result = {"status": "error", "error": str(exc)}
            await log_event("agent", "error", "ops-chat-agent", "chat_agent_spawn_failed",
                            f"ticket_{ticket_id}", {"error": str(exc)})
    return {
        "ticket": ticket,
        "ticket_id": ticket_id,
        "note_id": note.get("id"),
        "change_id": change_id,
        "agent": agent_result,
    }


async def _continue_ticket_from_chat(session_id, ticket_id, message, requester_name, requester_email, channel, spawn_agent=True):
    note = await ticket_service.add_note(
        ticket_id,
        "\n".join([
            "User chat follow-up",
            f"Responder: {requester_name or 'Chat User'} <{requester_email or 'not provided'}>",
            f"Channel: {channel or 'matrix'}",
            "",
            message,
        ]),
        author=requester_name or "Chat User",
        source="user-response",
        visibility="internal",
        external_ref=f"ops-chat-session:{session_id}",
    )
    active = await _active_ticket_agent(ticket_id)
    resume = {"status": "not_needed"}
    if not spawn_agent:
        resume = {"status": "skipped", "reason": "spawn_agent_disabled"}
    elif active and active.get("status") in ("spawned", "running", "working"):
        resume = {
            "status": "delivered_to_active_agent",
            "agent_id": active.get("id"),
            "task_id": active.get("task_id"),
            "agent_status": active.get("status"),
        }
    else:
        ticket = await fetchrow("SELECT * FROM tickets WHERE id = $1", ticket_id)
        if ticket:
            from services import agent_runner
            prior = (
                f"Prior waiting agent: {active.get('id')} / {active.get('status')}."
                if active else
                "No active agent was available."
            )
            resume = await agent_runner.spawn_agent(
                ticket_id,
                _chat_agent_model(),
                "\n".join([
                    build_ticket_resolution_prompt(ticket),
                    "",
                    "A requester sent a new Matrix/Element chat follow-up. Re-read the ticket notes, use the latest user-response note, continue the ticket, and write a user-readable note with the outcome.",
                    prior,
                ]),
                "ticket_resolution",
            )
    return {"note": note, "active_agent": active, "resume": resume}


async def _general_reply(message):
    return (
        "I can help. This looks like a general chat message, so I did not open a ticket. "
        "When you ask me to investigate, change, access, deploy, repair, audit, or otherwise do operational work, "
        "I will create a traceable ticket and hand it to a real dashboard agent."
    )


async def _handle_chat_message(message, requester_name=None, requester_email=None, session_id=None,
                               channel="matrix", external_thread_id=None, spawn_agent=True,
                               force_new_ticket=False):
    session_id = await _ensure_session(session_id, requester_name, requester_email, channel, external_thread_id)
    existing_ticket_id = await _session_ticket_id(session_id)
    await _record_message(session_id, "user", message, {
        "channel": channel,
        "external_thread_id": external_thread_id,
    }, existing_ticket_id)

    if existing_ticket_id and not force_new_ticket:
        continuation = await _continue_ticket_from_chat(
            session_id, existing_ticket_id, message, requester_name, requester_email, channel, spawn_agent
        )
        reply = (
            f"I added your update to ticket #{existing_ticket_id}. "
            "If an agent is active, it was delivered as steering context; otherwise continuation follows the chat spawn policy."
        )
        await _record_message(session_id, "assistant", reply, continuation, existing_ticket_id)
        await log_event("ops-chat", "info", "ops-chat-agent", "chat_ticket_updated",
                        f"ticket_{existing_ticket_id}", {
                            "session_id": session_id,
                            "channel": channel,
                            "resume": continuation.get("resume"),
                        })
        return {
            "session_id": session_id,
            "reply": reply,
            "ticket_id": existing_ticket_id,
            "created_ticket": False,
            "continued_ticket": True,
            **continuation,
        }

    rule, score = await intake_route._best_rule(message, message[:120], None)
    correlation = await intake_route._correlate(message, message[:120], rule)
    classification = intake_route._classification(rule, score, correlation)

    if not _looks_like_work(message, classification):
        reply = await _general_reply(message)
        await _record_message(session_id, "assistant", reply, {"classification": classification})
        await log_event("ops-chat", "info", "ops-chat-agent", "general_chat_answered",
                        f"chat_session_{session_id}", {"intent": classification.get("intent")})
        return {
            "session_id": session_id,
            "reply": reply,
            "classification": classification,
            "ticket_id": None,
            "created_ticket": False,
        }

    routed = await _create_routed_ticket(
        message, requester_name, requester_email, channel, classification, spawn_agent
    )
    ticket_id = routed["ticket_id"]
    reply = (
        f"I created ticket #{ticket_id} and routed it to "
        f"{classification.get('assignment_group') or 'the operations queue'}. "
        f"Classification: {classification.get('intent')} / priority {classification.get('priority')}. "
    )
    if routed.get("change_id"):
        reply += f"Approval gate #{routed['change_id']} was opened before risky action. "
    agent_status = (routed.get("agent") or {}).get("status")
    if agent_status:
        reply += f"Agent harness status: {agent_status}. "
    reply += "The request is now traceable in tickets, audit, intake history, and the agent queue."
    await _record_message(session_id, "assistant", reply, {
        "classification": classification,
        "ticket_id": ticket_id,
        "change_id": routed.get("change_id"),
        "agent": routed.get("agent"),
    }, ticket_id=ticket_id)
    await log_event("ops-chat", "info", "ops-chat-agent", "chat_ticket_created",
                    f"ticket_{ticket_id}", {
                        "session_id": session_id,
                        "intent": classification.get("intent"),
                        "assignment_group": classification.get("assignment_group"),
                        "agent": routed.get("agent"),
                    })
    return {
        "session_id": session_id,
        "reply": reply,
        "classification": classification,
        "ticket_id": ticket_id,
        "created_ticket": True,
        "continued_ticket": False,
        "change_id": routed.get("change_id"),
        "agent": routed.get("agent"),
    }


@router.get("/sessions")
async def list_chat_sessions(limit: int = 50):
    rows = await fetchall("""
        SELECT s.*, COUNT(m.id) AS message_count, MAX(m.created_at) AS last_message_at
        FROM ops_chat_sessions s
        LEFT JOIN ops_chat_messages m ON m.session_id = s.id
        GROUP BY s.id
        ORDER BY COALESCE(MAX(m.created_at), s.created_at) DESC
        LIMIT $1
    """, min(max(int(limit or 50), 1), 200))
    return {"sessions": rows, "total": len(rows)}


@router.get("/sessions/{session_id}/messages")
async def get_chat_messages(session_id: int):
    rows = await fetchall("""
        SELECT * FROM ops_chat_messages
        WHERE session_id = $1
        ORDER BY created_at ASC
    """, session_id)
    for row in rows:
        row["metadata"] = _json(row.get("metadata"), {})
    return {"session_id": session_id, "messages": rows, "total": len(rows)}


@router.post("/message")
async def send_chat_message(body: dict = Body({})):
    body = body or {}
    message = str(body.get("message") or "").strip()
    if not message:
        return {"error": "message is required"}
    return await _handle_chat_message(
        message,
        requester_name=body.get("requester_name") or body.get("sender_name") or "Chat User",
        requester_email=body.get("requester_email") or body.get("sender_email"),
        session_id=body.get("session_id"),
        channel=body.get("channel") or "matrix",
        external_thread_id=body.get("external_thread_id") or body.get("matrix_room_id"),
        spawn_agent=bool(body.get("spawn_agent", True)),
        force_new_ticket=bool(body.get("force_new_ticket", False)),
    )


@router.get("/matrix/health")
async def matrix_health():
    return {
        "status": "ok",
        "client": "Matrix Synapse + Element",
        "bridge": "ops-chat-bridge",
        "identity": "Keycloak OIDC",
        "agent_harness": os.getenv("AGENT_HARNESS", "hermes"),
        "agent_model": _chat_agent_model(),
    }


@router.get("/openai/v1/models")
async def openai_models():
    """Legacy compatibility only. Matrix/Element is the supported chat client."""
    return {
        "object": "list",
        "data": [{
            "id": OPS_CHAT_MODEL,
            "object": "model",
            "created": 0,
            "owned_by": "agentic-operations",
        }],
        "warning": "OpenAI-compatible chat is deprecated for Ops Chat; use Matrix/Element plus ops-chat-bridge.",
    }


@router.post("/openai/v1/chat/completions")
async def openai_chat_completions(request: Request, body: dict = Body({})):
    """Legacy compatibility route that still creates tickets and real agents."""
    body = body or {}
    message = _last_user_message(body.get("messages") or [])
    if not message:
        response_text = "Send an operational request through Matrix/Element and I will route it."
        result = {"reply": response_text, "session_id": None}
    else:
        result = await _handle_chat_message(
            message,
            requester_name="Legacy Chat User",
            requester_email=None,
            session_id=None,
            channel="legacy-openai-compatible",
            spawn_agent=True,
        )
        response_text = result["reply"]

    return {
        "id": f"chatcmpl-ops-{int(time.time() * 1000)}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": body.get("model") or OPS_CHAT_MODEL,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": response_text},
            "finish_reason": "stop",
        }],
        "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        "metadata": {
            "session_id": result.get("session_id"),
            "ticket_id": result.get("ticket_id"),
            "created_ticket": result.get("created_ticket"),
            "agent": result.get("agent"),
        },
    }
