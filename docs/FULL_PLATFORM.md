# Full Platform Blueprint

This project is the control plane for a modular, product-agnostic autonomous
enterprise operations platform. The current SOC/IT deployment is the seed proof:
it starts by automating security, service desk, DevSecOps, IAM, email, and
infrastructure work, but the long-term goal is a one-line installed agentic
operations layer that can replace or radically reduce the human labor of large
enterprise IT organizations.

The open-source tools in the local skills tree are reference modules, not
mandatory product choices. A customer can bring ServiceNow, Jira, Splunk,
Microsoft Defender, CrowdStrike, Proofpoint, GitLab, GitHub, Okta, Keycloak, or
any other equivalent product as long as an adapter exposes the same platform
contract.

See `docs/ENTERPRISE_OPERATIONS_VISION.md` for the north-star framing.

## Core Contract

The dashboard owns canonical enterprise work state:

- Tickets, alerts, requests, tasks, notes, attachments, related context, and
  external provider links.
- Agent tasks, prompts, checkpoints, output logs, model selection, and harness process state.
- Change requests, access requests, scoped credential leases, and approvals
  before any destructive or environment-changing action.
- Skills, knowledge articles, workflows, workflow runs, and postmortems.
- Audit and event logs for operator review, demo transparency, and future compliance mapping.

Everything else is a provider:

- Ticketing providers: local, iTop, ServiceNow, Jira, or another ITSM.
- SIEM providers: Wazuh, Splunk, Sentinel, Elastic, QRadar, or another alert source.
- EDR providers: Wazuh agent/Sysmon, Defender, CrowdStrike, SentinelOne, or another endpoint source.
- Email providers: Mailcow, Exchange, Gmail, Proofpoint, Mimecast, or another mail gateway.
- IAM providers: Keycloak, Okta, Entra ID, LDAP, or another identity source.
- CI/CD providers: GitLab, GitHub, Azure DevOps, Jenkins, or another code pipeline.
- Cloud/infrastructure providers: AWS, Azure, GCP, VMware, Proxmox, Kubernetes,
  storage, backup, monitoring, and network platforms.
- Collaboration and SaaS providers: Microsoft 365, Google Workspace, Slack,
  Teams, Matrix, Confluence, SharePoint, and customer-specific internal tools.

Provider adapters should translate product-specific API calls into the canonical dashboard objects rather than changing agent prompts, workflow records, or approval behavior.

The manifest now represents this as first-class provider contracts:

- `ticketing-provider-adapter`: ServiceNow, Jira, iTop, or local tickets.
- `siem-provider-adapter`: Splunk, Sentinel, Elastic, QRadar, Wazuh, or another SIEM.
- `edr-provider-adapter`: Defender, CrowdStrike, SentinelOne, Wazuh agent/Sysmon, or another EDR.
- `email-security-provider-adapter`: Exchange, Gmail, Proofpoint, Mimecast, Mailcow, or another mail/security gateway.
- `identity-provider-adapter`: Entra ID, Okta, LDAP, Keycloak, or another IAM source.
- `cicd-provider-adapter`: GitHub, GitLab, Azure DevOps, Jenkins, or another code pipeline.

Reference deployments fill gaps. Existing customer products satisfy the same contracts and should be marked as existing integrations in Setup.

Email is a good example of the contract boundary. Mailcow is the current reference email platform because it is open-source and deployable in a lab. Roundcube is the deployable reference browser client for mailbox demos and Report Phish submissions. The actual platform capability is email inventory, mailbox context, phishing-report intake, and optional mailbox/group provisioning. The Mailcow HTTP API shim in `docs/MAILCOW_API_SHIM.md` provides a narrow read-only compatibility surface for the reference stack, while the direct MySQL bridge remains the canonical Mailcow write path. A production environment can replace that with Exchange, Gmail, Proofpoint, Mimecast, or another adapter without changing the ticket/agent/approval model.

## Deployment Model

1. Install the enterprise operations control plane with the one-line installer.
2. Open the Setup page.
3. Pick a profile: control plane only, SOC baseline, full IT automation, or
   broader enterprise operations as those profiles mature.
4. Mark which capabilities already exist in the customer environment.
5. Leave gaps enabled so the system can deploy reference open-source modules where approved.
6. Create a setup ticket, optionally with an agent.
7. The setup agent reads the ticket, plans integrations, requests approvals for changes, runs health checks, and documents progress in the ticket.
8. Operators review completed setup, approve workflows, and then enable ticket or scheduled triggers.

## Reference Modules

The current reference modules include iTop, Wazuh, Zeek, Suricata, Mailcow, Roundcube webmail, the optional Mailcow HTTP API shim, report-phish, GitLab, Keycloak, bridge services, Sysmon/Wazuh EDR, server-manager, MemPalace, web research, and vault backup. Planned DevSecOps/intelligence modules include MISP and additional provider adapters. Semgrep, Trivy, OWASP ZAP, and Nuclei are already represented as modular CI/CD scanner skills in the current bundle.

ComfyUI, torrenting, media repair, image generation, video generation, and music generation are explicitly excluded from platform setup.

## Agent Behavior

Default ticket agents optimize for fast ticket completion. They do not automatically create workflows unless the ticket asks for workflow creation. After meaningful tickets complete, a postmortem agent can review the ticket, context, logs, approvals, mistakes, and gaps, then propose workflow, skill, test, guardrail, and documentation improvements.

Workflow-build agents operate in test-safe paths first, document all steps, run smoke tests, and stop for human review before production deployment.

In the broader product, agents are not limited to tickets. Tickets, alerts,
chat requests, scheduled jobs, CI/CD events, compliance asks, and direct operator
prompts are all work-intake surfaces. The same governed pattern applies:
understand context, use scoped tools and leases, request approval for risky
actions, write evidence, complete or wait, and feed postmortem learning back
into reusable operations.

## Guardrails

- Raw PostgreSQL only; no ORM, Pydantic application models, or SQLAlchemy.
- No plaintext secrets in source, docs, examples, or fallback values.
- Destructive actions require change requests.
- Product-specific logic belongs in adapters or skills, not core routes.
- Every deployment plan must include health checks and smoke tests.
- Every reusable workflow must include an approval policy and test evidence.
