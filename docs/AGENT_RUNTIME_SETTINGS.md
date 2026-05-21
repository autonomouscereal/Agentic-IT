# Agent Runtime Settings

Last updated: 2026-05-21.

The dashboard now treats agent runtime selection as platform configuration, not
an Agents-tab widget. Operators use `Settings` to choose profiles, concurrency,
timeouts, reasoning effort, fast mode, scoped route assignments, and profile
skill bundles.

## Runtime Profiles

Profiles are non-secret records stored in `agent_models.json` and editable
through `Settings`.

Default profiles:

- `codex-primary`: Codex first with `gpt-5.5`, high reasoning, 10 minute
  timeout, fast mode off. Fallback intent is Hermes external, then Hermes local.
- `local-only`: Hermes with `local/agent-default`, 60 minute timeout, no
  external provider requirement.
- `hermes-external`: Hermes with `deepseek/deepseek-v4-flash`, 10 minute
  timeout, OpenRouter/local fallbacks for lab testing.

Fast mode is off by default. When enabled for Codex, the runner forces low
reasoning for newly spawned tasks so demo turns finish faster.

## Scoped Routing

Route assignments map work scope to profiles:

- `platform_area`: examples include `ops_chat`, `ticket_resolution`,
  `platform_setup`, `workflow_rerun`, `postmortem`.
- `workflow_key`: a canonical workflow key.
- `raci_group`: examples include `Security Operations`, `Identity & Access`,
  `DevSecOps`.
- `ticket_class`: examples include `Incident`, `UserRequest`, `NormalChange`.
- `condition`: reserved for deployment-specific policy conditions.

Resolution order usually favors specific workflow/RACI scope where available,
then task area, then the active profile. The `local-only` and
`hermes-external` presets are treated as whole-platform operator modes for demos
and customer posture changes, so they override seeded scoped assignments unless
a caller explicitly requests a profile, model, or harness.

## Skill Bundles

Skills are managed from the standalone `Skills` plane instead of the Learning
tab. Operators can search, sort, view, edit, activate, deactivate, and inspect
profile assignment from that plane.

Saved runtime profiles include an optional `skills` list:

- Empty skill list: the profile inherits every enabled global/default skill.
- Selected skill list: the profile still keeps global/default skills, and the
  selected enabled skills are pinned into the spawned agent context.
- Disabled skills are not included in future agent context.

This keeps the demo-safe default of "all enabled skills are available" while
allowing teams, workflows, RACI groups, or platform areas to use named saved
agents with explicit extra or pinned skills.

## Concurrency And Timeouts

`Settings -> Max active agents` updates the runtime concurrency gate for newly
queued work. Keep the lab default at `1` for slow local models. Increase it only
when the selected route has enough model/provider capacity.

Timeout guidance:

- local/on-prem model profiles: `60` minutes
- external/cloud model profiles: `10` minutes
- chat harness HTTP windows: `3600` seconds so local agents are not cut off

## Harness Defaults

Codex is the default profile for the current demo. Hermes and Claude Code remain
supported harnesses through the same runner contract. Ops Chat follows the
active Settings profile when `OPS_CHAT_AGENT_HARNESS` and
`OPS_CHAT_AGENT_MODEL` are blank.

Environment overrides still work for targeted smoke tests:

```bash
OPS_CHAT_AGENT_HARNESS=hermes
OPS_CHAT_AGENT_MODEL=local/agent-default
```

Do not commit provider tokens, Codex OAuth state, or harness credentials. Use
runtime volumes, environment injection, or vault-backed deployment scripts.

## Validation

Local:

```bash
python -m py_compile api/services/agent_runner.py api/services/agent_harness.py api/routes/agents.py api/routes/ops_chat.py api/routes/workflows.py
node --check frontend/js/dashboard.js
node --check frontend/js/agents.js
docker compose config --quiet
```

Live:

```bash
curl -sS -H "X-Dashboard-Service-Token: $DASHBOARD_SERVICE_TOKEN" \
  http://127.0.0.1:25480/api/agents/config

curl -sS -H "X-Dashboard-Service-Token: $DASHBOARD_SERVICE_TOKEN" \
  http://127.0.0.1:25480/api/ops-chat/matrix/health
```

Expected live demo posture:

- active profile: `codex-primary`
- default harness: `codex`
- Ops Chat harness: `codex`
- default model: `gpt-5.5`
- max active agents: `1`
- default timeout: `10` minutes
