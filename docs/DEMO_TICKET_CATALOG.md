# Demo Ticket Catalog

Last updated: 2026-05-21.

Use the dashboard at `https://192.168.50.222:25443`. On the Tickets page, choose
the `Demo Proofs` filter to show the curated prepared examples in the order
below. Open each ticket and use the `Evidence Trail` section for the human
story. Start with `Sequence of Events`: it is chronological and shows notes,
agent work, model-turn starts, approval gates, access requests, postmortems,
and resolution in the order an operator would explain them. Use the raw notes
and `Full Audit Trail` only when you need lower-level proof.

The demo account password is still stored only in vault key `demo_account_1`.

## Newer Existing Golden Examples

These are already-created Ops Chat/intake proofs from the 2026-05-21 test pass.
They are tagged first in `Demo Proofs` so you can open with intake, then pivot
into the deeper agentic remediation examples below. They were not regenerated
for this curation pass.

| Story | Dashboard Ticket | Provider | Evidence |
| --- | --- | --- | --- |
| Same chat room creates a procurement ticket, then the user cancels it when scope changes | `1384` | iTop `803` | requester `Demo User`, affected user `Alice`, cancellation note says Alice is allergic to watermelon, ticket status changed by `ops-chat-agent` |
| Replacement request from the same chat becomes a distinct new ticket instead of mutating the cancelled ticket | `1385` | iTop `804` | requester `Demo User`, affected user `Alice`, routed to Procurement & Vendor Management with a separate Ops Chat message hash |
| Urgent account-access request from the same chat becomes a separate P1 identity ticket, then receives clarification that the issue is Keycloak SSO/MFA | `1386` | iTop `805` | requester/affected user `Demo User`, owning group Identity & Access, user-response note records the Keycloak SSO/MFA clarification |
| DevSecOps intake from chat for a delivery gate blocked by Semgrep/Trivy findings | `1309` | iTop `728` | owning group DevSecOps, P2, requester follow-up says urgent but no production change is approved yet |
| Requester/affected-user metadata correction without opening duplicate work | `1282` | iTop `701` | requester `Demo Account 1 Demo`, affected user `Alice Example`, synced to iTop, clean software-install intake proof |
| Scope change/reassignment proof for a software install request | `1176` | iTop `595` | assignment moved from Endpoint Support to Tier 2 Endpoint Support, assignee `endpoint.tier2.demo`, priority P3 to P2 |

Use these newer tickets for the intake story. Use the mature examples below for
the heavier “agent did the work, hit gates, learned from it” story.

## Mature Prepared Examples

| Story | Dashboard Ticket | Provider | Evidence |
| --- | --- | --- | --- |
| Fresh URL-safe phishing plus EDR hybrid with requester response, note steering, access/containment gates, postmortem, and provider-status recovery | `695` | iTop `475` | agents `273`/`274`, gates `185`/`186` completed, postmortem `107`, URL sandbox evidence, iTop sync verified resolved after compact-close adapter fix |
| URL-safe complex phishing plus EDR with user response, dashboard/iTop steering, Wazuh access gate, containment gate, postmortem, and workflow update | `690` | iTop `470` | agents `265`/`266`/`267`, gates `181`/`182` completed by `demo_account_1`, access request `31`, URL sandbox attachment `92`, postmortem `106` promoted, workflow `4` updated |
| Complex phishing plus EDR with user response, permission wall, access approval, containment gate, and promoted learning | `531` | iTop `308` | 37 notes, agents `194`/`195`/`196`, gates `155` and `156` completed, postmortem `82` promoted |
| GitLab Runner CI/CD remediation with real failed pipeline, agent fix branch, MR, final passing pipeline, and deployment gate | `83` | iTop `349` | CI/CD runs `11` failed and `12` passed, gates `39`/`40` completed, postmortem `21` ready for review |
| Roundcube Report Phish button to Mailcow quarantine and iTop/dashboard evidence | `580` | iTop `372` | gate `168` completed, postmortem `103` ready for review, quarantine id `21a705b151642568d375c748a9ea1a6b` |
| Mailcow report-phish legacy proof with completed remediation evidence | `578` | iTop `370` | agents `226`/`227`, gate `167` completed, quarantine id `28cd6d435f7c88cd9a7b46983c62a1cb` |
| Least-privilege permission wall and resume after access approval | `525` | local | agents `190`/`191`, gate `154` completed, access ticket `527` in iTop, no credential value exposed |
| Wazuh API access request proof with continuation agent after approval | `539` | iTop `333` | agents `204`/`205`, gate `161` completed, access ticket `540` resolved |
| SIEM alert to iTop to dashboard to agent with containment verification | `422` | iTop `267` | agent `149`, gate `123` completed, postmortem `62` recorded |
| Workflow broker/reuse proof for setup integration | `558` | iTop `315` | agent `213`, promoted postmortems `100` and `101` |
| False-positive tuning for Sysmon persistence noise | `575` | iTop `367` | gates `165`/`166` completed, postmortem `102` ready for review |
| Mid-task note steering without losing the original objective | `530` | iTop `307` | 13 notes, agent `193`, dashboard/iTop steering markers |
| Awaiting user response and resume flow | `118` | local | 11 notes, agents `68`/`69`, user-response lifecycle |
| Multi-action phishing remediation gate proof | `363` | iTop `235` | gates `97`/`98`/`99` completed for URL block, mailbox quarantine, and password/session review |
| False-positive internal training URL classification | `430` | local | agent `151`, resolved internal training false-positive investigation |

## Golden Demo Order

For the polished demo, use this order in the `Demo Proofs` filter:

1. `1384`, `1385`, `1386` - opening intake proof: one chat room can create,
   cancel, replace, and separately route multiple work items without treating
   the room as one ticket forever.
2. `1309` - DevSecOps intake proof: chat-created delivery-gate ticket, iTop
   sync, urgency follow-up, and no implicit production approval.
3. `1282` - requester/affected-user proof: agent-created software-install
   ticket with clean contact metadata.
4. `1176` - reassignment proof: scope changed to Tier 2 Endpoint Support with
   priority escalation.
5. `695` - lead deep-work proof: URL-safe phishing plus EDR with requester response,
   steering, Wazuh-style access wall, containment approval, postmortem, and
   provider close recovery.
6. `690` - cleaner learning proof: same phishing/EDR pattern with promoted
   workflow evidence.
7. `83` - CI/CD proof: GitLab runner gate fails, agent remediates, MR opens,
   final pipeline passes, deployment gate completes.
8. `580` - Mailcow/Roundcube proof: Report Phish button creates ticket,
   quarantine evidence, and postmortem.
9. `525` and `539` - least-privilege proof: agents hit real permission walls,
   create access requests, and resume only after approval/scoped lease.
10. `531` - older enterprise proof that still tells the full approval/access
   story, useful if you want a second complete incident.

## Live Demo Path

1. Open Tickets and select `Demo Proofs`.
2. Start with tickets `1384`, `1385`, and `1386` for the newer intake proof:
   cancellation, replacement, urgent account access, and Keycloak SSO/MFA
   clarification from one chat workspace without duplicate ticket bloat.
3. Use ticket `1309` to show chat-created DevSecOps work synced to iTop.
4. Use ticket `1282` to show requester and affected-user metadata.
5. Use ticket `1176` to show reassignment/escalation from the ticket trail.
6. Move to ticket `695` for the newest URL-safe 621/531 hybrid proof:
   requester response, dashboard/iTop steering, safe sandbox/reputation
   handling with no direct suspicious URL fetch, Wazuh-style access wall,
   approval gates, containment, postmortem, and the recovered provider close.
7. Use ticket `690` for the cleaner promoted-workflow version of the same
   story:
   user clarification, dashboard/iTop steering, sandbox evidence with
   `direct_fetch_performed=false`, Wazuh access wall, approval gates,
   containment, postmortem, and workflow learning.
8. Use ticket `531` as the older full enterprise story: user clarification,
   access wall, approval gate, scoped lease, containment, and promoted learning.
9. Use ticket `83` to show real GitLab/CI/CD proof: failed scanner gate,
   agent remediation, MR, final passing pipeline, and deployment approval.
10. Use ticket `580` with Mailcow/Roundcube open beside it to show email
   quarantine evidence.
11. Use ticket `525` or `539` to explain least-privilege credential leases.
12. Use the ticket modal's `Full Audit Trail` button when you need raw evidence;
   otherwise `Evidence Trail -> Sequence of Events` is the best
   audience-facing view.

## Cleanup Performed

On 2026-05-18, stale smoke/proof/provider/test artifacts were archived with
`demo-curation` notes instead of deleted. Pending and approved gates left over
from those old artifacts were reconciled so the Changes page no longer shows
phantom approvals. Prepared proof tickets were preserved and, where terminal
evidence already existed, their dashboard status was reconciled to `resolved`.

On 2026-05-21, the dashboard was re-curated for the employer demo:

- `Demo Proofs` now starts with tickets `1384`, `1385`, `1386`, `1309`,
  `1282`, and `1176`, then continues into mature remediation proofs such as
  `695`, `690`, `83`, `580`, `525`, `539`, and `531`.
- The newer existing intake proofs `1384`, `1385`, `1386`, `1309`, `1282`,
  and `1176` were added ahead of the mature remediation proofs so the demo can
  open with chat/intake before moving into gates, agents, and workflow learning.
- The frontend demo filter now loads the full ticket corpus so older but
  valuable proof tickets such as `83`, `118`, and `430` are not missed.
- 660 stale smoke, setup, broad-matrix, and chat-marathon tickets were archived
  as `resolved` with `demo-curation` or `ticket-status` notes. Provider-backed
  incident/request tickets were closed in iTop when their workflow allowed it;
  Change-class tickets that rejected `ev_resolve` were dashboard-archived with
  an explicit cleanup reason.
- Stale nonterminal agents/tasks tied to archived tickets were reconciled to
  terminal states.
- Stale pending/approved gates tied to archived synthetic tickets were
  reconciled to `rejected` or `completed` with cleanup evidence.
- Final live counts: zero open tickets, zero active agents, zero open tasks,
  and zero pending/approved changes. Historical evidence remains in the audit
  trail and resolved-ticket history.

Current cleanup target state:

- No pending approval gates.
- No approved-but-not-completed gates.
- No stale waiting agents on already-resolved tickets.
- Overview shows open agent load instead of all historical failures.
- Agents page shows active/waiting work plus recent curated evidence; archived
  lab agents remain in audit but are hidden from the primary demo view.
- Prepared examples are accessible through `Demo Proofs`.
- Historical clutter is retained as closed audit history, not active work.
- Browser validation on 2026-05-19 confirmed `demo_account_1` login over
  HTTPS, `Demo Proofs` rendering the curated ticket list, the ticket modal evidence
  trail loading, and no console/page/http errors.
- A full authenticated Chrome tab sweep also passed across Overview, Tickets,
  Intake, Agents, Changes, Workflows, Postmortems, CI/CD, Learning, Tools,
  Setup, Access, and Audit with no console/page/http errors.
- Playwright validation on 2026-05-19 confirmed ticket `695` renders
  `Sequence of Events`, includes model-turn start markers, includes final
  resolution evidence, and trims duplicate audit/event rows from the main
  human narrative.

## Regression Cases Not For Lead Demo

| Ticket | Reason | Current Disposition |
| --- | --- | --- |
| `688` | Superseded proof launched by an old script default with explicit local qwen instead of the preferred Hermes/DeepSeek route. | Internal routing-regression evidence only. |
| `689` | Correctly used Hermes/DeepSeek and proved URL sandbox/user/steering steps, but external provider capacity exhausted before the fallback patch was deployed. | Use only to explain why fallback was added; ticket `690` is the successful replacement. |
| `621` | The flow exposed unsafe direct suspicious URL retrieval behavior. A phishing/EDR agent must use passive evidence, reputation/sandbox adapters, or approved isolated detonation rather than curling or browsing a potentially malicious URL. | Demoted from `Demo Proofs`; use as a guardrail regression/evidence-hardening story only after the URL safety patch is deployed and verified. |
