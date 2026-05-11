# Demo Runbook

Last updated: 2026-05-11.

## Demo Goal

Show that this is not code completion and not a static playbook system. The dashboard is a control plane for agentic work:

- canonical tickets
- provider sync
- local or external models
- real agent subprocesses
- logs/checkpoints/process visibility
- approval gates
- postmortems
- reusable workflow creation

## Fast Local Demo Path

Use `qwen/qwen3.6-27b` for speed.

1. Open dashboard:

```text
http://192.168.50.222:25480
```

2. Show runner health on Agents page:

- harness
- proxy URL
- model API status
- process diagnostics

3. Create an ad hoc agent from prompt:

```text
Create a local-only ticket for a synthetic phishing report. Read the ticket context, write an internal note summarizing the scope, request approval before any remediation, and finish with a done checkpoint.
```

4. Show:

- ticket created
- agent spawned
- logs/checkpoints
- ticket note
- no active process after completion

5. Create a change request manually or through agent prompt:

- action: `block_url`
- target: synthetic URL
- risk: medium
- approve from dashboard

6. Trigger postmortem:

- open ticket
- click Postmortem
- give optional context
- show postmortem agent/task and Learning page entry

7. Trigger workflow build:

- open ticket
- click Build Workflow
- ask for phishing triage workflow
- show Workflows page draft/tested/review state

## Cloud/Faster Model Demo Path

Point `AGENT_LLM_BASE_URL` or the proxy backend at faster external/cloud model infrastructure. Keep the dashboard API and provider model the same.

Suggested longer demo:

- create a richer phishing scenario
- include fake headers/URLs as ticket note/attachment metadata
- have agent scope recipients, defang URLs, create approval request, and write a remediation plan
- then run postmortem/workflow build

## Proof Points To Narrate

- The ticket can originate from the dashboard or provider.
- The agent does not need a prebuilt playbook for every task.
- The agent has a safe fast path for ticket work.
- Workflow creation happens after or when explicitly requested.
- Risky work is approval-gated.
- Everything is logged.
- The model can run local or cloud through a proxy/harness abstraction.
- iTop is a provider, not the architecture.
- Claude Code is a harness, not the architecture.

