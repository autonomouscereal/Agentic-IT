# UI self-repair fixes - 2026-05-13

## Known issues documented

These were reported as small dashboard defects and handled in a separate UI lane
to avoid overlapping the concurrent workflow-canonicalization work:

- Audit page filters could be repopulated by stale `audit_q`,
  `audit_source`, or `audit_level` URL parameters after a drill-down link.
- Ticket descriptions imported from providers could show raw paragraph markup
  such as `<p>` and `</p>` in the ticket detail modal.
- Agent cards showed an `Idle` timer, which made inactive queued/dashboard
  agents look like they were wasting compute.
- Agent cards and agent detail modals showed ticket titles but did not provide a
  direct ticket drill-down link.

## Fixes

- Audit URL filters are now consumed once for deep links and immediately removed
  from the browser URL, so normal page refreshes return to an unfiltered audit
  view unless the operator intentionally enters a filter.
- Ticket descriptions are converted to safe plain text before rendering. Common
  block tags become line breaks, HTML tags are removed, and entities are decoded
  before the result is escaped into the DOM.
- Agent cards now link directly to their current ticket and retain runtime,
  working-time, and gated-time fields while removing the idle timer.
- Agent detail modals now include a clickable ticket link.

## Self-repair agent pattern

For system/dashboard defects, create a normal local ticket and spawn an agent
with a bounded task. The agent should:

1. Read the ticket context and existing notes.
2. Create a change request before modifying dashboard code, deployment scripts,
   or live configuration.
3. Wait for approval.
4. Apply the smallest scoped patch in an isolated workspace.
5. Run focused tests and attach the evidence as ticket notes.
6. Mark the change complete and finish with `checkpoint.json` at `done` /
   `100%`.

Operators should review the agent's patch before syncing it to a customer
deployment. Customer-specific fixes should be represented as reviewed patches,
skills, workflows, or setup overlays so they can be re-applied after upgrades
instead of becoming invisible drift.

## Live self-repair validation attempt

Ticket `433` (`CODEX_UI_SELF_REPAIR_20260513`) was created on 2026-05-13 to
exercise the approval-gated self-repair path against these UI fixes.

Result:

- Agent `152`, task `149`, started in `/app/agent_work/152` and failed after
  emitting only the Claude Code init event.
- Agent `153`, task `150`, was spawned through the dashboard Restart path and
  failed the same way.
- No approval gate was created by either agent, and no agent-authored
  diagnostic note was written beyond control-plane assignment/start notes.
- The auditor recorded `agent_task_failed` for agent `152` with recommended
  action `spawn_replacement_agent`; after one controlled retry, the same
  failure repeated.
- Runner health reported credentials present and the model API reachable, so
  the failure appears to be a harness/model execution issue after Claude Code
  startup rather than an API availability issue.

Known issue:

- Self-repair/local-model ticket agents can exit immediately after the init
  event without producing tool output or an approval gate. The task tracker
  correctly marks the task failed, but the runner currently lacks enough stderr
  or exit-code detail in the surfaced ticket evidence to explain why the model
  stopped. Add richer process-exit telemetry before relying on autonomous
  dashboard self-repair demos.

Important coordination note:

- While investigating this failure, an unrelated active agent `154` appeared on
  ticket `434`. It was not stopped, restarted, or otherwise managed from this
  UI lane.
