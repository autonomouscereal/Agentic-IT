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
- audit/event records

The dashboard should let operators answer:

- Did a harness process actually start?
- Which model did it use?
- Which proxy did it hit?
- What did it output?
- What was the last checkpoint?
- Did it request approval before risky work?
- Did the process clean up after completion?

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

