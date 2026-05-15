# Workflow Tests

The platform needs tests that prove the durable control-plane behavior before spending local model time. Model tests are still useful, but the core ticket, approval, workflow, postmortem, and audit objects should pass without invoking an agent.

## Setup Plane Smoke

```bash
python3 scripts/smoke_setup_platform.py http://localhost:25480
```

This verifies:

- API health.
- Setup manifest loads.
- Product-agnostic plan generation works.
- Existing products are represented as integrations instead of deployments.
- Excluded modules stay excluded.
- Setup ticket creation works.
- Installer dry-run works.

## Phishing Lifecycle Smoke

```bash
python3 scripts/smoke_phishing_workflow_lifecycle.py http://localhost:25480
```

This verifies:

- Local phishing ticket creation.
- Ticket note and attachment metadata.
- Knowledge article creation.
- Change request remains pending until approved.
- Approval and completion records.
- Workflow creation and workflow run completion.
- Postmortem creation and review.
- Unified ticket context contains changes, workflows, and postmortems.
- Audit records exist for the lifecycle.

## Workflow Review And Rerun Semantics

Workflow status and approval state are shown separately enough for an operator
to understand what can run:

- `draft`: not ready for live use.
- `ready_for_review`: assets exist and need review.
- `tested_needs_approval`: test output exists, but activation still requires
  approval.
- `active_approved`: reviewed workflow can be used for future tickets.
- `active_missing_review`: legacy or imported active workflow that should be
  reviewed before demoing as approved automation.

Workflow list/detail now includes run counters and linked ticket/test runs.
Detail also exposes **Rerun on Ticket**, which calls
`POST /api/workflows/{workflow_id}/rerun` for workflows in `tested`, `approved`,
or `active` state. The rerun creates a `workflow_runs` row and spawns an agent
with the workflow blueprint, current ticket context, and the workflow run id it
must complete.

## Workflow Key Reuse And Postmortem Promotion

Workflow identity is `workflow_key`, not `name`. Names are operator-facing
labels. Agents and postmortem promotion must reuse an existing non-superseded
workflow when the operational purpose matches, even when ticket titles,
postmortem ids, or display names differ.

Promotion behavior:

- `POST /api/workflows` derives or honors `approval_policy.workflow_key`.
- If a non-superseded workflow already exists for that key, the route updates
  and versions that workflow instead of creating a name-only duplicate.
- `POST /api/postmortems/{id}/promote` derives the workflow key from ticket
  class, summary, improvements, workflow proposal, guardrails, and tests.
- Similar postmortems update the same reusable workflow and record
  `workflow_action: updated` plus `workflow_key` in notes and audit details.
- New or changed workflows remain review-gated; create/update paths do not
  silently activate workflows.
- `POST /api/workflows/{id}/review` is the activation boundary. Approval
  demotes any active/approved sibling with the same `workflow_key` to
  `superseded` before setting the reviewed workflow active, and records
  `workflow_siblings_superseded` audit evidence.
- If an already-active workflow is edited onto a different `workflow_key`
  without an explicit status change, it is re-gated to `ready_for_review`.
- `GET /api/postmortems/{id}` resolves promoted workflow assets by promotion
  audit details first, then by `workflow_key`.

Focused local regression:

```bash
python -m unittest tests.test_workflow_postmortem_reuse tests.test_postmortem_evidence_compaction
```

Deployed smoke:

```bash
python scripts/smoke_workflow_postmortem_reuse.py http://localhost:25480
python scripts/smoke_workflow_canonicalization.py http://localhost:25480
```

The smoke creates two similar resolved phishing tickets with a unique ticket
class, promotes two approved postmortems, and verifies the second promotion
updates the first workflow id/version instead of creating a duplicate.
The canonicalization smoke additionally verifies review-gated activation,
one-active-per-key demotion, context selection for the active phishing workflow,
audit search evidence, and that synthetic evidence tickets are created with
`auto_assign=false`.

Latest live verification on 2026-05-15:

- `smoke_postmortem_promotion.py`: ticket `552`, postmortem `97`, knowledge
  article `73`, draft workflow `90`, skills `96` and `97`.
- `smoke_workflow_canonicalization.py`: workflow `91` reactivated and
  superseded `92`; tickets `553` and `554`; postmortems `98` and `99`;
  canonical phishing workflow `4`; knowledge article `55`.
- `/api/agents/active` returned `{"agents":[],"count":0}` after the smokes.

## Agentic System Smoke

```bash
python3 scripts/smoke_agentic_system.py http://localhost:25480
```

This verifies the existing canonical ticket, KB, skill, approval, postmortem, workflow, and context bundle.

## Local Model Agent Smoke

```bash
python3 scripts/smoke_local_model_agent.py http://localhost:25480 qwen/qwen3.6-27b
```

Run this only when the local model/proxy is ready. It spends GPU time and should use the faster local model unless intentionally testing queue behavior.

## Setup Agent Smoke

```bash
python3 scripts/smoke_setup_agent.py http://localhost:25480 qwen/qwen3.6-27b
```

This creates a provider-agnostic setup ticket, assigns a short local-model agent, verifies the agent can read setup context and write a setup note, then confirms no harness process remains active.

## Expected Test Order

1. Python compile.
2. JavaScript syntax check.
3. Secret/prohibited dependency sweep.
4. Installer dry-run.
5. Rebuild and health check.
6. Operational metrics smoke.
7. Setup plane smoke.
8. Workflow/postmortem reuse smoke.
9. Phishing lifecycle smoke.
10. Agentic system smoke.
11. Local model agent smoke.
12. Setup agent smoke.
