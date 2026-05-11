# Skill Sync And Git Workflow

The platform skills are active deployment code. They should not be treated as one-time copies. The dashboard uses a portable `reference_skills/` bundle so agents can read and use the same production-relevant skills regardless of the current harness.

## Source Of Truth

Short term:

- Harness skills in `.agents/skills` and `.claude/skills` are where active agents may edit and test.
- `reference_skills/` is the sanitized bundle mounted into the dashboard container.
- `reference_skills/manifest.json` records checksums for drift detection.

Long term:

- Put the platform repo and production skills under Git.
- Make changes in branches.
- Run skill tests and dashboard smoke tests.
- Commit source skill changes and staged reference bundle changes together.
- Use PR/MR approvals for production-impacting skill or workflow changes.

## Commands

Stage allowlisted skills into the bundle:

```bash
python scripts/sync_reference_skills.py stage
```

Check whether harness skills and bundled skills differ:

```bash
python scripts/sync_reference_skills.py check
```

Install bundled skills into a clean harness:

```bash
python scripts/sync_reference_skills.py install --destination /path/to/skills
```

Use explicit roots when needed:

```bash
python scripts/sync_reference_skills.py stage --source-roots "/opt/platform/skills:/home/user/.claude/skills"
```

On Windows, separate roots with `;` instead of `:`.

## Exclusions

The sync config excludes:

- Credential vault files.
- `.env` files and credential JSON.
- Python virtual environments.
- Node modules.
- Logs, caches, and temporary output.
- Key/certificate files.

The allowlist excludes unrelated ComfyUI, torrenting, media repair, image, video, and music tooling.

## Dashboard Mounts

The API container mounts:

- `./reference_skills:/app/skills:ro`
- `${CLAUDE_SKILLS_DIR:-/home/cereal/.claude/skills}:/root/.claude/skills:ro`
- `${AGENTS_SKILLS_DIR:-/home/cereal/.agents/skills}:/root/.agents/skills:ro`

This lets setup inventory show both the portable bundle and live harness skills without granting the dashboard write access to the harness directories.

## Agent-Driven Skill Changes

When an agent creates or updates a skill:

1. It must do that work in a tracked ticket or workflow-build task.
2. It must write notes describing changed files, test results, and rollback notes.
3. It must not deploy production-impacting behavior without approval.
4. It must run `sync_reference_skills.py stage` after tests.
5. It must create or update docs in the source skill and the platform docs when behavior changes.
