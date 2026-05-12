# Awaiting User Response Workflow

Agents and operators can now pause a ticket cleanly when the next step requires
requester input.

## API Contract

Request information:

```bash
curl -sS -X POST http://localhost:25480/api/tickets/123/request-info \
  -H "Content-Type: application/json" \
  -d '{
    "question": "Which host is affected and what error do you see?",
    "requested_by": "agent_42",
    "contact_method": "email",
    "recipient": "user@example.local",
    "context": "Needed before endpoint triage can continue."
  }'
```

Effects:

- Adds a user-visible ticket note with the outbound question.
- Sets ticket status to `awaiting_user_response`.
- Stores the previous status inside `provider_payload.awaiting_user_response`.
- Records a structured `user_info_requested` event for audit/search.

Record the user answer:

```bash
curl -sS -X POST http://localhost:25480/api/tickets/123/user-response \
  -H "Content-Type: application/json" \
  -d '{
    "response": "Host DEMO-LAPTOP-44. Error: VPN DNS lookup failed.",
    "responder_name": "Demo User",
    "responder_email": "demo@example.local",
    "resume_agent": true
  }'
```

Effects:

- Adds an internal `user-response` note.
- Restores the prior ticket status, defaulting to `in_progress`.
- If the ticket has an assigned agent and no active task, starts a continuation
  agent with the latest ticket context.
- Records `user_response_received` for audit/search.

## Agent Prompt Rule

Ticket-resolution prompts instruct agents to call `/request-info`, write
`waiting_for_user` into `checkpoint.json`, and stop when requester information is
required. This prevents long polling loops while still leaving a durable resume
point.

## Test

```bash
python3 scripts/smoke_user_response_workflow.py http://localhost:25480
```

The smoke creates a ticket, asks for details, verifies
`awaiting_user_response`, records a user answer, and confirms both notes are
present in canonical ticket context.
