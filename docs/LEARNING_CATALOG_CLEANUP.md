# Learning Catalog Cleanup

The dashboard Learning tab should show the operational skill catalog agents need
to run and maintain the platform. Generated smoke and one-off postmortem skills
are retained as history, but should be disabled so they do not dominate the
agent-facing catalog.

## Cleanup Contract

Run:

```bash
python scripts/cleanup_learning_catalog.py --base http://localhost:25480 --apply
```

The script only uses dashboard APIs. It does not connect directly to
PostgreSQL, does not read secrets, and does not write credential values. It is
safe to rerun: canonical workflows that are already active, reviewed, and
matching the desired definition are reported as unchanged instead of being
re-reviewed.

It performs four actions:

1. Disables generated `smoke-skill-*`, `postmortem-*`, and `smoke` category
   skills.
2. Upserts every `reference_skills/*/SKILL.md` entry into `/api/skills`.
3. Marks reference skills enabled and globally available so ticket agents can
   see deployment, bridge, CI/CD, IAM, memory, proxy, SIEM, and service desk
   capabilities.
4. Keeps only canonical operational workflow families active and supersedes
   legacy active smoke/proof/null-key workflows.

## Canonical Active Workflow Families

- `incident:phishing`
- `incident:edr-sysmon`
- `incident:false-positive-tuning`
- `userrequest:service-intake`
- `userrequest:access-request`
- `change:cicd-security`
- `change:setup-integration`
- `change:platform-self-repair`
- `change:provider-bridge-maintenance`

These are intentionally broad operational families. Postmortems should update
the matching canonical workflow instead of creating a new active workflow for
each ticket, marker, smoke run, or proof.

## UI Behavior

The Learning tab now renders operational enabled skills first, then places
generated enabled skills and disabled legacy/test skills behind expandable
sections. This keeps the demo surface readable while preserving historical
evidence.
