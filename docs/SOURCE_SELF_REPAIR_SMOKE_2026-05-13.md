# Source Self-Repair Smoke - 2026-05-13

## Purpose

Prove that a dashboard-spawned local-model agent can diagnose and edit source code
from scratch inside an isolated workspace, behind an approval gate, instead of
only following an operator-provided patch.

## Run Summary

Marker: `CODEX_SOURCE_SELF_REPAIR_HARDENED_1778694733`

Primary proof:

- Dashboard ticket: `442`
- Agent: `159`
- Task: `156`
- Approval gate: change `128`
- Evidence note: `770`
- Isolated repo: `/app/agent_work/159/source-repo`

The agent:

1. Read ticket context and identified itself as agent `159`.
2. Ran the failing unit test from the absolute source path.
3. Diagnosed the missing `scripts/agentic_self_repair_marker.py` utility.
4. Created change request `128` before editing source.
5. Waited until the operator approved the gate.
6. Created the missing script without an operator-provided patch.
7. Ran `py_compile` and `python3 -m unittest tests.test_agentic_self_repair_marker`.
8. Completed change `128`.
9. Wrote evidence note `770` with changed file, tests, residual risk, and patch
   location.

## First Attempt Failure

Ticket `441` / agent `158` proved two harness/prompt defects before the hardened
retry:

- Host-side seeding failed until the agent workdir ownership was repaired.
- The agent correctly diagnosed the missing file, but ran verification from
  `/app/agent_work/158` instead of the isolated `source-repo` path twice.

The retry prompt fixed this by requiring every source command to use:

```bash
cd /app/agent_work/<agent_id>/source-repo && <command>
```

## Issues Found And Fixed

The hardened run exposed that the API/agent container allowed `Bash(git *)` but
did not include the `git` binary. The agent's compile and unit tests passed, but
`git diff` failed with exit `127`.

Fix:

- Add `git` to `api/Dockerfile`.
- Add regression coverage that asserts the agent runtime image installs `git`.
- Update the SOC dashboard skill so future source-repair prompts require both
  `git status --short` and diff evidence, and explain the fallback if the
  environment is not a real git checkout.

Host verification also showed Python bytecode writes can fail in root-owned
agent workspaces. Verification commands for copied agent workspaces should set
`PYTHONDONTWRITEBYTECODE=1` or repair ownership for the current swim lane only.

## Productized Artifacts

The agent-created utility was reconciled into the product tree as a reusable,
low-risk smoke target:

- `scripts/agentic_self_repair_marker.py`
- `tests/test_agentic_self_repair_marker.py`

The product test uses an environment-independent marker,
`CODEX_SOURCE_SELF_REPAIR_UNIT`, so it remains useful outside this specific run.

## Operator Notes

Do not stop a slow local-model source-repair agent based on elapsed wall-clock
time alone. For this run, several steps took multiple minutes after successful
tool calls. Judge state from:

- `/api/agents/active`
- `/api/agents/processes`
- `agent_work/<id>/output.log`
- ticket notes
- change request state
- checkpoint state

If the model completes a source edit and note but stalls before a final
checkpoint, treat that as a completion bookkeeping defect, not as failure of the
source-edit capability.
