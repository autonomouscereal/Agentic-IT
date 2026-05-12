# CI/CD Security Tool Deployment

This bundle deploys the reference free/open-source scanners used by the
platform CI/CD security gate:

- Semgrep for SAST.
- Trivy for filesystem, dependency, container, and IaC scanning.
- OWASP ZAP for DAST.
- Nuclei for exposure/template-driven checks.

GitLab Runner is the default execution target in the reference platform, but
the bundle can run anywhere Docker Compose is available.

## One-Shot Gate

```bash
./scripts/cicd_security_tools.sh gate --repo /path/to/repo --output ./scan-output
```

With DAST:

```bash
./scripts/cicd_security_tools.sh gate \
  --repo /path/to/repo \
  --target-url http://app-under-test.local \
  --output ./scan-output
```

The script writes scanner-native output plus `security-gate-result.json`.

## GitLab

Use the dashboard endpoint `/api/cicd/gitlab/template` for the starter
`.gitlab-ci.yml`. Production deployment jobs should require both the GitLab
security stage and the dashboard change approval.

## Notes

- No secrets are stored in this bundle.
- Scanner images can be pinned per deployment through `.env`.
- If Docker is not allowed, install the CLIs locally and run
  `scripts/run_cicd_security_pipeline.py --execution local`.
