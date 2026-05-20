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

Smoke:

```bash
export DASHBOARD_SERVICE_TOKEN=<from approved runtime secret source>
python3 scripts/smoke_global_search.py http://localhost:25480
```

The smoke creates a local ticket and note with a unique marker, then proves the
operator can find both through global search.
