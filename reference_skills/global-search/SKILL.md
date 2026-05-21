---
name: global-search
description: >
  Configure, test, and troubleshoot the dashboard global search surface across
  tickets, notes, agents, approvals, workflows, postmortems, CI/CD runs, tools,
  and audit records with RBAC and row-level ticket scoping.
---

# Global Search

Use this skill when validating dashboard-wide search or adding searchable
record types.

Endpoint:

```bash
GET /api/search/global?q=<query>&limit=60
```

Rules:

- Search is authenticated with `search:read`.
- Ticket and ticket-note results must use the same ticket row-level access
  filters as `/api/tickets`.
- Non-ticket record families are included only when the subject has the matching
  read capability.
- Do not return credential values, raw secrets, or unbounded audit details.
- Keep queries bounded; default UI searches should not exceed 60 visible rows.
- The dashboard result modal must support client-side type filtering, status
  filtering, and newest/oldest/type/title sorting over the already scoped
  result set.
- The dashboard shell must show the global search field above every page, not
  only on tickets or audit. Results should deep-link to the native record when
  possible: ticket modal, CI/CD run modal, workflow/postmortem detail, or the
  matching page for agents, tools, approvals, and audit.
- Ops Chat proof markers should be searchable by ticket title, ticket note, and
  audit event so a demo operator can jump from the conversation marker to the
  canonical evidence trail.

Smoke:

```bash
export DASHBOARD_SERVICE_TOKEN=<from approved runtime secret source>
python3 scripts/smoke_global_search.py http://localhost:25480
```

The smoke creates a local ticket and note with a unique marker, then proves the
operator can find both through global search.

For the current Ops Chat/global-search evidence checkpoint, see
`docs/OPS_CHAT_AGENTIC_UI_TESTING_AND_DEMO_READINESS.md`.
