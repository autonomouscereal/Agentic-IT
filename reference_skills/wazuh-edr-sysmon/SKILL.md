---
name: wazuh-edr-sysmon
description: >
  Wazuh EDR and Sysmon deployment blueprint for Windows and Linux endpoints.
  Includes Sysmon configs, Wazuh agent templates, endpoint deployment scripts,
  custom Wazuh decoders/rules, active response scripts, and E2E tests. Use when
  deploying endpoint telemetry, validating Sysmon event flow, or testing
  approval-gated EDR response workflows.
allowed-tools:
  - Read
  - Bash(python *)
  - Bash(sh *)
  - Bash(find *)
  - Bash(cat *)
---

# Wazuh EDR Sysmon

This skill packages endpoint telemetry and response assets for the modular SOC platform.

## Important Guardrails

- Do not deploy agents, restart services, edit endpoint configs, quarantine hosts, or enable active response without an approved change request.
- Treat `configs/`, `wazuh_configs/`, and `scripts/` as reference deployment assets that must be adapted to the customer environment.
- Store credentials in the platform vault or environment; never write credentials into `.env.example`, templates, or scripts.
- Run tests in a lab or explicitly approved test environment before production rollout.

## Layout

- `configs/`: Sysmon and Wazuh agent configuration templates.
- `scripts/`: endpoint deployment, status, and test helpers.
- `tests/`: Python E2E test coverage for the EDR/Sysmon flow.
- `wazuh_configs/`: Wazuh decoders, rules, and active response scripts.

## Recommended Workflow

1. Read the assigned ticket and identify the target OS, Wazuh manager, network path, and approval policy.
2. Create or confirm a change request before touching endpoints or manager rules.
3. Stage configs in a test environment first.
4. Run `scripts/edr-status.sh` and `bash scripts/test-edr-e2e.sh` where available.
5. Document event IDs, Wazuh rule IDs, endpoint coverage, gaps, rollback steps, and test results in the ticket.
6. After completion, run a postmortem if the deployment created reusable process improvements.

## Test Entry Points

```bash
bash scripts/test-edr-e2e.sh
python tests/test_edr_sysmon_e2e.py
```

Use the dashboard approval workflow for any active response or endpoint-changing test.
