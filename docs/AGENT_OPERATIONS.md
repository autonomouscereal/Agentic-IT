# Agent Operations Runbook

Last updated: 2026-05-11.

## Operator Mental Model

Agents are not dashboard status flags. A real agent run has:

- an `agents` row
- an `agent_tasks` row
- a work directory
- a harness subprocess
- streamed logs
- checkpoints
- human-readable ticket notes
- audit/event records

The dashboard should let operators answer:

- Did a harness process actually start?
- Which model did it use?
- Which proxy did it hit?
- What did it output?
- What was the last checkpoint?
- Did it request approval before risky work?
- Did the process clean up after completion?
- Can a demo viewer follow the story from ticket notes without reading raw logs?

## Demo-Friendly Notes

Agents are instructed to write their own ticket notes, but the control plane
also writes progress notes so the dashboard stays understandable even when a
local model is terse.

Automatic notes are written for:

- agent assignment
- agent start
- new checkpoint steps
- approved change auto-completion
- agent completion
- agent failure
- postmortem supervisor fallback

These notes use sources such as `agent-control-plane`, `agent-checkpoint`, and
`agent-supervisor`. They appear in:

- ticket detail timeline
- overview recent activity
- `GET /api/dashboard/audit?source=note`
- `GET /api/dashboard/audit?ticket_id=<id>`

Use the ticket modal's **Full Audit Trail** action to jump into the Audit page
with the ticket filter preloaded.

## Creating Agents

From existing ticket:

```bash
curl -sS -X POST http://localhost:25480/api/tickets/28/assign-agent \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen/qwen3.6-27b"}'
```

From free prompt:

```bash
curl -sS -X POST http://localhost:25480/api/agents/create-from-prompt \
  -H 'Content-Type: application/json' \
  -d '{"model":"qwen/qwen3.6-27b","prompt":"Investigate this synthetic request and write a ticket note."}'
```

## Task Types

`ticket_resolution`

- Fast path.
- Resolve the ticket as quickly and safely as possible.
- Do not create reusable workflows unless explicitly asked.

`postmortem`

- Review completed/in-progress work.
- Record summary, improvements, workflow proposal, skill proposals, tests, guardrails, and documentation.

`workflow_build`

- Build or improve reusable workflow blueprint.
- Define test plan and approval policy.
- Keep workflow draft/tested until human review.

`ad_hoc`

- Free prompt from dashboard.
- Still creates a canonical local ticket for auditability.

## Checkpoint Protocol

Each work directory contains:

```text
checkpoint.json
output.log
.claude/CLAUDE.md
.claude/settings.json
```

Agents must update `checkpoint.json` after major steps:

```json
{
  "step": "scope-ticket",
  "status": "running",
  "output": "Fetched ticket context and notes.",
  "progress_pct": 30,
  "timestamp": "2026-05-11T12:00:00"
}
```

Completion status should be:

```json
{
  "step": "done",
  "status": "done",
  "output": "Ticket resolved and notes written.",
  "progress_pct": 100,
  "timestamp": "2026-05-11T12:05:00"
}
```

When a checkpoint reaches `done` or `completed`, `task_tracker` completes the task and terminates the harness process.

If the task has approved, agent-linked changes, completion also advances those
changes to `completed` unless the approval policy explicitly requires manual
completion. This prevents the stale state where approved remediation work
finished but the change never moved past `approved`.

Postmortem tasks are learning work, not ticket-resolution ownership. Spawning a
postmortem agent does not reopen the ticket or replace the ticket's primary
resolver agent.

If a local-model postmortem task fails or stalls on evidence processing, the
supervisor can synthesize a bounded `ready_for_review` postmortem from the
ticket, CI/CD runs, changes, task states, notes, and audit entries:

```bash
curl -sS -X POST http://localhost:25480/api/postmortems/synthesize/88 \
  -H 'Content-Type: application/json' \
  -d '{"agent_id":56,"task_id":54,"reason":"postmortem agent stalled"}'
```

After review, promote the postmortem into reusable learning assets instead of
leaving the lesson trapped in a ticket:

```bash
curl -sS -X POST http://localhost:25480/api/postmortems/25/promote \
  -H 'Content-Type: application/json' \
  -d '{
    "create_knowledge": true,
    "create_workflow": true,
    "create_skills": true,
    "workflow_status": "draft",
    "created_by": "dashboard",
    "mark_promoted": true
  }'
```

Promotion creates a knowledge article, candidate skills, and a draft workflow
with `requires_human_review_before_activation=true`. It also writes a ticket
note and audit/event records so the operator can show exactly how a completed
ticket became future automation. Production workflow activation remains a
separate reviewed step.

The operation is idempotent. If an operator clicks Promote again after editing
the postmortem, the platform updates the same `external_ref=postmortem:{id}`
knowledge article, same deterministic workflow name, and same deterministic
skill names. The audit trail still records the repeat promotion as an update so
there is evidence of what changed without cluttering the reusable asset catalog.

## Wake

Use Wake when an agent should be nudged or restarted only if no active task exists.

Behavior:

- active queued/running task exists: refresh heartbeat and return active task id.
- no active task: spawn replacement from latest prompt/task type.
- stopped/terminated source agent: return error; use Restart instead.

## Restart

Use Restart when the current run should be abandoned and recreated.

Behavior:

- stop active task if present.
- mark old agent terminated.
- spawn replacement for same ticket/model/prompt.

## Stop

Use Stop when work must halt.

Behavior:

- terminate subprocess if tracked.
- mark task stopped.
- mark agent stopped.
- record audit/event entries.

## Diagnostics

Runner health:

```bash
curl -sS http://localhost:25480/api/agents/runner-health
```

Process view:

```bash
curl -sS http://localhost:25480/api/agents/processes
```

Task list:

```bash
curl -sS 'http://localhost:25480/api/agents/tasks?agent_id=26'
```

Logs:

```bash
curl -sS 'http://localhost:25480/api/agents/tasks/24/logs?lines=200'
```

## Known Harness Details

Claude Code command ordering matters. `--allowedTools` is variadic and must appear before `-p`. If placed near the end it can swallow the prompt and Claude Code will report that input is missing.

The API container runs as root in the current lab. Claude Code refuses full bypass permission mode as root. Use:

```text
AGENT_PERMISSION_MODE=acceptEdits
AGENT_ALLOWED_TOOLS=Read,Write,Bash(curl *)
```

This is enough for agents to call dashboard APIs with `curl` while keeping arbitrary destructive shell operations out of the default tool scope.

## Local Model Smoke Result

Latest verified local-model smoke:

- model: `qwen/qwen3.6-27b`
- ticket: `28`
- agent: `26`
- task: `24`
- final status: `completed`
- progress: `100`
- note written through dashboard API: yes
- active Claude processes after completion: zero

## Awaiting requester input

Agents should not spin while waiting for missing user details. When work cannot
continue without the requester, call:

```bash
curl -sS -X POST http://localhost:25480/api/tickets/<ticket_id>/request-info \
  -H "Content-Type: application/json" \
  -d '{"question":"Which host is affected?","requested_by":"agent_<id>","contact_method":"email","recipient":"user@example.local"}'
```

Then write `waiting_for_user` to `checkpoint.json` and stop. The dashboard
records the outbound request as a user-visible note and moves the ticket to
`awaiting_user_response`. When a reply is received through
`/api/tickets/<ticket_id>/user-response`, the ticket returns to the previous
status and the assigned agent can be resumed if no task is active.
