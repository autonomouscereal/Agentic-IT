# Agentic IT

Agentic IT is a private, self-hosted control plane for turning enterprise IT,
security, service desk, DevOps, IAM, and operations work into governed agent
work.

The short version: organizations are full of tickets, alerts, chats, emails,
change requests, compliance asks, failed builds, access requests, and recurring
maintenance work. Today, humans copy context between tools, investigate the same
classes of issues repeatedly, wait on approvals, write notes, and try to keep an
audit trail after the fact.

Agentic IT is built to make that operational work agent-addressable without
giving up control. It gives agents the context, tools, permissions, approvals,
and audit surface they need to do real work, while keeping humans in charge of
risk, policy, and accountability.

Core doctrine: agents own operational decisions; the platform owns real
boundaries. Do not replace the agent with brittle app-side intent parsers.
Instead, give the agent context and make authentication, RBAC, provider
permissions, credential leases, approval gates, audit, and unsafe-action
blocking enforce the walls. See [Agent Decision Model](docs/AGENT_DECISION_MODEL.md).

## What It Solves

Most AI demos stop at chat. Most enterprise automation stops at rigid playbooks.
Real operations work is messier:

- A user asks for help in chat, but the actual work belongs in a ticket.
- A SOC alert needs SIEM context, endpoint context, identity context, and a
  decision about whether remediation is safe.
- A CI/CD scan fails and someone has to understand the finding, patch code,
  prove the fix, and document what changed.
- A service desk request needs routing, user follow-up, approval, provider sync,
  and a clean evidence trail.
- A repeated incident should become a reusable workflow, test, skill, or
  knowledge article.

Agentic IT is the layer that connects those pieces. It is not just a dashboard,
not just a chatbot, and not just a SOAR script. It is a canonical work system
where agents can operate across existing tools with bounded authority.

## What It Does

- Creates a single control plane for tickets, alerts, requests, changes,
  approvals, notes, evidence, agents, tasks, postmortems, workflows, tools, and
  audit history.
- Accepts work from the dashboard, Ops Chat, provider tickets, CI/CD events,
  setup flows, and direct operator prompts.
- Runs real agent harnesses against work items, currently including Hermes
  Agent, Claude Code, and Codex CLI through a common runner contract.
- Uses a Settings plane for runtime profiles so Codex, Hermes, and Claude Code
  can be selected per platform area, workflow, RACI group, or team without
  hardcoding the Agents tab.
- Routes models through a built-in AI proxy so deployments can prefer local or
  on-prem models, while still allowing deliberate external test routes.
- Uses provider adapters so existing tools can stay in place. iTop, Wazuh,
  Mailcow, Keycloak, GitLab, Matrix/Element, and related services are reference
  modules, not permanent product boundaries.
- Requires change approvals, access requests, and scoped credential leases for
  sensitive or environment-changing actions.
- Records notes, logs, checkpoints, tool activity, provider links, agent state,
  and postmortem evidence so operators can answer what happened and why.
- Converts resolved work into reusable knowledge, workflows, skills, tests, and
  runbooks.

## Product Goal

The long-term goal is a one-line installed, local/private enterprise operations
layer that can radically reduce the human labor required to run IT, security,
service desk, IAM, DevOps, cloud, network, compliance, and internal operations.

The current SOC/IT stack is the first proof domain because it exercises the hard
parts:

- alerts and tickets,
- identity and access,
- logs and evidence,
- provider integrations,
- risky remediation,
- approval gates,
- user communication,
- postmortems and reusable workflows.

The architecture is intentionally broader than SOC. The platform should
eventually operate work from tickets, alerts, chat, email, schedules, CI/CD,
monitoring, audits, docs, and platform self-repair events.

## How It Works

```text
Work arrives
  ticket, alert, chat, email, CI/CD failure, setup request, operator prompt
        |
        v
Control plane builds context
  requester, affected user, related tickets, provider data, notes, approvals,
  tools, skills, logs, attachments, workflows, policies, model route
        |
        v
Agent is assigned
  Settings resolves a runtime profile, then Hermes, Claude Code, Codex, or
  another future harness runs through the same task and checkpoint contract
        |
        v
Agent works under guardrails
  reads context, investigates, writes notes, calls approved tools, requests
  access or change approval when needed, updates checkpoints
        |
        v
Outcome is recorded
  ticket updates, provider sync, audit events, output logs, evidence,
  postmortem, reusable workflow/skill proposals
```

The platform owns the canonical state. External products are providers. Provider
code translates between those tools and the canonical dashboard objects without
forcing the whole product to become specific to one ITSM, SIEM, IAM provider, or
agent harness.

Design rule: build guardrails as real platform barriers, not as upstream
decision cages. The agent should decide whether to answer, ask, create,
continue, reassign, escalate, or learn; the system should stop unauthorized,
unsafe, unaudited, or unapproved actions when the agent reaches those barriers.

## Current Reference Stack

The live lab deployment runs a reference environment on the AI server. These are
working modules used to prove the product shape:

- FastAPI control plane and vanilla JS dashboard.
- Raw PostgreSQL database for canonical state.
- Built-in model proxy for local/on-prem and external model routing.
- Agent memory service backed by PostgreSQL/pgvector.
- Hermes Agent, Claude Code, and Codex CLI harness support.
- iTop as the reference ITSM/CMDB provider.
- Wazuh, Zeek, and Suricata as security telemetry/reference SOC modules.
- Mailcow/Roundcube and report-phish flows for email/security operations.
- Keycloak for IAM/OIDC/SAML reference identity.
- GitLab and GitLab Runner for CI/CD security workflows.
- Matrix/Element Ops Chat for conversational work intake.
- Settings-managed runtime profiles for Codex-primary, local-only, and
  Hermes-external routes, including reasoning effort, fast mode, concurrency,
  timeouts, and fallback order.
- Semgrep, Trivy, OWASP ZAP, and Nuclei for CI/CD security gates.
- Reference skills for deployment, provider management, scans, chat, memory,
  access workflows, and dashboard operations.

These modules are replaceable. In a real customer environment, the goal is to
integrate what already exists first and deploy reference tools only where the
organization has gaps.

## Example Workflows

### Chat To Ticket To Agent

A user asks for help in Ops Chat. The chat agent decides whether the message is
ordinary conversation, a clarification, or operational work. If it is work, the
dashboard creates a traceable ticket, syncs it to the active provider, attaches
the chat context, and queues an agent.

### Phishing Report

A reported email becomes a ticket with evidence. Agents can inspect safe
metadata, coordinate with email/security providers, request approvals for risky
remediation, update the user, and preserve the audit trail.

### CI/CD Security Gate

A pipeline runs SAST, dependency, container, and DAST scans. Failed results are
normalized into dashboard-readable evidence. An agent can analyze findings,
prepare remediation, document the change, and route through review/approval.

### Access Request Or Account Recovery

The system captures requester and affected-user context, routes to the right
assignment group, checks policy, requests scoped access where needed, and records
who approved what.

### Setup And Onboarding

The setup flow creates a parent setup ticket and scoped module tickets. Agents
can deploy or integrate each module while preserving evidence, approvals, and
health status.

## Why This Is Different

- The agent is not the product. The control plane, provider contract, approvals,
  audit trail, and learning loop are the product.
- Tickets are not the boundary. They are one trigger among many.
- Existing enterprise tools are not thrown away. They become providers behind a
  canonical work model.
- Automation is aggressive but governed. Agents can do real work, but risky
  actions require approvals and scoped permissions.
- The agentic harness is trusted to reason about work. The platform should
  correct, steer, gate, audit, and recover agents, not neuter them into fixed
  parser flows.
- Every run is meant to improve the next one through postmortems, skills,
  workflows, tests, and documentation.

## Guardrails

Agentic IT is designed for high-trust environments, so guardrails are first-class
features:

- local/private first deployment model,
- raw PostgreSQL canonical state,
- no plaintext secrets in source or docs,
- scoped credential leases,
- approval gates for risky or environment-changing work,
- provider-specific permissions instead of broad global access,
- audit and event logs for operator review,
- checkpointed agent tasks and output logs,
- human-readable notes and postmortems,
- harness isolation so a model or agent runtime can be replaced.

## Quick Start

The project supports one-line style local installs and side-by-side lab
deployments. From a prepared checkout:

```bash
./install.sh --profile soc --proxy-mode deploy --harness auto --model-route local
```

Windows:

```powershell
.\install.ps1 --profile soc --proxy-mode deploy --harness auto --model-route local
```

The installer starts the control plane, PostgreSQL, model proxy, memory service,
and setup-ticket handoff. Product-specific module deployment and integration
continue from the dashboard Setup page as auditable work.

For deployment details, see:

- [One-Line Installer](docs/ONE_LINE_INSTALLER.md)
- [Deployment Runbook](docs/DEPLOYMENT.md)
- [Installer E2E Results](docs/INSTALLER_E2E_RESULTS.md)

## Current Lab Deployment

The current reference lab uses:

- Dashboard UI/API: `https://192.168.50.222:25443`
- Local service API on the AI server: `http://127.0.0.1:25480`
- Model proxy: `http://ai-proxy:4001` inside Docker and
  `http://192.168.50.222:4001` from the LAN
- Ops Chat reference client: `https://192.168.50.222:3303`
- Server path: `/home/cereal/SOC_TESTING/soc-dashboard`
- Windows working copy: `D:\IT AGENT PROJECT`

Credentials are stored in the server-manager vault or runtime environment, not
in source.

## Development Rules

These are hard project rules:

- No ORM.
- No Pydantic application models.
- No SQLAlchemy.
- PostgreSQL only for persistent application state.
- Raw parameterized SQL only.
- No plaintext passwords, API keys, tokens, or fallback secrets in source,
  examples, or docs.

The current API uses `asyncpg` and raw SQL. Keep provider-specific behavior
behind adapters, services, modules, or skills.

## Documentation Map

Start here:

- [Autonomous Enterprise Operations Vision](docs/ENTERPRISE_OPERATIONS_VISION.md)
- [Architecture](docs/ARCHITECTURE.md)
- [Full Platform Blueprint](docs/FULL_PLATFORM.md)
- [Agent Operations](docs/AGENT_OPERATIONS.md)
- [Provider Adapter Guide](docs/PROVIDER_ADAPTERS.md)
- [Security And Approvals](docs/SECURITY_APPROVALS.md)
- [Global Search And Ops Chat](docs/GLOBAL_SEARCH_AND_OPS_CHAT.md)
- [Ops Chat Deployment Blueprint](docs/OPS_CHAT_DEPLOYMENT_BLUEPRINT.md)
- [Demo Runbook](docs/DEMO_RUNBOOK.md)
- [Demo Ticket Catalog](docs/DEMO_TICKET_CATALOG.md)
- [Testing Runbook](docs/TESTING.md)
- [API Reference](docs/API.md)

Harness and model routing:

- [Hermes Harness](docs/HERMES_HARNESS.md)
- `reference_skills/codex-harness/SKILL.md`
- [Skill Sync And Git Workflow](docs/SKILL_SYNC.md)

Security/compliance:

- [FedRAMP-Style Security Hardening](docs/FEDRAMP_SECURITY_HARDENING.md)
- [FedRAMP Access Control Prep](docs/FEDRAMP_ACCESS_CONTROL_PREP.md)

## Useful Operator Commands

Health checks:

```bash
curl -sS http://localhost:25480/health
curl -sS http://localhost:25480/api/agents/runner-health
curl -sS http://localhost:25480/api/agents/processes
```

Switch model routing in the deployed server path:

```bash
python3 scripts/switch_model_route.py --route local --restart
python3 scripts/switch_model_route.py --route external --restart
```

Use `local` for customer/government demos unless you are explicitly proving
external provider fallback.

## Test Checklist

Before publishing or deploying meaningful changes:

1. Compile API modules with `python -m py_compile`.
2. Run `node --check` over frontend JavaScript.
3. Sweep for prohibited libraries and secret literals.
4. Run focused pytest coverage for touched behavior.
5. Rebuild changed API/proxy/frontend containers.
6. Check `/health`, `/api/agents/runner-health`, and `/api/agents/processes`.
7. Run the relevant smoke scripts from `scripts/`.
8. Open the dashboard and verify the affected workflow visually.

See [Testing Runbook](docs/TESTING.md) and [Workflow Tests](docs/WORKFLOW_TESTS.md)
for deeper validation.

## Status

This is an active research and product-build repository. The current stack is
already capable of running real lab workflows, but the product boundary is still
expanding: more providers, more deployment profiles, stronger RBAC, better
attachment handling, more trigger surfaces, and a cleaner postmortem-to-workflow
promotion path are ongoing work.
