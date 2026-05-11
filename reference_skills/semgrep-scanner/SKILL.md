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

## Agent Rules

- Treat high/critical findings as a failed security gate.
- Create a ticket for findings that need remediation.
- Request change approval before production deployment.
- Do not store Semgrep App tokens in source; use provider variables if a paid or
  authenticated ruleset is ever enabled.
