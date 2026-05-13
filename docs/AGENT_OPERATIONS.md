# Agent Operations Runbook

Last updated: 2026-05-13.

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

Treat `progress_pct` as a UI hint only. It is allowed to lag, jump, or reflect
the last stream event rather than real work completion. Operator status comes
from active evidence:

- `agents.status` and `agent_tasks.status`
- whether the recorded PID is still alive in the API container
- recent `output.log` stream lines and tool results
- `checkpoint.json` content and `agent_tasks.checkpoints`
- ticket notes written by the agent/control plane
- `audit_log` and `agent_audit_reviews`
- PostgreSQL memory hook events for the agent workspace, when memory is enabled

The dashboard should let operators answer:

- Did a harness process actually start?
- Which model did it use?
- Which proxy did it hit?
- What did it output?
- What was the last checkpoint?
- Did it request approval before risky work?
- Did the process clean up after completion?
- Can a demo viewer follow the story from ticket notes without reading raw logs?

## Real-Time Metrics

The overview calls `GET /api/dashboard/ops-metrics` for operator and demo
metrics. The goal is to show how the autonomous system is actually performing,
not just whether a process exists.

Agent timing definitions:

- `running_seconds`: server-derived wall time from agent start to finish/now,
  clamped at zero so browser clock skew cannot show negative durations.
  This is retained for diagnostics and is zero for stalled agents.
- `idle_seconds`: server-derived time since the latest heartbeat or start time,
  clamped at zero. This is diagnostic only and is zero for stalled agents.
- `gate_wait_seconds`: approval/user-response/change wait time associated with
  the task window.
- `task_working_seconds`: task runtime minus gate wait, clamped at zero. Use
  this for "how long did the agent work" SLA/efficiency conversations.
  The Agents tab labels this as `Total work time` and does not show idle/gate
  wait timers as primary card metrics.

Dashboard operational cards currently show:

- average agent working time, with gate wait removed.
- 30-day SLA compliance, breach count, and at-risk count.
- pending approval gates and average gate wait.
- automation activity, active workflows, and healthy tool count.

Task-type rows include total/completed counts, average working time, and p95
working time. These values are intentionally calculated by PostgreSQL on the
server so every browser sees the same nonnegative numbers.

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

## Agent And Task Statuses

Agent status and task status are related but not identical:

- `agents.status` is the operator lifecycle for an agent instance.
- `agent_tasks.status` is the runnable work item state for that agent.
- `progress_pct` is not status. It is only a coarse UI hint.

Agent statuses:

- `spawned`: agent row exists and the task is queued or about to start.
- `running` / `working`: the harness has started and recent process, stream,
  checkpoint, note, or audit evidence should be used to judge activity.
- `pending_approval`: the agent intentionally stopped behind a change approval
  gate. This is not stalled.
- `awaiting_access`: the agent hit a permission wall and created or referenced
  an access request. This is not stalled.
- `awaiting_user_response`: the agent asked the requester for information and
  should resume after the response arrives. This is not stalled.
- `blocked`: the agent stopped at another durable wait state that requires
  operator or workflow action.
- `stalled`: watchdog/monitor evidence says the agent stopped producing useful
  heartbeat/output outside an approval, access, or user-response gate. Stalled
  cards report `Total work time` as `0s` until a replacement run is started.
- `finished`: the task completed and final evidence was recorded.
- `failed`: the harness or supervisor failed the task.
- `stopped`: an operator stopped the task through the dashboard/API.
- `terminated`: a prior agent instance was replaced, unassigned, or restarted.
- `resolved`: legacy terminal value retained for old rows only.

Task statuses:

- `queued`: waiting for the bounded local-model lane or priority queue.
- `running`: process is active or being tracked.
- `pending_approval`, `awaiting_access`, `awaiting_user_response`, `blocked`:
  durable wait states from checkpoint guard logic.
- `completed`: task reached final `done` / `100%` or supervisor-confirmed
  completion evidence.
- `failed` / `stopped`: terminal non-success states.

Dashboard category mapping:

- Queued Agents: task `queued` with agent `spawned` or `running`.
- Active Agents: agent `spawned`, `running`, or `working`, excluding queued
  tasks.
- Waiting On Gate: agent `pending_approval`, `awaiting_access`,
  `awaiting_user_response`, or `blocked`.
- Stalled Agents: agent `stalled` only.
- Agent History: `finished`, `failed`, `stopped`, `terminated`, and legacy
  `resolved`.

These categories are intended to be non-overlapping in the UI. An agent behind
approval belongs in `Waiting On Gate`; it should not be counted as stalled.

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

Task completion status should be:

```json
{
  "step": "done",
  "status": "done",
  "output": "Agent work complete and notes written.",
  "progress_pct": 100,
  "timestamp": "2026-05-11T12:05:00"
}
```

When a checkpoint reaches `done` or `completed`, `task_tracker` completes the
agent task and terminates the harness process. This does not resolve the
ticket by itself.

If the task has approved, agent-linked changes, completion also advances those
changes to `completed` unless the approval policy explicitly requires manual
completion. This prevents the stale state where approved remediation work
finished but the change never moved past `approved`.

Ticket closure is a separate workflow decision, but the default ticket-agent
workflow is still to close the ticket explicitly when the work is truly done.
Agents or operators call `POST /api/tickets/{ticket_id}/status` when the ticket
should move to `resolved`, `closed`, or another state. Set `close_provider:
true` only when the external ticketing record should also be closed.
Deployments that require human review, requester response, access grants, or
manual provider handoff can leave tickets open after the agent task finishes,
but the agent must write a note explaining that handoff.

Below-100 wait checkpoints are intentionally not completion. If an agent writes
`waiting_for_access`, `pending_approval`, `pending_access`, `blocked`,
`access_denied`, or `needs_access`, the runner records a waiting/blocked task
state, keeps the ticket unresolved, and writes an operator note. This is the
durable handoff point for access grants, approval gates, and user follow-up.

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

## Local Model Runner Policy

The reference AI server runs slow local models. Treat output/activity, process
state, checkpoints, notes, and audit findings as the source of truth. Do not use
short wall-clock timeouts to judge local agent work.

Current reference defaults:

```text
MAX_CONCURRENT_AGENTS=1
AGENT_TIMEOUT_MINUTES=0
AGENT_NO_OUTPUT_STALL_SECONDS=3600
AUTO_ASSIGNMENT_MAX_ACTIVE_PER_RULE=1
```

`AGENT_TIMEOUT_MINUTES=0` disables the fixed wall-clock process timeout.
`AGENT_NO_OUTPUT_STALL_SECONDS` is a configurable silent-harness guard. It is
not a progress timer: agents that are streaming output, using tools, updating
checkpoints, or writing notes should continue.
`AUTO_ASSIGNMENT_MAX_ACTIVE_PER_RULE=1` keeps RACI-driven auto-assignment from
queueing several same-rule local agents while one Security Operations/EDR agent
is already active. Set it higher, or `0` for unlimited, in faster environments.

Model-backed smoke and acceptance scripts must serialize against the live local
model lane. Before spawning a smoke agent, wait for `/api/agents/active` to
return `count=0`, run the auditor while waiting, and record the active agent ids
in the log. In the reference lab, use:

```text
AGENT_SMOKE_WAIT_SECONDS=3600
AGENT_SMOKE_IDLE_WAIT_SECONDS=3600
AGENT_SMOKE_STOP_ON_TIMEOUT=false
```

The smoke wrapper's wait window is evidence reporting only. It must not stop a
streaming or tool-using agent unless an operator explicitly sets
`AGENT_SMOKE_STOP_ON_TIMEOUT=true` for that run.

Runner health:

```bash
curl -sS http://localhost:25480/api/agents/runner-health
```

Live process snapshot:

```bash
curl -sS http://localhost:25480/api/agents/processes
```

Task stream tail:

```bash
curl -sS 'http://localhost:25480/api/agents/tasks/<task_id>/logs?lines=200'
```

Agent auditor evidence:

```bash
curl -sS 'http://localhost:25480/api/agents/audits?agent_id=<agent_id>&limit=20'
```

Ticket activity and notes:

```bash
curl -sS http://localhost:25480/api/tickets/<ticket_id>/context
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

## Permission Walls And Access Requests

When an agent cannot continue because it lacks a role, group membership, system
permission, repository access, mailbox permission, or SIEM/index access, it
should create an access request instead of bypassing the control:

```bash
curl -sS -X POST http://localhost:25480/api/tickets/<ticket_id>/access-request \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": 123,
    "resource": "GitLab project demo/private-infra",
    "permission": "Developer repository read access",
    "account_ref": "agent-123",
    "assignment_group": "DevSecOps",
    "risk_level": "medium",
    "reason": "Repository API returned 403; least-privilege read access is required."
  }'
```

The dashboard creates a child access request ticket and a parent-ticket approval
gate. The agent writes `waiting_for_access` to `checkpoint.json` and stops.
When the gate is approved, the approval handler resumes the original ticket if
no active task is already running. The resumed agent verifies the grant evidence,
marks the access gate complete, and continues the original work.

Seeded RACI access rules:

- `GitLab repository access` routes to DevSecOps and the repository owner.
- `SIEM analyst access` routes to Identity & Access with Security Operations as
  accountable owner.
