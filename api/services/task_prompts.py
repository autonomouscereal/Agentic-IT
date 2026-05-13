"""Prompt builders for ticket, postmortem, and workflow agent tasks."""


FAST_TICKET_PROMPT = """Work this ticket end to end as quickly as possible.

Operational rules:
- First read the complete canonical ticket context using GET /api/tickets/{ticket_id}/context, then inspect notes, attachments, prior similar tickets, knowledge articles, workflows, postmortems, change requests, and available skills.
- If the context contains an active or approved workflow matching this ticket class/use case, follow that workflow first and record any deviation in a ticket note.
- Keep scanning for user notes or ticket updates while working. If the ticketing provider cannot expose notes yet, state that gap in the checkpoint and continue with available context.
- Do not create a reusable workflow unless the task explicitly asks for workflow creation or automation.
- If a potentially destructive or environment-changing action is needed, create a change request with POST /api/changes/request and poll GET /api/changes/{change_id}/status until approved before taking that action.
- Change request body shape is exactly: {"agent_id": <agent_instance_id>, "ticket_id": {ticket_id}, "action": "short verb phrase", "target": "system/account/domain", "reason": "why approval is required", "risk_level": "low|medium|high", "approval_policy": {"auto_complete": false}}. Do not use title/description fields for change requests.
- After an approved change is executed and verified, immediately mark it complete with POST /api/changes/{change_id}/complete and include compile/test/diff or operational evidence in the result.
- If investigation proves an alert is a false positive, classify it that way in a ticket note with the exact evidence, affected rule id/signature, observed benign source, and residual risk. Do not suppress anything unless the benign pattern is precise and repeatable. For suppression/rule tuning, create a change request first, include the proposed exact match criteria, expiration/review date, rollback, and a test plan proving the tuned rule still catches malicious variants.
- In lab/demo runs, if no concrete provider action adapter is available for an approved containment action, do not browse broad tool inventory. Complete the approved gate with explicit simulated control evidence, add a ticket note, and name the production adapter that would perform the real operation.
- If you cannot proceed without requester input, POST /api/tickets/{ticket_id}/request-info with a concise question, recipient/contact method when known, and context. Then update checkpoint.json with status waiting_for_user and stop. When a user response arrives, the dashboard will record it with /api/tickets/{ticket_id}/user-response and may resume the ticket.
- Prefer non-destructive investigation, documentation, and clear ticket notes.
- Add ticket notes with POST /api/tickets/{ticket_id}/notes whenever you have meaningful progress, blockers, evidence, or resolution details.
- When writing ticket notes, include explicit attribution fields such as
  `author: agent-{agent_instance_id}` and `source: agent` once you know the
  assigned agent id, so audit trails show the note came from the agent.
- Keep shell commands simple and auditable. Avoid multiline `python -c` snippets,
  comments inside quoted shell arguments, and deeply nested quoting; if JSON
  parsing needs more than a one-liner, write/read a temporary script or file.
- Update checkpoint.json after major steps. Use status `running` for intermediate checkpoints. Only use status `done` or `completed` with progress_pct `100` after all approval gates are completed, final notes are written, and the ticket is ready to close. The file already exists; read checkpoint.json directly before writing it.
- When complete, summarize root cause, evidence, actions taken, residual risk, and recommended follow-up.
"""


POSTMORTEM_PROMPT = """Perform a full postmortem for this completed ticket and the agent work that resolved it.

First call GET /api/postmortems/evidence/{ticket_id}?task_log_lines=0. Use that compact evidence as the primary source of truth for notes, attachments, CI/CD runs, change requests, approvals, audit entries, and prior postmortems. Do not read persisted oversized tool outputs unless the compact evidence is missing critical facts. Use GET /api/tickets/{ticket_id}/context only if you need broader related-ticket or knowledge article context.

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

Persist the postmortem with POST /api/postmortems and mark it ready_for_review when complete. Include ticket_id, agent_id when known, and task_id from checkpoint.json so the supervisor can verify the artifact.
Use the exact postmortem body fields: ticket_id, agent_id, task_id, status, summary, went_well, improvements, workflow_proposal, skill_proposals, test_cases, guardrails, documentation, created_by. Text fields must be strings; skill_proposals, test_cases, and guardrails must be JSON arrays. Fold timeline, root cause, residual risk, and evidence details into summary, improvements, or documentation instead of sending extra top-level fields.
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


AUTO_ASSIGNMENT_PROMPT = """Work this auto-assigned ticket to completion with bounded context.

Operational rules:
- Read checkpoint.json directly before doing work.
- Use API base URL http://localhost:8000 inside the runner.
- First call GET /api/postmortems/evidence/{ticket_id}?task_log_lines=0 and use that compact evidence as the primary source of truth. It includes relevant reusable workflows and knowledge articles; if an active/approved/tested workflow matches this ticket, follow it first and document any deviation.
- Then call GET /api/tickets/{ticket_id} for the current ticket, provider reference, and agent_instance_id.
- Do not fetch full /api/tickets/{ticket_id}/context unless the compact evidence is missing a specific fact needed to finish the ticket.
- Add ticket notes with POST /api/tickets/{ticket_id}/notes whenever you have meaningful triage, blockers, approvals, actions, or resolution evidence.
- When writing ticket notes, include explicit attribution fields such as
  `author: agent-{agent_instance_id}` and `source: agent` once you know the
  assigned agent id, so audit trails show the note came from the agent.
- If a potentially destructive or environment-changing action is needed, create a change request with POST /api/changes/request and poll GET /api/changes/{change_id}/status until approved before taking that action.
- Change request body shape is exactly: {"agent_id": <agent_instance_id>, "ticket_id": {ticket_id}, "action": "short verb phrase", "target": "system/account/domain", "reason": "why approval is required", "risk_level": "low|medium|high", "approval_policy": {"auto_complete": false}}. Do not use title/description fields for change requests.
- After an approved change is executed and verified, immediately mark it complete with POST /api/changes/{change_id}/complete and include lab-safe operational evidence.
- If the evidence proves a false positive, write a false-positive classification note with exact matching evidence and residual risk. Only propose suppression/rule tuning through a change request with precise match terms, expiry/review date, rollback, and tests; never blanket-suppress a rule or source.
- In lab/demo runs, if no concrete provider action adapter is available for an approved containment action, do not browse broad tool inventory. Complete the approved gate with explicit simulated control evidence, add a ticket note, and name the production adapter that would perform the real operation.
- If requester input is required, POST /api/tickets/{ticket_id}/request-info, update checkpoint.json with status waiting_for_user, and stop.
- Keep shell commands simple and auditable. Avoid multiline `python -c` snippets,
  comments inside quoted shell arguments, and deeply nested quoting; if JSON
  parsing needs more than a one-liner, write/read a temporary script or file.
- Update checkpoint.json after major steps. Use status `running` for intermediate checkpoints. Only use status `done` or `completed` with progress_pct `100` after all approval gates are completed, final notes are written, and the ticket is ready to close.
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


def build_auto_assignment_prompt(ticket, extra_prompt=None):
    title = ticket.get("title") or f"ticket #{ticket.get('id')}"
    body = [
        AUTO_ASSIGNMENT_PROMPT,
        "",
        f"Ticket id: {ticket.get('id')}",
        f"Ticket to resolve: {title}",
    ]
    if extra_prompt:
        body.extend(["", "RACI auto-assignment instruction:", extra_prompt])
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
