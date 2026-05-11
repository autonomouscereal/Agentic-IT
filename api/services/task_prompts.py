"""Prompt builders for ticket, postmortem, and workflow agent tasks."""


FAST_TICKET_PROMPT = """Work this ticket end to end as quickly as possible.

Operational rules:
- First read the complete canonical ticket context using GET /api/tickets/{ticket_id}/context, then inspect notes, attachments, prior similar tickets, knowledge articles, workflows, postmortems, change requests, and available skills.
- Keep scanning for user notes or ticket updates while working. If the ticketing provider cannot expose notes yet, state that gap in the checkpoint and continue with available context.
- Do not create a reusable workflow unless the task explicitly asks for workflow creation or automation.
- If a potentially destructive or environment-changing action is needed, create a change request with POST /api/changes/request and poll GET /api/changes/{change_id}/status until approved before taking that action.
- Prefer non-destructive investigation, documentation, and clear ticket notes.
- Add ticket notes with POST /api/tickets/{ticket_id}/notes whenever you have meaningful progress, blockers, evidence, or resolution details.
- Update checkpoint.json after major steps. The file already exists; read checkpoint.json directly before writing it.
- When complete, summarize root cause, evidence, actions taken, residual risk, and recommended follow-up.
"""


POSTMORTEM_PROMPT = """Perform a full postmortem for this completed ticket and the agent work that resolved it.

Analyze:
- The original ticket context, notes, attachments, related tickets, and knowledge articles that were available.
- The agent task logs, checkpoints, change requests, approvals, errors, and retries.
- What worked, what failed, what was slow, what was missing, and what should be automated next time.

Produce:
- A concise postmortem summary.
- A reusable workflow proposal for future similar tickets.
- Candidate skills the agents should create or update.
- Test cases needed before the workflow can be trusted.
- Guardrails and approval gates for any destructive or environment-changing action.
- Documentation updates needed for operators.

Persist the postmortem with POST /api/postmortems and mark it ready_for_review when complete.
Do not deploy new automation directly. If automation creation is requested, create a follow-up workflow-build task or ticket and mark it for human review before production use.
Update checkpoint.json as you work. The file already exists; read checkpoint.json directly before writing it.
"""


WORKFLOW_BUILD_PROMPT = """Create or improve a reusable workflow/automation for this class of ticket.

Build in this order:
- Gather ticket context, related historical tickets, knowledge articles, existing skills, and operator notes.
- Draft the workflow blueprint and approval boundaries.
- Create or update the needed skills/scripts in a test-safe way.
- Build an end-to-end test plan with positive, negative, rollback, and approval-gate cases.
- Execute safe tests in the test environment only.
- Document deployment steps, required configuration, required credentials by vault key name, and operational runbook.
- Stop before production deployment and request human review/approval.

Persist the workflow with POST /api/workflows. Keep it draft or tested until human review approves it.
All destructive or environment-changing actions must go through change management. Do not hardcode secrets. Use raw PostgreSQL only for database work.
Update checkpoint.json after major steps. The file already exists; read checkpoint.json directly before writing it.
"""


def build_ticket_resolution_prompt(ticket, extra_prompt=None):
    title = ticket.get("title") or f"ticket #{ticket.get('id')}"
    body = [
        FAST_TICKET_PROMPT,
        "",
        f"Ticket to resolve: {title}",
    ]
    if extra_prompt:
        body.extend(["", "Additional operator instruction:", extra_prompt])
    return "\n".join(body)


def build_postmortem_prompt(ticket, extra_context=None):
    body = [
        POSTMORTEM_PROMPT,
        "",
        f"Ticket under review: {ticket.get('title') or ticket.get('id')}",
    ]
    if extra_context:
        body.extend(["", "Additional postmortem context:", extra_context])
    return "\n".join(body)


def build_workflow_prompt(ticket, extra_context=None):
    body = [
        WORKFLOW_BUILD_PROMPT,
        "",
        f"Workflow source ticket: {ticket.get('title') or ticket.get('id')}",
    ]
    if extra_context:
        body.extend(["", "Operator workflow request/context:", extra_context])
    return "\n".join(body)
