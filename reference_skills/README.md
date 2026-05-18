# Reference Skills Bundle

This directory is the portable, sanitized skill bundle used by the Agentic
Operations control plane.

The source skills still live in harness-specific locations such as
`.agents/skills` or `.claude/skills`. Use `scripts/sync_reference_skills.py`
to keep this bundle synchronized instead of manually copying folders. Hermes
and Claude Code both consume the same production-relevant skill contract.

## Stage From Harness Skills

```bash
python scripts/sync_reference_skills.py stage
```

This copies only allowlisted production skills from
`platform/skill_sync_config.json` and excludes vaults, venvs, logs, caches,
environment files, and unrelated tooling.

## Check Drift

```bash
python scripts/sync_reference_skills.py check
```

Run this before commits and after agent-driven skill edits.

## Install Bundle Into A Harness

```bash
python scripts/sync_reference_skills.py install --destination /path/to/skills
```

Use this when a clean environment should receive the portable skill bundle.

## Git Workflow

Preferred flow:

1. Edit or generate skills in the harness workspace.
2. Run the skill's own tests.
3. Run `python scripts/sync_reference_skills.py stage`.
4. Review `reference_skills/manifest.json`.
5. Run dashboard smoke tests.
6. Commit both the changed source skill and the staged reference bundle in the same change set when this repo becomes a Git source of truth.

Do not commit `.cred_key`, `.cred_vault.json`, `.env`, credentials, logs,
venvs, caches, provider tokens, Hermes auth state, Claude OAuth files, or
generated run outputs.
