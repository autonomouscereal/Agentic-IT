# Agent Decision Model

Last updated: 2026-05-21.

## Doctrine

Agentic Operations is agent-first. The platform should give agents rich context,
tools, memory, provider links, policies, and evidence surfaces, then let the
agent decide how to work.

The product is not a brittle classifier wrapped around a model. It is a governed
operating layer where agents can reason across tickets, chat, approvals,
providers, files, tools, and prior work.

## Boundary

Agents own decisions such as:

- answer directly, ask a clarifying question, create a ticket, or continue an
  existing ticket;
- choose the likely ticket class, priority, affected user, assignment group, and
  whether a room contains one work item or several unrelated work items;
- decide whether an old ticket is still relevant, stale, reusable, or unrelated;
- decide when to write requester-facing progress updates or closure notes;
- decide what evidence, tools, skills, and provider context are needed;
- recommend next actions, remediations, and workflow improvements.

The platform owns enforcement such as:

- authentication, RBAC, ticket visibility, and data classification barriers;
- credential-vault leases and provider permissions;
- approval gates for risky or environment-changing work;
- provider API failures, permission denials, and scoped access requests;
- suspicious URL blocking and unsafe file/prompt-injection guardrails;
- audit/event logging, immutable evidence, retry/idempotency, and queue safety.

The short rule:

> Let the agent choose the path. Make the real system enforce the walls.

## What Not To Build

Do not replace the agent with custom parser logic that decides business intent,
ownership, ticket reuse, workflow choice, or user communication unless it is a
small safety/recovery guard.

Avoid:

- hard terminal-ticket blocks that prevent an agent from continuing old work
  when the user clearly wants that;
- brittle keyword routers that decide ticket class or assignment before the
  agent has reasoned over the full message and room history;
- app-side JSON/function-call shims that bypass the harness decision loop;
- automatic assumptions that one chat room equals one ticket;
- automatic assumptions that every message after a ticket is a ticket update;
- generic closure/status messages that hide the actual agent's explanation.

If the app adds a guard, it must be narrow, explainable, and testable. Prefer
guardrails that stop unsafe action at the boundary over guardrails that remove
agent decision-making upstream.

## Acceptable Guardrails

Strong guardrails are still mandatory. They should be real barriers:

- A ticket agent can request access, but cannot grant access to itself.
- A ticket agent can request a change, but cannot approve risky work.
- A chat agent can route work, but cannot bypass provider sync or audit.
- A model can propose a suspicious URL action, but direct retrieval is blocked
  unless an approved sandbox workflow exists.
- A model can read uploaded files as untrusted input, but secrets and prompt
  injection must be handled as hostile content.
- A model can publish a demo static site only through an approved platform
  adapter or approved external deployment path.

Recovery guards are allowed when the harness fails to call the final tool, when
duplicate retry suppression is needed, or when a message would otherwise be
silently lost. These guards should preserve the agent's decision where possible
and document any fallback behavior in notes/audit.

## Ops Chat Interpretation

Ops Chat is a conversation, not a ticket container.

One Matrix room may contain:

- harmless chat;
- current-information answers;
- one-off developer artifacts;
- several independent tickets;
- cancellations or replacements;
- user replies to waiting tickets;
- scope changes, reassignment, or escalation.

The chat agent must decide per message. The platform passes recent room tickets,
ticket titles, statuses, provider refs, and recency to the agent as context.
The app should not hard-force old/new decisions. If an agent chooses poorly,
document the issue, improve prompts/context/skills, and let the next agent make
a better decision.

## Design Review Checklist

Before merging changes that touch intake, chat, assignment, approvals, or agent
execution, ask:

- Does this give the agent better context, or does it replace the agent's
  decision?
- Is this a real security/permission/change barrier, or just keyword routing?
- If the agent needs to do something risky, will it hit an auditable gate?
- If the agent needs access, will it request a scoped lease or access ticket?
- Can the agent recover, ask a user, reassign, or open a new ticket without
  fighting the application?
- Will the requester see the agent's actual result, not a generic status blob?
- Is the fallback documented as a fallback rather than the primary operating
  model?

If the change constrains agent autonomy, it must have a concrete safety reason
and a regression test proving the boundary.
