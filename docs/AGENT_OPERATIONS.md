# Agent Operations Runbook

Last updated: 2026-05-20.

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
- AI proxy / LM Studio activity for the selected model route
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

## Proxy And Model Activity

Use proxy and model-server evidence as another liveness signal before deciding
an agent is stuck. A stale checkpoint can coexist with active local inference,
especially on long Qwen/LM Studio runs. Do not stop or restart an agent only
because `progress_pct` or `checkpoint.json` has not advanced if proxy/model
logs show recent `/v1/messages` activity for that agent's selected model.

Reference lab checks on the AI server:

```bash
curl -s http://localhost:4001/health
curl -s http://localhost:4001/v1/models
docker logs --since 20m --tail 200 ai-proxy
curl -s http://localhost:25480/api/agents/active
curl -s http://localhost:25480/api/agents/processes
```

Interpretation:

- Recent `POST /v1/chat/completions` lines from Hermes through `ai-proxy`
  mean the Hermes harness is actively using a local or cloud OpenAI-compatible
  model route.
- Recent `POST /v1/messages` lines from `claude-cli` through `ai-proxy` mean
  the Claude Code fallback harness is actively using an Anthropic-compatible
  route.
- Repeated `GET /v1/models` alone proves the runner health probe is alive, not
  that the agent is making reasoning progress.
- Combine proxy timestamps with agent heartbeat, process PID, output log
  growth, ticket notes, audit events, and checkpoint state.
- If proxy/model activity is recent but no ticket notes/checkpoints are moving,
  prefer light steering through ticket notes over stopping the harness.
- For live capability evaluations, avoid giving the agent suspected root cause,
  hostname, device type, user identity, or asset owner through steering notes
  until after the run. Operator hints can contaminate the proof by turning
  discovery into confirmation. If context must be added mid-run, label it as
  unverified operator context and record that the run is no longer a clean
  autonomous-identification proof.
- If there is no proxy/model activity, no output growth, no checkpoint movement,
  and no relevant wait gate, treat it as a no-progress reliability issue and
  document it before intervening.

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

Agent Task Runtime cards are task-run metrics, not artifact inventory. For
example, `Postmortem agent task` counts postmortem agent task runs; the actual
number of postmortem records lives in the SLA / Tool Snapshot `Postmortems`
row from `postmortem_sla.total_postmortems`. Each task-runtime card shows:

- average working time, with gate wait removed.
- completed task runs.
- total task runs.
- `95% under`, the 95th percentile working time. In plain English, 95% of
  completed task runs of that type finished at or below that time.

These values are intentionally calculated by PostgreSQL on the server so every
browser sees the same nonnegative numbers.

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

## Chat-Originated Agent Work

Ops Chat messages are a first-class agent entry point. The user starts in
Element, not the dashboard, but the work must still be visible in the same
ticket, agent, approval, provider-sync, and audit surfaces.

Expected chat path:

1. Matrix/Element user sends a message to `Agentic Ops Agent`.
2. `ops-chat-bridge` forwards the room event to `/api/ops-chat/message`.
3. The dashboard runs the configured Hermes/Claude chat harness with
   `ops_chat_tool.py`.
4. The chat harness either answers harmless/general chat directly, asks one
   concise clarification, or creates a ticket with agent-selected class,
   priority, and assignment group.
5. Operational tickets sync through the active provider adapter, iTop in the
   lab, then queue the real ticket-resolution agent when enabled.
6. If the ticket agent calls `/api/tickets/{id}/request-info`, the bridge posts
   that user-facing note back to the Matrix room.
7. The user's chat reply becomes a `user-response` ticket note and is delivered
   to active agents through the normal steering inbox.

The chat harness can decide whether work needs a ticket and where it should be
assigned. It is not an approval authority. Approval, access, credential, and
change gates must be created only when the ticket agent hits a real platform
barrier such as a vault lease denial, provider `403`, workflow policy, or
change approval requirement.

For demo-quality evidence, a chat-created ticket should show:

- an Ops Chat-created note with the Matrix room/session metadata;
- preserved recent chat context, especially when clarification happened before
  ticket creation;
- `provider=itop` and `provider_sync_status=synced` when iTop sync is enabled;
- a real agent assignment/task when the case is operational and spawning is on;
- user-facing `/request-info` or `/status` notes reflected back to Element;
- no raw provider stack trace, model transcript dump, or placeholder notes.

Use `docs/OPS_CHAT_AGENTIC_UI_TESTING_AND_DEMO_READINESS.md` as the checkpoint
for current live proof tickets and the broad UI test matrix.

## Live Note Steering

Human and provider notes can steer a running agent without stopping it. When a
note is added from `dashboard`, `itop`, `servicenow`, `jira`, `provider`,
`requester`, or `user-response`, the dashboard records an
`agent_steering_events` row for each active ticket agent and mirrors the update
into that agent's workspace:

- `agent_steering_inbox.json`
- `AGENT_STEERING.md`

Agents are prompted to read the inbox before major actions and checkpoints.
They must treat steering as additional context, keep the original objective,
document changed decisions as ticket notes, and continue unless the new note
creates an approval, access, safety, or requester wait gate. Agent-authored and
control-plane notes do not create steering events, which prevents self-steering
loops from normal progress notes.

Operational proof:

```bash
python scripts/agentic_note_steering_demo.py http://127.0.0.1:25480 qwen/qwen3.6-27b
```

Expected evidence: the ticket shows `STEERING_READY_DASHBOARD`,
`STEERING_OBSERVED_DASHBOARD`, `STEERING_READY_ITOP`,
`STEERING_OBSERVED_ITOP`, and `STEERING_COMPLETE` notes. The agent remains
active through the dashboard and iTop updates, then finishes the original task
with a 100% checkpoint.

Latest live proof: ticket `530`, iTop `UserRequest::307`, agent `193`, task
`190`, marker `NOTE_STEERING_1778787230`. Dashboard note `1075` and iTop
note `1079` both became delivered steering events, the task completed at 100%,
and a forced provider sync preserved dashboard status `resolved` even while
iTop still reported provider status `new`.

## Approval Timing And Wait Recovery

Approval gates can be approved while a local model is already inside a model
turn. In that case the next text emitted by the agent may reflect the pre-approval
worldview even though the gate is already open. The runner records explicit
`agent_model_turn_started` and `agent_model_turn_finished` events in both
`event_log` and `audit_log` so operators can compare model-turn timing against
`change_approved` and `change_completed` events.

When `POST /api/changes/{id}/approve` sees that the original agent task is
still active, it does not spawn a duplicate continuation. Instead it delivers a
dashboard-sourced steering update into `agent_steering_inbox.json` telling the
agent to re-read current change/access state before writing any wait checkpoint.

If the agent still writes a durable wait checkpoint such as `waiting_for_access`
after the associated gate is already approved or completed, the control plane
treats that checkpoint as stale. The task tracker keeps the active task in
`running` while delivering a correction; if the blocking-checkpoint watcher has
already stopped the harness, the runner marks the source agent as historical
evidence and queues a continuation agent with the stale-wait correction. If a
gate is truly still pending, the agent/task state becomes `awaiting_access`,
`pending_approval`, `awaiting_user_response`, or `blocked` instead of remaining
generic `working`.

## Wazuh Access Requests

Wazuh/SIEM provider access is lease-gated. Agents must not call Wazuh hosts
directly or ask operators for API credentials. The control plane owns provider
credentials through runtime configuration and exposes audited, agent-scoped
read endpoints only after a matching `agent_vault_leases` row exists.

Expected flow:

1. Agent requests a lease with
   `POST /api/agents/{agent_id}/vault/lease` for
   `{"system":"wazuh","resource_type":"api","resource_id":"wazuh.manager","action":"read"}`.
2. If denied, the agent creates a ticket access request and stops at
   `waiting_for_access`.
3. The access request should include `lease_request`. If a local model omits
   it but names a known resource such as `wazuh.manager API`, the dashboard now
   infers the scoped Wazuh lease and records that inference in audit/event logs.
4. When the approved gate is completed, the dashboard mints the scoped lease;
   secret values are not stored in dashboard tables or returned to the agent.
5. The resumed agent re-requests the lease and then uses
   `GET /api/agents/{agent_id}/wazuh/manager/status`,
   `GET /api/agents/{agent_id}/wazuh/rules/{rule_id}`, and, when indexer
   credentials are configured,
   `GET /api/agents/{agent_id}/wazuh/alerts/search?rule_id=...&source_ip=...`.

Audit events to look for:

- `access_request_created` with `lease_request` and
  `lease_request_inferred`.
- `access_request_lease_inferred_on_completion` when older/incomplete gates are
  repaired at completion time.
- `agent_vault_lease_granted`.
- `wazuh_provider_access_allowed`.
- `wazuh_manager_status_read`, `wazuh_rule_lookup`, or
  `wazuh_alert_search`.

Real proof script:

```bash
python scripts/agentic_wazuh_access_request_demo.py http://localhost:25480 qwen/qwen3.6-27b
```

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

### Approval-Gate Continuations

Local model harnesses do not reliably support suspending one long-running
process at a gate and later resuming that exact process after a human approval
or access grant. The control plane treats a wait checkpoint as a durable stop:
the source agent becomes historical evidence for the permission/access/user
wait, and the ticket objective resumes through a continuation agent after the
gate opens.

That continuation is still one logical ticket flow. When `_resume_agent_after_approval`
spawns a replacement, the ticket timeline gets an `agent-lifecycle` note such
as `Agent handoff after approval: 195 -> 196`. The source agent's detail also
records the continuation agent/task in `error_message`, and the source
agent/task moves to terminal `finished` / `completed` so it no longer appears in
the Waiting On Gate section. Operators should read the source agent as "stopped
correctly at a gate and handed off," not as an indefinitely running worker.

Current complex proof example: ticket `531` used agent `194` for initial
phishing/EDR triage until Wazuh access was denied, continuation agent `195`
after access change `155`, and continuation agent `196` after containment
change `156`.

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

The API also accepts the same explicit status payload on `POST`, `PUT`, and
`PATCH /api/tickets/{ticket_id}` as a compatibility path for local models that
infer a ticket-resource update. The compatibility path still requires a status
field and preserves the same audit note, status validation, access check, and
`close_provider` behavior. Prompts should continue to teach the canonical
`/status` endpoint because it is more explicit.

If a model exits cleanly without writing a terminal `checkpoint.json`, the
runner writes a final checkpoint with `status=done`, `progress_pct=100`, and a
runner-owned step before marking the task complete. This keeps workspace-file
evidence aligned with the task table for audits and self-repair.

Terminal-evidence recovery is the narrow exception for local-model finalization
gaps. If a running ticket-resolution task has no open gates, completed approval
work, final completion notes, and a promoted postmortem/workflow asset, the
supervisor may mark the ticket `resolved` and finish the task with an
`agent-supervisor` note. This is for the case where the model already completed
the real workflow and learning steps but stalled before the explicit final
status/checkpoint calls.

The successful-exit path has an even narrower done-checkpoint close recovery.
After the runner has marked the task completed and written its own agent
completion note, it may resolve the ticket only when the final checkpoint is
`done` or `completed` at `100%`, the prompt explicitly required ticket closure,
there are no open change/access gates, the ticket is not in an approval,
access, user-response, or blocked wait state, and final agent evidence notes
exist in the task window. The recovery writes an `agent-supervisor` note, calls
the provider close path for provider-backed tickets, and logs
`ticket_status_recovered_from_done_checkpoint`.

Generic task completion still does not close tickets, and any open approval,
access, or user-response gate fails closed.

Latest deployed smoke, 2026-05-15: marker
`DONE_CHECKPOINT_RECOVERY_SMOKE_1778872231` created synthetic local-only ticket
`563`, agent `217`, and task `214`; the recovery resolved the ticket, skipped
provider close as `provider_local`, recorded
`ticket_status_recovered_from_done_checkpoint`, and left zero active agents.

Below-100 wait checkpoints are intentionally not completion. If an agent writes
`waiting_for_access`, `pending_approval`, `pending_access`, `blocked`,
`access_denied`, or `needs_access`, the runner records a waiting/blocked task
state, keeps the ticket unresolved, and writes an operator note. This is the
durable handoff point for access grants, approval gates, and user follow-up.
After approval, the control plane may spawn a continuation agent rather than
resuming the exact same process; this is expected and must be recorded as an
agent-lifecycle handoff note. Once that handoff is recorded, the source
agent/task should be terminal `finished` / `completed` because its subtask was
to stop at the gate and hand off safely.

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

Current reference defaults are managed from the dashboard `Settings` page and
persisted in `agent_models.json`. Use that page to change max active agents,
per-profile timeouts, Codex reasoning effort, Codex fast mode, and scoped
routing by platform area, workflow key, ticket class, or RACI group.

Current local-model reference defaults:

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

Runtime profile timeout guidance:

- `local-only`: Hermes/local model, 60 minute timeout, max active agents usually
  `1`.
- `codex-primary`: Codex subscription/OAuth route, 10 minute timeout, high
  reasoning by default, fast mode off unless an operator enables it for a demo.
- `hermes-external`: Hermes external lab provider route, 10 minute timeout,
  with OpenRouter/local fallbacks.

`local-only` and `hermes-external` are whole-platform mode switches: when one
is active, it overrides seeded scoped assignments such as chat/demo defaults
unless a caller explicitly passes a profile, harness, or model.

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

The `curl` allowance is for dashboard/internal APIs only. Agents must never
directly browse, curl, wget, screenshot, open, or otherwise retrieve suspicious
URLs from phishing reports, SIEM/EDR alerts, unsolicited email, attachments, or
untrusted ticket text. Use passive evidence, URL/domain parsing, configured
VirusTotal/urlscan/ANY.RUN-style adapters, or approved isolated detonation
instead. Approval to block, quarantine, or contain a URL is not approval to
fetch it. The runner curl guard enforces this by blocking arbitrary external
URL hosts outside the configured `AGENT_CURL_ALLOWED_HOSTS` allowlist.

The API/agent image also carries Node.js plus Playwright Chromium for trusted
internal UI validation. Agents may use `node`, `npx playwright`, or
`playwright` for dashboard, setup, CI/CD, provider-console, or generated local
app checks. `NODE_PATH` is set so `require("playwright")` works from small
agent-written scripts. They must not use browser automation to open suspicious
URLs from tickets, email, SIEM/EDR alerts, attachments, or user text; those
stay on the passive/reputation/isolated-detonation path.

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
