# Documentation Refresh - Agentic Operations

Date: 2026-05-18.

## Why This Refresh Happened

The project scope has moved beyond a SOC-only dashboard. The correct framing is
now **Agentic Operations**: a one-line installed, private enterprise operations
control plane that routes work to governed agents, brokers model access through
the AI proxy, enforces approvals and scoped access, records audit evidence, and
turns completed work into reusable workflows, skills, and knowledge.

SOC/security remains the first proof domain because it exercises the hardest
primitives: tickets, alerts, logs, identity, access, approvals, remediation,
postmortems, workflow learning, and audit evidence. It is not the product
boundary.

## Updated Documentation Areas

- Top-level README: current deployment, default Hermes harness, built-in proxy,
  memory service, installer commands, and smoke-test expectations.
- Architecture: Hermes/Claude harness boundary, built-in proxy model gateway,
  `AGENTS.md` workspace context, and provider-agnostic runtime contract.
- Deployment: current lab default harness/model, proxy requirements, rebuild
  targets, and health expectations.
- One-line installer: proxy-first default examples, Hermes onboarding, and
  setup-ticket handoff.
- Agent operations: Hermes `/v1/chat/completions` and Claude Code
  `/v1/messages` proxy evidence.
- API reference: Agentic Operations naming and canonical enterprise-work API
  framing.
- Demo runbook: Agentic Operations story first, SOC as proof domain.
- Reference skills: Agentic Operations framing, Hermes harness skill, memory
  skill language, and request intake wording.

## Naming Rules Going Forward

- Use **Agentic Operations** or **Agentic Operations control plane** for the
  product/control-plane name.
- Use **SOC/IT seed domain** when referring to the current lab proof.
- Use **Provider Modules** for tools/integrations in UI and demo language.
- Use **Request Intake** for broad user/work intake. Service desk is one intake
  category, not the whole feature.
- Use **Model Gateway** or **AI proxy** for `ai-proxy`.
- Do not rename compatibility identifiers such as `SOC_DASHBOARD_CONFIG`,
  database prefixes, historical comments, or provider payloads unless there is
  a planned migration.

## Harness Rules

- Hermes Agent is the preferred default queue harness for long-running work in
  the current lab.
- Claude Code remains a supported fallback harness.
- Harness-specific command construction stays isolated in
  `api/services/agent_harness.py`.
- Agents always use the dashboard task/checkpoint/API contract regardless of
  harness.
- Secrets stay in host auth state, vaults, or runtime environment. They do not
  belong in docs, skills, `.env.example`, `runtime/proxy_config.json`, or git.

## Documentation Review Checklist

Before future commits that change behavior, run:

```powershell
rg -n "<legacy product label regex>" README.md docs reference_skills frontend .env.example
python scripts\text_hygiene.py
python -m unittest tests.test_frontend_ui_regressions
python scripts\sync_reference_skills.py check --source-roots "C:/Users/cereal/.agents/skills"
```

Expected remaining old-name hits should be compatibility names, historical
notes, provider-specific SOC module docs, or deliberate migration evidence.
