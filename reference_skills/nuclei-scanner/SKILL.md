---
name: nuclei-scanner
description: >
  Deploy and run ProjectDiscovery Nuclei exposure/template scans as part of the
  modular CI/CD security gate. Supports Docker image and GitLab Runner execution
  against a configured target URL.
---

# Nuclei Scanner

Run Nuclei against authorized test/staging targets or explicitly approved
production targets.

## Deploy

Reference Docker image:

```bash
docker pull projectdiscovery/nuclei:latest
```

Reference platform wrapper:

```bash
./scripts/cicd_security_tools.sh gate \
  --repo /path/to/repo \
  --target-url http://app-under-test.local \
  --output ./scan-output
```

## Command

```bash
nuclei -u "$DAST_TARGET_URL" -jsonl -o nuclei.jsonl
```

## Agent Rules

- Keep template updates controlled by the deployment owner.
- Treat high/critical findings as deployment blockers.
- Create tickets for confirmed exposure findings.
- Do not scan networks outside the approved target scope.
