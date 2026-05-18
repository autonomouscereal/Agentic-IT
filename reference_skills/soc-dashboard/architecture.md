# Agentic Operations - Architecture & Deployment Blueprint

This reference skill note summarizes the current control-plane shape for
agents. The full source-of-truth architecture is `docs/ARCHITECTURE.md`.

## Runtime Shape

- Dashboard/API: FastAPI service on port `25480` in the reference lab.
- Database: PostgreSQL 16 only, accessed through raw parameterized SQL.
- Model gateway: built-in `ai-proxy` on port `4001`.
- Agent harnesses: Hermes Agent by default, Claude Code as a fallback.
- Memory: PostgreSQL/pgvector `agent-memory-db`.
- Frontend: vanilla HTML/CSS/JS mounted into the API container.
- Reference providers: iTop, Wazuh, Mailcow, GitLab, Keycloak, Zeek,
  Suricata, SearXNG, and CI/CD scanner skills.

## Canonical Contract

The dashboard owns the canonical records for:

- tickets, requests, alerts, changes, and operational tasks
- notes, attachment metadata, provider links, and context bundles
- agents, task prompts, checkpoints, logs, process state, and model choice
- approval gates, access requests, scoped credential leases, and evidence
- workflows, workflow runs, postmortems, skills, knowledge, and tests
- audit logs, event logs, tool health, setup plans, and runtime metrics

External tools are providers. They can be customer-owned tools or reference
modules deployed by setup. Provider logic belongs in adapters, modules, or
skills, not in the core control-plane contract.

## Agent Flow

1. Work enters through tickets, request intake, alerts, CI/CD, setup, or a
   direct operator prompt.
2. The API creates an `agents` row and an `agent_tasks` row.
3. The runner creates an isolated work directory under `AGENT_WORK_BASE`.
4. The runner writes `AGENTS.md`, `.claude/CLAUDE.md`, settings, checkpoint,
   and output log files.
5. `api/services/agent_harness.py` builds the selected harness command and
   environment.
6. Hermes uses `/v1/chat/completions`; Claude Code uses `/v1/messages`.
7. The agent writes notes, checkpoints, approval requests, and final evidence
   through the dashboard API.
8. Completion, failure, wait gates, and process cleanup are recorded in
   PostgreSQL and surfaced through the dashboard.

## Guardrails

- No ORM, Pydantic application models, SQLAlchemy, SQLite, or Chroma in the
  primary platform path.
- No hardcoded secrets or tokens in docs, skills, source, examples, or runtime
  configs committed to git.
- Risky actions require approval gates.
- Agents must use scoped leases for provider credentials.
- Do not judge agent status from progress percent alone; inspect process state,
  output logs, checkpoints, ticket notes, audit records, and proxy activity.
