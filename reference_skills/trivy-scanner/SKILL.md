---
name: trivy-scanner
description: >
  Deploy and run Trivy filesystem, dependency, container, and IaC scanning as
  part of the modular CI/CD security gate. Supports local CLI, Docker image,
  and GitLab Runner execution.
---

# Trivy Scanner

Use Trivy after tests and before release/deploy approval.

## Deploy

Reference Docker image:

```bash
docker pull aquasec/trivy:latest
```

Reference platform wrapper:

```bash
./scripts/cicd_security_tools.sh gate --repo /path/to/repo --output ./scan-output
```

Local CLI install should follow the deployment owner's OS package policy. The
platform wrapper avoids host installs by default.

## Commands

```bash
trivy fs --format json --output trivy.json /path/to/repo
trivy image --format json --output trivy-image.json image:tag
```

## Agent Rules

- High/critical unfixed vulnerabilities block production deployment unless a
  risk acceptance change is approved.
- Keep Trivy cache in runner-controlled storage, not the repository.
- Post normalized results to `/api/cicd/runs`.
