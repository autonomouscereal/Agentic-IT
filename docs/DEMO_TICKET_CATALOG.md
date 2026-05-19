# Demo Ticket Catalog

Last updated: 2026-05-19.

Use the dashboard at `http://192.168.50.222:25480`. On the Tickets page, choose
the `Demo Proofs` filter to show the curated prepared examples in the order
below. Open each ticket and use the `Evidence Trail` section for the human
story: notes, agent work, approval gates, access requests, postmortems, and
audit links.

The demo account password is still stored only in vault key `demo_account_1`.

## Best Prepared Examples

| Story | Dashboard Ticket | Provider | Evidence |
| --- | --- | --- | --- |
| Fresh Hermes complex phishing plus EDR proof with user response, dashboard/iTop steering, Wazuh access gate, containment gate, postmortem, and promoted workflow | `621` | iTop `401` | 38 notes, agents `256`/`257`/`258`, access request `29`, gates `178` and `179` completed, postmortem `105`, workflow `4` updated |
| Complex phishing plus EDR with user response, permission wall, access approval, containment gate, and promoted learning | `531` | iTop `308` | 37 notes, agents `194`/`195`/`196`, gates `155` and `156` completed, postmortem `82` promoted |
| GitLab Runner CI/CD remediation with real failed pipeline, agent fix branch, MR, final passing pipeline, and deployment gate | `83` | iTop `349` | CI/CD runs `11` failed and `12` passed, gates `39`/`40` completed, postmortem `21` ready for review |
| Local CI/CD remediation plus scanner wrapper and Sysmon/EDR infrastructure repair | `82` | iTop `350` | CI/CD runs `8`/`9` needs-review and `10` passed, gates `34`/`36`/`37`/`38` completed, postmortem `20` ready for review |
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

## Live Demo Path

1. Open Tickets and select `Demo Proofs`.
2. Start with ticket `621` for the freshest full enterprise story: user clarification,
   access wall, approval gate, scoped lease, containment, and promoted learning.
3. Use ticket `83` to show real GitLab/CI/CD proof: failed scanner gate,
   agent remediation, MR, final passing pipeline, and deployment approval.
4. Use ticket `580` with Mailcow/Roundcube open beside it to show email
   quarantine evidence.
5. Use ticket `525` or `539` to explain least-privilege credential leases.
6. Use the ticket modal's `Full Audit Trail` button when you need raw evidence;
   otherwise the `Evidence Trail` section is the best audience-facing view.

## Cleanup Performed

On 2026-05-18, stale smoke/proof/provider/test artifacts were archived with
`demo-curation` notes instead of deleted. Pending and approved gates left over
from those old artifacts were reconciled so the Changes page no longer shows
phantom approvals. Prepared proof tickets were preserved and, where terminal
evidence already existed, their dashboard status was reconciled to `resolved`.

Current cleanup target state:

- No pending approval gates.
- No approved-but-not-completed gates.
- No stale waiting agents on already-resolved tickets.
- Overview shows open agent load instead of all historical failures.
- Agents page shows active/waiting work plus recent curated evidence; archived
  lab agents remain in audit but are hidden from the primary demo view.
- Prepared examples are accessible through `Demo Proofs`.
- Historical clutter is retained as closed audit history, not active work.
