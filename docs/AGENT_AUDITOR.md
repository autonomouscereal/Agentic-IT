# Agent Auditor

The agent auditor is a background supervision loop that watches agent tasks for
progress, approval blocks, failures, and stuck runs. It records every finding in
PostgreSQL before taking any recovery action.

## Behavior

- Polls recent active and failed agent tasks.
- Records `agent_progress_ok` periodically for active work.
- Records `agent_waiting_on_approval` and does not restart agents blocked on a
  pending change request.
- Records `agent_no_progress` when checkpoints stop advancing beyond the
  configured threshold.
- Records `agent_task_failed` for failed tasks.
- Can spawn a replacement agent for failed/stuck tasks when auto recovery is
  enabled and the agent is not blocked on approval.
- Runner heartbeats are based on real stream output or checkpoint updates, not
  a synthetic timer.
- Running tasks are marked failed/orphaned if the recorded Claude/Node process
  no longer exists in the API container after a restart or rebuild.

## Configuration

Environment variables:

- `AGENT_AUDIT_INTERVAL`, default `60`.
- `AGENT_AUDIT_NO_PROGRESS_MINUTES`, default `30`.
- `AGENT_AUDIT_MAX_RECOVERY_ATTEMPTS`, default `2`.
- `AGENT_AUDITOR_AUTO_RECOVER`, default `false`.

Recovery actions are limited to replacement agent spawns and are disabled by
default so demos and production environments do not accidentally duplicate old
work. Enable auto recovery only after cleanup policies and max attempts are
confirmed. Environment-changing work still requires normal dashboard change
approval.

## API

- `GET /api/agents/audits`
- `POST /api/agents/audits/run`

## Test

```bash
python3 scripts/smoke_agent_auditor.py http://localhost:25480
```
