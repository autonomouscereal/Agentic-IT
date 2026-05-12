# Agent Run Failure Notes - 2026-05-12

## Status Evidence Rule

Do not determine agent status from `progress_pct`. It is a dashboard/UI hint
derived from stream events and checkpoints. It can show activity even when the
agent has not completed the requested work.

Use active evidence instead:

- task and agent rows: `GET /api/agents/<agent_id>` and
  `GET /api/agents/tasks?agent_id=<agent_id>`
- live process state: `GET /api/agents/processes`
- stream tail: `GET /api/agents/tasks/<task_id>/logs?lines=200`
- checkpoint state: `<work_dir>/checkpoint.json` and `agent_tasks.checkpoints`
- ticket context and notes: `GET /api/tickets/<ticket_id>/context`
- audit reviews: `GET /api/agents/audits?agent_id=<agent_id>&limit=20`
- memory hook audit records in the relevant `AGENT_MEMORY_SPACE`

## Local Model Smoke Agents 82 and 83

Context:

- Smoke script: `scripts/smoke_local_model_agent.py`
- Model: `qwen/qwen3.6-27b`
- Agent `82`: ticket `313`, task `80`, PID `147`
- Agent `83`: ticket `314`, task `81`, PID `239`

Observed state from active checks:

- Both recorded PIDs were no longer running in `soc-dashboard-api-1`.
- Both agents ended with dashboard status `failed`.
- Both task checkpoints stayed at the initial provisioned state:
  `step=init`, `status=queued`, `progress_pct=0`.
- The dashboard task rows showed `progress_pct=40`, but that only reflected
  stream activity and did not mean the smoke task was healthy.
- Agent `82` emitted tool-use for reading `checkpoint.json` and fetching ticket
  context, then stopped after receiving only the checkpoint read result.
- Agent `83` read `checkpoint.json`, fetched ticket context, and successfully
  wrote ticket note `280` with body `local model agent smoke note complete`.
  It then stopped before rereading/writing the final checkpoint or returning the
  required final text.
- The Claude project transcript paths reported by the hook were not present in
  the API container by the time of inspection, so `output.log`, dashboard DB
  rows, ticket notes, and memory hook records are the durable evidence.

Why this matters:

- The memory hook path worked: prompt/tool events for agents `82` and `83` were
  captured under ticket-scoped memory spaces.
- The local model/harness path remained brittle: useful work happened, but the
  runner marked the task failed because the process exited before the checkpoint
  completion contract was satisfied.
- The smoke result must be reported as failed despite the `40%` progress value
  and despite agent `83` producing a valid note.

Next fixes to investigate:

- Capture the harness process exit code and stderr separately from stdout so the
  failure note is not just a prefix of the JSON stream.
- Preserve or expose the Claude transcript path from the API container, or make
  `output.log` the canonical stream artifact.
- Bound or summarize oversized tool results before writing them into
  `agent_tasks.output` and failure notes.
- Update the runner to record the last completed tool result and checkpoint
  evidence in a structured field.
- Keep smoke validation based on process, stream, checkpoint, notes, audit, and
  memory evidence, not `progress_pct`.
