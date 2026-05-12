---
name: owasp-zap-scanner
description: >
  Deploy and run OWASP ZAP baseline DAST scans for web applications in the
  modular CI/CD security gate. Supports Docker image and GitLab Runner execution
  against a configured DAST target URL.
---

# OWASP ZAP Scanner

Run ZAP only when the application has a reachable test/staging URL. Do not scan
production targets unless the ticket/change explicitly authorizes it.

## Deploy

Reference Docker image:

```bash
docker pull ghcr.io/zaproxy/zaproxy:stable
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
zap-baseline.py -t "$DAST_TARGET_URL" -J zap.json
```

## Agent Rules

- Use test/staging URLs by default.
- Store `zap.json` as evidence.
- High findings block production deployment pending remediation or approved risk
  acceptance.
- Never embed application credentials in ZAP command lines or artifacts.
