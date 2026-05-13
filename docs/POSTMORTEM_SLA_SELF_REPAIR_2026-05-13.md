# Postmortem SLA Self-Repair

Date: 2026-05-13

## Issue

The Overview operational metrics tracked ticket SLA compliance, but did not
separately track whether resolved tickets received a postmortem inside the
learning/review SLA window. That hid missing or late postmortems after tickets
were marked resolved.

## Fix

- Added `postmortem_sla` to `GET /api/dashboard/ops-metrics`.
- The metric counts resolved tickets from the last 30 days, joins the first
  postmortem per ticket, and reports:
  - `tickets_requiring_postmortem`
  - `tickets_with_postmortem`
  - `within_sla`
  - `missing_postmortem`
  - `breached_sla`
  - `at_risk`
  - `avg_postmortem_latency_seconds`
  - `compliance_pct`
  - `target_hours`
- The dashboard Overview SLA card now shows missing postmortems in the subtitle.
- The SLA / Tool Snapshot table now includes a `Postmortems` row.
- The operational metrics smoke test now asserts the postmortem SLA contract.
- The SOC dashboard skill now documents `postmortem_sla` as part of the
  operational metrics contract.

## Validation

Local deterministic checks:

```powershell
python -m py_compile api/routes/dashboard.py
node --check frontend/js/dashboard.js
python -m unittest tests.test_ops_metrics_postmortem_sla tests.test_task_tracker_provider_close tests.test_frontend_ui_regressions
```

Live deployed checks on the AI server:

```bash
python3 -m py_compile api/routes/dashboard.py
python3 -m unittest tests.test_ops_metrics_postmortem_sla tests.test_task_tracker_provider_close
node --check frontend/js/dashboard.js
python3 scripts/smoke_operational_metrics.py http://127.0.0.1:25480
```

The live smoke returned `postmortem_sla.required=79`,
`postmortem_sla.within_sla=23`, `postmortem_sla.missing=56`, and
`postmortem_sla.compliance_pct=29.1`.

## Agentic Proof

Ticket `440` / agent `157` was spawned as
`CODEX_POSTMORTEM_SLA_SELF_REPAIR_20260513` to validate the deployed dashboard
self-repair through the normal control plane. The agent is required to create a
low-risk approval gate before accepting the self-repair, verify the live metrics
and frontend strings after approval, complete the gate with evidence, write a
final ticket note, and checkpoint `done` at 100%.

Final evidence:

- Agent `157`, task `154`, model `qwen/qwen3.6-27b`.
- Approval gate `126` was requested by the agent, approved by
  `codex-postmortem-sla-approver`, then completed by the agent.
- Final evidence note `755` was written to ticket `440`.
- Ticket `440` resolved and agent `157` finished at
  `2026-05-13T16:46:28Z`.
- Final checkpoint:
  `{"step": "complete", "status": "done", "progress_pct": 100}`.
- Agent-verified values:
  `tickets_requiring_postmortem=79`, `tickets_with_postmortem=23`,
  `within_sla=23`, `missing_postmortem=56`, `breached_sla=8`, `at_risk=5`,
  `compliance_pct=29.1`, `target_hours=24`.
- After ticket `440` resolved, the live smoke denominator increased as expected:
  `tickets_requiring_postmortem=80`, `missing_postmortem=57`,
  `compliance_pct=28.8`.

Harness lesson:

- The agent initially hit the shell guard with inline JSON / multiline shell
  payloads, then self-corrected by writing JSON files and using
  `curl -d @payload.json`.
- The reusable prompts now document that payload pattern so future agents avoid
  the same failure mode.
