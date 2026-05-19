---
name: semgrep-scanner
description: >
  Deploy and run Semgrep SAST as part of the modular CI/CD security gate.
  Supports local CLI, Docker image, and GitLab Runner execution through the
  dashboard CI/CD security pipeline contract.
---

# Semgrep Scanner

Use Semgrep after unit tests and before merge/deploy approval.

## Deploy

Reference Docker image:

```bash
docker pull semgrep/semgrep:latest
```

Reference platform wrapper:

```bash
./scripts/cicd_security_tools.sh gate --repo /path/to/repo --output ./scan-output
```

Local CLI option:

```bash
python -m pip install semgrep
semgrep --config auto --json --output semgrep.json /path/to/repo
```

## GitLab

Use `semgrep/semgrep:latest` in the `security` stage. Preserve `semgrep.json`
as an artifact and post the canonical dashboard run to `/api/cicd/runs`.

GitLab artifact URLs may require provider credentials in the browser. The
dashboard must still be able to show Semgrep findings from the stored canonical
run record through `/api/cicd/runs/{run_id}/reports/semgrep`. Use that internal,
auth-protected dashboard report for demos, tickets, and agent remediation
context; keep external artifacts as optional engineering references.

## Agent Rules

- Treat high/critical findings as a failed security gate.
- Create a ticket for findings that need remediation.
- Request change approval before production deployment.
- Do not store Semgrep App tokens in source; use provider variables if a paid or
  authenticated ruleset is ever enabled.
- When documenting a Semgrep finding, cite the dashboard report/finding details
  first. Do not require the operator to open a private GitLab artifact to read
  the rule id, path, line, severity, or remediation note.
