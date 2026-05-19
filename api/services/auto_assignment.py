"""Policy-driven automatic agent assignment for incoming tickets."""
import json
import os

from database import fetchall, fetchrow, execute
from services.event_logger import log_event
from services.task_prompts import build_auto_assignment_prompt


DEFAULT_MODEL = "deepseek/deepseek-v4-flash"
DEFAULT_MAX_ACTIVE_PER_RULE = int(os.getenv("AUTO_ASSIGNMENT_MAX_ACTIVE_PER_RULE", "1") or "1")


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            loaded = json.loads(value)
            return loaded if isinstance(loaded, list) else [loaded]
        except json.JSONDecodeError:
            return [value]
    return [value]


def _score_rule(rule, ticket):
    text = " ".join([
        ticket.get("title") or "",
        ticket.get("description") or "",
        ticket.get("itop_class") or "",
        ticket.get("provider_class") or "",
        ticket.get("assignee_team") or "",
    ]).lower()
    score = 0
    strong_signal = False
    ticket_class = (ticket.get("provider_class") or ticket.get("itop_class") or "").lower()
    assignee_team = (ticket.get("assignee_team") or "").lower()
    if rule.get("assignment_group") and assignee_team == str(rule.get("assignment_group")).lower():
        score += 4
        strong_signal = True
    for keyword in _as_list(rule.get("keywords")):
        keyword_text = str(keyword).lower().strip()
        if keyword_text and keyword_text in text:
            score += max(1, len(keyword_text.split()))
            strong_signal = True
    if not strong_signal:
        return 0
    if rule.get("ticket_class") and ticket_class == str(rule.get("ticket_class")).lower():
        score += 3
    return score


async def maybe_auto_assign(ticket_id, source="ticket_event"):
    """Spawn a ticket agent when an enabled RACI rule says to do so."""
    ticket = await fetchrow("SELECT * FROM tickets WHERE id = $1", ticket_id)
    if not ticket:
        return {"status": "skipped", "reason": "ticket_not_found"}
    if ticket.get("agent_id"):
        return {"status": "skipped", "reason": "ticket_already_has_agent", "agent_id": ticket.get("agent_id")}

    active_agent = await fetchrow("""
        SELECT id, status FROM agents
        WHERE ticket_id = $1
          AND status IN ('spawned', 'running', 'working')
        ORDER BY started_at DESC
        LIMIT 1
    """, ticket_id)
    if active_agent:
        return {"status": "skipped", "reason": "active_agent_exists", "agent_id": active_agent["id"]}

    rules = await fetchall("""
        SELECT *
        FROM service_raci_rules
        WHERE enabled = true
          AND auto_assign_agent = true
        ORDER BY id ASC
    """)
    if not rules:
        return {"status": "skipped", "reason": "no_enabled_policy"}

    scored = [(rule, _score_rule(rule, ticket)) for rule in rules]
    scored.sort(key=lambda item: item[1], reverse=True)
    rule, score = scored[0]
    if score <= 0:
        await log_event("agent", "info", source, "auto_assignment_no_match", f"ticket_{ticket_id}", {
            "ticket_class": ticket.get("itop_class"),
            "provider": ticket.get("provider"),
        })
        return {"status": "skipped", "reason": "no_matching_policy"}

    max_active_per_rule = DEFAULT_MAX_ACTIVE_PER_RULE
    if max_active_per_rule > 0:
        active_rows = await fetchall("""
            SELECT a.id AS agent_id, t.id AS ticket_id, t.title, t.description,
                   t.itop_class, t.provider_class, t.assignee_team
            FROM agents a
            JOIN tickets t ON t.id = a.ticket_id
            WHERE a.status IN ('spawned', 'running', 'working')
              AND t.id <> $1
            ORDER BY a.started_at DESC
        """, ticket_id)
        matching_active = [
            row for row in active_rows
            if _score_rule(rule, row) > 0
        ]
        if len(matching_active) >= max_active_per_rule:
            await log_event("agent", "info", source, "auto_assignment_capacity_reached", f"ticket_{ticket_id}", {
                "rule_id": rule.get("id"),
                "rule_name": rule.get("name"),
                "score": score,
                "max_active_per_rule": max_active_per_rule,
                "active_agent_ids": [row.get("agent_id") for row in matching_active[:10]],
            })
            return {
                "status": "skipped",
                "reason": "auto_assignment_capacity_reached",
                "rule_id": rule.get("id"),
                "score": score,
                "max_active_per_rule": max_active_per_rule,
                "active_agent_ids": [row.get("agent_id") for row in matching_active[:10]],
            }

    model = rule.get("auto_agent_model") or DEFAULT_MODEL
    extra_prompt = rule.get("auto_agent_prompt") or (
        f"Auto-assigned by RACI rule `{rule.get('name')}` for intent `{rule.get('intent')}`. "
        f"Assignment group: {rule.get('assignment_group')}. "
        "Work the ticket to completion using canonical context, notes, approval gates, and postmortem recommendations."
    )
    from services import agent_runner

    result = await agent_runner.spawn_agent(
        ticket_id,
        model,
        build_auto_assignment_prompt(ticket, extra_prompt),
    )
    if result.get("error"):
        await log_event("agent", "error", source, "auto_agent_assignment_failed", f"ticket_{ticket_id}", {
            "rule_id": rule.get("id"),
            "rule_name": rule.get("name"),
            "score": score,
            "model": model,
            "error": result.get("error"),
        })
        return {**result, "status": "error", "rule_id": rule.get("id"), "score": score}

    await execute("""
        INSERT INTO ticket_notes (ticket_id, source, author, body, visibility, external_ref)
        VALUES ($1, 'auto-assignment', 'system', $2, 'internal', $3)
    """, ticket_id,
        f"Auto-assigned agent `{result.get('agent_id')}` from RACI rule `{rule.get('name')}`.",
        f"auto-assignment:raci-rule:{rule.get('id')}")
    await log_event("agent", "info", source, "auto_agent_assigned", f"ticket_{ticket_id}", {
        "agent_id": result.get("agent_id"),
        "task_id": result.get("task_id"),
        "rule_id": rule.get("id"),
        "rule_name": rule.get("name"),
        "score": score,
        "model": model,
    })
    return {**result, "status": "assigned", "rule_id": rule.get("id"), "score": score}
