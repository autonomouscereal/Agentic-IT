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
6. Setup plane smoke.
7. Phishing lifecycle smoke.
8. Agentic system smoke.
9. Local model agent smoke.
10. Setup agent smoke.
