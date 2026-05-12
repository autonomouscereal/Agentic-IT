import os
import json
import re

from fastapi import APIRouter, Body, Query
from database import fetchall, fetchrow, execute, fetchval, json_dumps
from services.event_logger import log_event
from services.postmortem_synthesizer import synthesize_postmortem
from services.ticket_service import compact_ticket_payload

router = APIRouter(prefix="/api/postmortems", tags=["postmortems"])


def _truncate(value, limit=1500):
    if value is None:
        return value
    text = value if isinstance(value, str) else json_dumps(value)
    if len(text) <= limit:
        return text
    return text[:limit] + f"... [truncated {len(text) - limit} chars]"


def _loads(value, default):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return default


def _slug(value, fallback="asset"):
    text = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return (text or fallback)[:80]


def _text_lines(value):
    if value is None:
        return []
    if isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, dict):
                name = item.get("name") or item.get("title") or item.get("action") or "item"
                detail = item.get("description") or item.get("purpose") or item.get("expected") or item.get("approval") or ""
                lines.append(f"- {name}: {detail}".strip())
            else:
                lines.append(f"- {item}")
        return lines
    return [str(value)]


def _postmortem_article_body(postmortem, ticket, skill_ids, workflow_name):
    title = ticket.get("title") if ticket else f"postmortem {postmortem['id']}"
    skill_proposals = _loads(postmortem.get("skill_proposals"), [])
    test_cases = _loads(postmortem.get("test_cases"), [])
    guardrails = _loads(postmortem.get("guardrails"), [])
    sections = [
        f"# Postmortem Knowledge: {title}",
        "",
        f"- Postmortem: {postmortem['id']}",
        f"- Ticket: {postmortem.get('ticket_id') or 'n/a'}",
        f"- Promoted workflow: {workflow_name or 'not requested'}",
        f"- Promoted skill IDs: {', '.join(str(s) for s in skill_ids) if skill_ids else 'none'}",
        "",
        "## Summary",
        postmortem.get("summary") or "No summary recorded.",
        "",
        "## What Worked",
        postmortem.get("went_well") or "No positives recorded.",
        "",
        "## Improvements",
        postmortem.get("improvements") or "No improvements recorded.",
        "",
        "## Workflow Proposal",
        postmortem.get("workflow_proposal") or "No workflow proposal recorded.",
        "",
        "## Skill Proposals",
        *(_text_lines(skill_proposals) or ["- None"]),
        "",
        "## Test Cases",
        *(_text_lines(test_cases) or ["- None"]),
        "",
        "## Guardrails",
        *(_text_lines(guardrails) or ["- None"]),
        "",
        "## Documentation Notes",
        postmortem.get("documentation") or "No additional documentation recorded.",
    ]
    return "\n".join(sections)


def _skill_prompt_from_proposal(proposal, postmortem):
    if isinstance(proposal, dict):
        prompt = proposal.get("prompt_template") or proposal.get("prompt") or proposal.get("instructions")
        if prompt:
            return str(prompt)
        purpose = proposal.get("purpose") or proposal.get("description") or proposal.get("name") or "reusable task step"
    else:
        purpose = str(proposal)
    return (
        f"Use this reusable skill for: {purpose}\n"
        f"Source postmortem: {postmortem['id']}.\n"
        "Start from the ticket context bundle, write regular ticket notes, use approval gates for any change, "
        "and record test evidence before marking work complete."
    )


def _skill_name_from_proposal(proposal, postmortem_id, index):
    if isinstance(proposal, dict):
        base = proposal.get("name") or proposal.get("title") or proposal.get("purpose")
    else:
        base = proposal
    return f"postmortem-{postmortem_id}-{_slug(base, f'skill-{index}')}"[:200]


def _workflow_name(postmortem_id, ticket):
    ticket_title = (ticket or {}).get("title") or f"postmortem {postmortem_id}"
    return f"postmortem-{postmortem_id}-{_slug(ticket_title, 'workflow')}"[:240]


def _ticket_class(ticket):
    return (ticket or {}).get("provider_class") or (ticket or {}).get("itop_class")


def _severity_counts(findings):
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0, "info": 0, "unknown": 0}
    for finding in findings or []:
        severity = str(finding.get("severity") or "unknown").lower()
        counts[severity if severity in counts else "unknown"] += 1
    return counts


def _compact_tool_results(tool_results):
    compact = {}
    for name, result in (tool_results or {}).items():
        if not isinstance(result, dict):
            compact[name] = _truncate(result, 500)
            continue
        compact[name] = {
            "status": result.get("status"),
            "returncode": result.get("returncode"),
            "reason": _truncate(result.get("reason"), 500),
            "duration_seconds": result.get("duration_seconds"),
            "artifact": result.get("artifact"),
            "stderr_tail": _truncate((result.get("stderr") or "")[-180:], 180),
        }
    return compact


def _tail_file(path, lines):
    if not path:
        return ""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return "".join(handle.readlines()[-lines:])
    except (FileNotFoundError, OSError):
        return ""


@router.get("")
async def list_postmortems(
    ticket_id: int = Query(None),
    status: str = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    where = []
    params = []
    idx = 1
    if ticket_id:
        where.append(f"pm.ticket_id = ${idx}")
        params.append(ticket_id)
        idx += 1
    if status:
        where.append(f"pm.status = ${idx}")
        params.append(status)
        idx += 1
    where_sql = "WHERE " + " AND ".join(where) if where else ""
    rows = await fetchall(f"""
        SELECT pm.*, t.title AS ticket_title, a.model AS agent_model
        FROM postmortems pm
        LEFT JOIN tickets t ON pm.ticket_id = t.id
        LEFT JOIN agents a ON pm.agent_id = a.id
        {where_sql}
        ORDER BY pm.created_at DESC
        LIMIT ${idx}
    """, *params, limit)
    return {"postmortems": rows, "total": len(rows)}


@router.get("/evidence/{ticket_id}")
async def get_postmortem_evidence(
    ticket_id: int,
    task_log_lines: int = Query(0, ge=0, le=100),
):
    """Return compact, agent-safe evidence for postmortem work.

    This endpoint is intentionally summary-first: it gives agents the material
    they need for lessons learned without asking them to discover provider-
    specific note URLs or read arbitrary files outside their work directory.
    """
    ticket = await fetchrow("SELECT * FROM tickets WHERE id = $1", ticket_id)
    if not ticket:
        return {"error": "Ticket not found"}
    compact_ticket_payload(ticket)

    notes = await fetchall("""
        SELECT id, source, author, visibility, body, created_at
        FROM ticket_notes
        WHERE ticket_id = $1
        ORDER BY created_at DESC
        LIMIT 40
    """, ticket_id)
    for note in notes:
        note["body"] = _truncate(note.get("body"), 700)
    attachments = await fetchall("""
        SELECT id, note_id, filename, content_type, storage_ref, sha256,
               size_bytes, metadata, created_at
        FROM ticket_attachments
        WHERE ticket_id = $1
        ORDER BY created_at DESC
        LIMIT 40
    """, ticket_id)
    for attachment in attachments:
        attachment["metadata"] = _truncate(attachment.get("metadata"), 1000)
    changes = await fetchall("""
        SELECT id, agent_id, action, target, reason, status, requested_by,
               approved_by, approved_at, rejected_reason, result, risk_level,
               requested_at, expires_at
        FROM change_requests
        WHERE ticket_id = $1
        ORDER BY requested_at DESC
        LIMIT 40
    """, ticket_id)
    for change in changes:
        change["reason"] = _truncate(change.get("reason"), 500)
        change["rejected_reason"] = _truncate(change.get("rejected_reason"), 500)
        change["result"] = _truncate(change.get("result"), 700)
    tasks = await fetchall("""
        SELECT id, agent_id, task_type, status, progress_pct, work_dir,
               pid, error_message, created_at, started_at,
               completed_at
        FROM agent_tasks
        WHERE ticket_id = $1
        ORDER BY created_at DESC
        LIMIT 25
    """, ticket_id)
    for task in tasks:
        task["log_tail"] = ""
        if task_log_lines and task.get("work_dir"):
            task["log_tail"] = _truncate(
                _tail_file(os.path.join(task["work_dir"], "output.log"), task_log_lines),
                1200,
            )

    cicd_runs = await fetchall("""
        SELECT id, provider, repo_ref, branch, commit_sha, target_url, status,
               summary, findings, tool_results, change_id, created_by,
               created_at, completed_at
        FROM cicd_security_runs
        WHERE ticket_id = $1
        ORDER BY created_at DESC
        LIMIT 20
    """, ticket_id)
    for run in cicd_runs:
        findings = _loads(run.get("findings"), [])
        tool_results = _loads(run.get("tool_results"), {})
        run["finding_count"] = len(findings) if isinstance(findings, list) else 0
        run["severity_counts"] = _severity_counts(findings if isinstance(findings, list) else [])
        compact_findings = []
        for finding in (findings[:10] if isinstance(findings, list) else []):
            compact_findings.append({
                "tool": finding.get("tool"),
                "severity": finding.get("severity"),
                "rule_id": _truncate(finding.get("rule_id"), 120),
                "title": _truncate(finding.get("title"), 180),
                "path": _truncate(finding.get("path"), 160),
                "url": _truncate(finding.get("url"), 160),
                "package": _truncate(finding.get("package"), 120),
                "fixed_version": _truncate(finding.get("fixed_version"), 120),
            })
        run["findings"] = compact_findings
        run["tool_results"] = _compact_tool_results(tool_results if isinstance(tool_results, dict) else {})
        run["summary"] = _truncate(run.get("summary"), 500)
    postmortems = await fetchall("""
        SELECT id, agent_id, task_id, status, summary, improvements,
               workflow_proposal, created_by, created_at, updated_at
        FROM postmortems
        WHERE ticket_id = $1
        ORDER BY created_at DESC
        LIMIT 10
    """, ticket_id)
    for postmortem in postmortems:
        postmortem["summary"] = _truncate(postmortem.get("summary"), 1800)
        postmortem["improvements"] = _truncate(postmortem.get("improvements"), 1800)
        postmortem["workflow_proposal"] = _truncate(postmortem.get("workflow_proposal"), 1800)
    audit = await fetchall("""
        SELECT id, actor, action, target, details, created_at, 'audit' AS source
        FROM audit_log
        WHERE target ILIKE $1 OR details::text ILIKE $2
        UNION ALL
        SELECT id, COALESCE(actor, 'system') AS actor, action, target, details,
               created_at, 'event' AS source
        FROM event_log
        WHERE target ILIKE $1 OR details::text ILIKE $2
        ORDER BY created_at DESC
        LIMIT 15
    """, f"%ticket_{ticket_id}%", f"%\"ticket_id\": {ticket_id}%")
    for entry in audit:
        entry["details"] = _truncate(entry.get("details"), 400)

    return {
        "ticket": ticket,
        "notes": list(reversed(notes)),
        "attachments": attachments,
        "change_requests": changes,
        "agent_tasks": tasks,
        "cicd_runs": cicd_runs,
        "postmortems": postmortems,
        "audit": audit,
        "guidance": {
            "use_this_endpoint_first": True,
            "write_result_to": "POST /api/postmortems",
            "required_status": "ready_for_review",
        },
    }


@router.post("/synthesize/{ticket_id}")
async def synthesize_postmortem_route(
    ticket_id: int,
    agent_id: int = Body(None),
    task_id: int = Body(None),
    created_by: str = Body("postmortem-supervisor"),
    reason: str = Body("manual_supervisor_synthesis"),
):
    return await synthesize_postmortem(ticket_id, agent_id, task_id, created_by, reason)


@router.get("/{postmortem_id}")
async def get_postmortem(postmortem_id: int):
    row = await fetchrow("SELECT * FROM postmortems WHERE id = $1", postmortem_id)
    if not row:
        return {"error": "Postmortem not found"}
    ticket = None
    if row.get("ticket_id"):
        ticket = await fetchrow("SELECT * FROM tickets WHERE id = $1", row["ticket_id"])
    workflow = await fetchrow(
        "SELECT id, name, status, version, updated_at FROM agent_workflows WHERE name = $1",
        _workflow_name(postmortem_id, ticket),
    )
    articles = await fetchall("""
        SELECT id, title, category, source, external_ref, updated_at
        FROM knowledge_articles
        WHERE external_ref = $1
        ORDER BY updated_at DESC
    """, f"postmortem:{postmortem_id}")
    skills = await fetchall("""
        SELECT id, name, category, enabled, updated_at
        FROM agent_skills
        WHERE name LIKE $1
        ORDER BY name
    """, f"postmortem-{postmortem_id}-%")
    row["promotion_assets"] = {
        "knowledge_articles": articles,
        "workflow": workflow,
        "skills": skills,
    }
    return row


@router.post("")
async def create_postmortem(
    ticket_id: int = Body(None),
    agent_id: int = Body(None),
    task_id: int = Body(None),
    status: str = Body("draft"),
    summary: str = Body(""),
    went_well: str = Body(""),
    improvements: str = Body(""),
    workflow_proposal: str = Body(""),
    skill_proposals: list = Body([]),
    test_cases: list = Body([]),
    guardrails: list = Body([]),
    documentation: str = Body(""),
    created_by: str = Body("dashboard"),
):
    postmortem_id = await fetchval("""
        INSERT INTO postmortems (
            ticket_id, agent_id, task_id, status, summary, went_well,
            improvements, workflow_proposal, skill_proposals, test_cases,
            guardrails, documentation, created_by
        )
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
        RETURNING id
    """, ticket_id, agent_id, task_id, status, summary, went_well,
        improvements, workflow_proposal, json_dumps(skill_proposals or []),
        json_dumps(test_cases or []), json_dumps(guardrails or []),
        documentation, created_by)
    await log_event("postmortem", "info", created_by, "postmortem_created",
                    f"postmortem_{postmortem_id}", {"ticket_id": ticket_id, "status": status})
    return {"id": postmortem_id, "status": "created"}


@router.put("/{postmortem_id}")
async def update_postmortem(
    postmortem_id: int,
    status: str = Body(None),
    summary: str = Body(None),
    went_well: str = Body(None),
    improvements: str = Body(None),
    workflow_proposal: str = Body(None),
    skill_proposals: list = Body(None),
    test_cases: list = Body(None),
    guardrails: list = Body(None),
    documentation: str = Body(None),
    review_notes: str = Body(None),
):
    allowed = {
        "status": status,
        "summary": summary,
        "went_well": went_well,
        "improvements": improvements,
        "workflow_proposal": workflow_proposal,
        "skill_proposals": json_dumps(skill_proposals) if skill_proposals is not None else None,
        "test_cases": json_dumps(test_cases) if test_cases is not None else None,
        "guardrails": json_dumps(guardrails) if guardrails is not None else None,
        "documentation": documentation,
        "review_notes": review_notes,
    }
    fields = []
    params = []
    idx = 1
    for name, value in allowed.items():
        if value is not None:
            fields.append(f"{name} = ${idx}")
            params.append(value)
            idx += 1
    if not fields:
        return {"error": "No fields to update"}
    fields.append("updated_at = NOW()")
    params.append(postmortem_id)
    await execute(f"UPDATE postmortems SET {', '.join(fields)} WHERE id = ${idx}", *params)
    await log_event("postmortem", "info", "dashboard", "postmortem_updated",
                    f"postmortem_{postmortem_id}", {"fields": [f.split(' = ')[0] for f in fields[:-1]]})
    return {"status": "updated", "id": postmortem_id}


@router.post("/{postmortem_id}/review")
async def review_postmortem(
    postmortem_id: int,
    reviewed_by: str = Body("dashboard"),
    review_notes: str = Body(""),
    approved: bool = Body(False),
):
    status = "approved" if approved else "needs_revision"
    await execute("""
        UPDATE postmortems
        SET status = $1, reviewed_by = $2, reviewed_at = NOW(),
            review_notes = $3, updated_at = NOW()
        WHERE id = $4
    """, status, reviewed_by, review_notes, postmortem_id)
    await log_event("postmortem", "info", reviewed_by, "postmortem_reviewed",
                    f"postmortem_{postmortem_id}", {"status": status})
    return {"status": status, "id": postmortem_id}


@router.post("/{postmortem_id}/promote")
async def promote_postmortem(
    postmortem_id: int,
    create_knowledge: bool = Body(True),
    create_workflow: bool = Body(True),
    create_skills: bool = Body(True),
    workflow_status: str = Body("draft"),
    created_by: str = Body("dashboard"),
    mark_promoted: bool = Body(True),
):
    postmortem = await fetchrow("SELECT * FROM postmortems WHERE id = $1", postmortem_id)
    if not postmortem:
        return {"error": "Postmortem not found"}

    ticket = None
    if postmortem.get("ticket_id"):
        ticket = await fetchrow("SELECT * FROM tickets WHERE id = $1", postmortem["ticket_id"])

    skill_ids = []
    skill_actions = []
    skill_proposals = _loads(postmortem.get("skill_proposals"), [])
    if create_skills:
        for idx, proposal in enumerate(skill_proposals or [], start=1):
            name = _skill_name_from_proposal(proposal, postmortem_id, idx)
            description = ""
            category = "postmortem"
            if isinstance(proposal, dict):
                description = proposal.get("description") or proposal.get("purpose") or proposal.get("title") or ""
                category = proposal.get("category") or category
            else:
                description = str(proposal)
            prompt_template = _skill_prompt_from_proposal(proposal, postmortem)
            existing_skill = await fetchrow("SELECT id FROM agent_skills WHERE name = $1", name)
            skill_id = await fetchval("""
                INSERT INTO agent_skills (name, description, category, prompt_template, enabled, assigned_to_all)
                VALUES ($1, $2, $3, $4, true, false)
                ON CONFLICT (name) DO UPDATE SET
                    description = EXCLUDED.description,
                    category = EXCLUDED.category,
                    prompt_template = EXCLUDED.prompt_template,
                    enabled = true,
                    updated_at = NOW()
                RETURNING id
            """, name, description, category, prompt_template)
            skill_ids.append(skill_id)
            skill_actions.append({"id": skill_id, "name": name, "action": "updated" if existing_skill else "created"})

    workflow_id = None
    workflow_name = None
    workflow_action = "skipped"
    ticket_class = _ticket_class(ticket)
    if create_workflow:
        workflow_name = _workflow_name(postmortem_id, ticket)
        existing_workflow = await fetchrow("SELECT id FROM agent_workflows WHERE name = $1", workflow_name)
        workflow_action = "updated" if existing_workflow else "created"
        test_plan = "\n".join(_text_lines(_loads(postmortem.get("test_cases"), [])))
        guardrails = _loads(postmortem.get("guardrails"), [])
        approval_policy = {
            "source": "postmortem_promotion",
            "postmortem_id": postmortem_id,
            "ticket_id": postmortem.get("ticket_id"),
            "requires_human_review_before_activation": True,
            "production_changes_require_approval": True,
            "guardrails": guardrails,
        }
        workflow_id = await fetchval("""
            INSERT INTO agent_workflows (
                name, description, ticket_class, trigger_type, status, blueprint,
                test_plan, test_results, approval_policy, skill_ids, created_by
            )
            VALUES ($1, $2, $3, 'manual', $4, $5, $6, $7, $8, $9, $10)
            ON CONFLICT (name) DO UPDATE SET
                description = EXCLUDED.description,
                ticket_class = EXCLUDED.ticket_class,
                status = EXCLUDED.status,
                version = agent_workflows.version + 1,
                blueprint = EXCLUDED.blueprint,
                test_plan = EXCLUDED.test_plan,
                test_results = EXCLUDED.test_results,
                approval_policy = EXCLUDED.approval_policy,
                skill_ids = EXCLUDED.skill_ids,
                updated_at = NOW()
            RETURNING id
        """,
            workflow_name,
            postmortem.get("summary") or "Workflow drafted from postmortem learning.",
            ticket_class,
            workflow_status,
            postmortem.get("workflow_proposal") or postmortem.get("improvements") or "Review ticket evidence and convert repeated steps into a reusable workflow.",
            test_plan,
            "Generated from postmortem promotion. Requires human review and a workflow run before production activation.",
            json_dumps(approval_policy),
            json_dumps(skill_ids),
            created_by,
        )

    knowledge_article_id = None
    knowledge_action = "skipped"
    if create_knowledge:
        title = f"Postmortem knowledge: {(ticket or {}).get('title') or postmortem_id}"[:500]
        body = _postmortem_article_body(postmortem, ticket, skill_ids, workflow_name)
        tags = ["postmortem", f"postmortem:{postmortem_id}"]
        if postmortem.get("ticket_id"):
            tags.append(f"ticket:{postmortem['ticket_id']}")
        external_ref = f"postmortem:{postmortem_id}"
        existing_article = await fetchrow(
            "SELECT id FROM knowledge_articles WHERE external_ref = $1 ORDER BY updated_at DESC LIMIT 1",
            external_ref,
        )
        if existing_article:
            knowledge_article_id = existing_article["id"]
            knowledge_action = "updated"
            await execute("""
                UPDATE knowledge_articles
                SET title = $1, body = $2, category = $3, source = $4,
                    tags = $5, enabled = true, updated_at = NOW()
                WHERE id = $6
            """,
                title,
                body,
                ticket_class or "postmortem",
                "postmortem-promotion",
                json_dumps(tags),
                knowledge_article_id,
            )
        else:
            knowledge_action = "created"
            knowledge_article_id = await fetchval("""
                INSERT INTO knowledge_articles (title, body, category, source, tags, external_ref)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
            """,
                title,
                body,
                ticket_class or "postmortem",
                "postmortem-promotion",
                json_dumps(tags),
                external_ref,
            )

    if mark_promoted:
        await execute(
            "UPDATE postmortems SET status = 'promoted', updated_at = NOW() WHERE id = $1",
            postmortem_id,
        )

    if postmortem.get("ticket_id"):
        note = (
            "Postmortem promoted into reusable assets.\n"
            f"- Postmortem: {postmortem_id}\n"
            f"- Knowledge article: {knowledge_article_id or 'not created'} ({knowledge_action})\n"
            f"- Workflow: {workflow_id or 'not created'} ({workflow_action})\n"
            f"- Skills: {', '.join(str(s) for s in skill_ids) if skill_ids else 'none'}\n"
            "Assets remain draft/review-gated until explicitly approved for production use."
        )
        await execute("""
            INSERT INTO ticket_notes (ticket_id, source, author, body, visibility, external_ref)
            VALUES ($1, 'postmortem', $2, $3, 'internal', $4)
        """, postmortem["ticket_id"], created_by, note, f"postmortem:{postmortem_id}:promotion")

    details = {
        "postmortem_id": postmortem_id,
        "ticket_id": postmortem.get("ticket_id"),
        "knowledge_article_id": knowledge_article_id,
        "workflow_id": workflow_id,
        "skill_ids": skill_ids,
        "skill_actions": skill_actions,
        "knowledge_action": knowledge_action,
        "workflow_action": workflow_action,
        "workflow_status": workflow_status,
        "mark_promoted": mark_promoted,
    }
    await log_event("postmortem", "info", created_by, "postmortem_promoted",
                    f"postmortem_{postmortem_id}", details)
    await execute(
        "INSERT INTO audit_log (actor, action, target, details) VALUES ($1, $2, $3, $4)",
        created_by,
        "postmortem_promoted",
        f"postmortem_{postmortem_id}",
        json_dumps(details),
    )
    return {"status": "promoted", **details}
