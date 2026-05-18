# Demo Runbook

Last updated: 2026-05-18.

## Demo Goal

Show that this is not code completion and not a static playbook system.
Agentic Operations is a one-line installed, local/private control plane that
turns enterprise work into governed agent work. The SOC deployment is the
first proof domain, not the product boundary.

The demo should explicitly frame SOC as the seed domain. The same primitives
apply to service desk, IAM, endpoint, network, cloud, DevOps, compliance,
maintenance, and eventually internal replacement of SaaS/tool categories.

The dashboard is a control plane for agentic work:

- canonical tickets
- provider sync
- local or external models
- real agent subprocesses
- logs/checkpoints/process visibility
- approval gates
- postmortems
- reusable workflow creation
- human-readable ticket notes and full audit drill-downs

The deeper story is:

- One install can connect to existing tools or deploy reference modules for gaps.
- Agents can work ad hoc tasks, alerts, scheduled maintenance, CI/CD events, and
  user requests.
- Agents do not inherit blanket admin power; they receive scoped leases and hit
  permission walls when outside scope.
- Risky actions are approval-gated.
- Completed work becomes reusable knowledge, workflows, tests, and skills.
- The platform can expand from SOC to the rest of enterprise operations.

## Activity Trail For Demos

Ticket details show a timeline instead of only raw event rows:

- agent assignment note
- agent started note
- agent-authored notes
- checkpoint notes
- change completion notes
- agent completion/failure notes
- audit/event rows for the same ticket

In the ticket detail modal, use **Full Audit Trail** to jump to the Audit page
filtered to that ticket. Audit rows expose quick links for ticket, agent, and
target trails when those identifiers are present. Use the Notes source filter
on the Audit page when you want the human-readable narrative without the lower
level system events.

Approval gates are also deliberately visible for the demo. When the lab
auto-approves a gate, the ticket timeline shows:

```text
Approval gate opened: change <id>
Approval gate AUTO-APPROVED: change <id>
Approval gate completed: change <id>
```

Use the gate card's **full gate audit** link to show the underlying audit fields:
`approval_gate=true`, `approval_mode=demo_auto_approval`, and
`auto_approved=true`.

Quick proof before the demo:

```bash
cd /home/cereal/SOC_TESTING/soc-dashboard
python3 scripts/smoke_local_model_agent.py http://localhost:25480 qwen/qwen3.6-27b
```

Expected ticket timeline shape:

```text
Agent assigned
Agent started
<agent-authored task note>
Agent checkpoint: <step>
Agent completed
```

## Fast Local Demo Path

Use `qwen/qwen3.6-27b` for speed.

1. Open dashboard:

```text
http://192.168.50.222:25480
```

2. Show runner health on Agents page:

- harness
- proxy URL
- model API status
- process diagnostics

Use Hermes/DeepSeek as the default long-running queue proof when available;
Claude Code/local Qwen remains a fallback route for local-only demos.

3. Create an ad hoc agent from prompt:

```text
Create a local-only ticket for a synthetic phishing report. Read the ticket context, write an internal note summarizing the scope, request approval before any remediation, and finish with a done checkpoint.
```

4. Show:

- ticket created
- agent spawned
- logs/checkpoints
- ticket note
- no active process after completion

5. Create a change request manually or through agent prompt:

- action: `block_url`
- target: synthetic URL
- risk: medium
- approve from dashboard

6. Trigger postmortem:

- open ticket
- click Postmortem
- give optional context
- show postmortem agent/task and Learning page entry
- click Promote on the postmortem
- show the generated knowledge article, draft workflow, candidate skills, ticket
  note, and full postmortem audit trail
- optionally click Promote again to show the idempotent update behavior: the
  same KB/workflow/skill assets are updated and audited instead of duplicated

7. Trigger workflow build:

- open ticket
- click Build Workflow
- ask for phishing triage workflow
- show Workflows page draft/tested/review state

## DevSecOps Agent Demo Path

This is the strongest proof that the system is more than a dashboard and more
than code completion.

```bash
cd /home/cereal/SOC_TESTING/soc-dashboard
python3 scripts/agentic_cicd_full_demo.py --base http://localhost:25480 --model qwen/qwen3.6-27b
```

Narrative beats:

1. Show a vulnerable demo app and a GitLab-default scanner gate.
2. Run Semgrep, Trivy, OWASP ZAP, and Nuclei for real.
3. Show the dashboard evidence ticket and initial failed or needs-review gate.
4. Spawn the local-model remediation agent.
5. Show the agent requesting approval before modifying source.
6. Approve the remediation change from the dashboard.
7. Show the agent patch, note, checkpoint, and logs.
8. Rerun the scanner gate and show final pass with no high/critical findings.
9. For the local-only proof, show the local branch and patch artifact as the
   PR/MR handoff. For the full proof, switch to the GitLab Runner path below
   and show the real GitLab MR and final branch pipeline.
10. Show the postmortem task that turns the run into future workflow/skill
    improvements.

Latest verified demo artifacts:

- Ticket `82`
- Initial scanner run `8`
- Remediation agent `48`, task `46`
- Remediation change `34`
- Final scanner run `10`
- Deployment gate `36`
- Patch artifact `/home/cereal/SOC_TESTING/soc-dashboard/agent_work/48/agent-remediation.patch`

## GitLab Runner Agent Demo Path

Use this path when you want the strongest live proof: GitLab creates the
project, GitLab Runner executes the scanner jobs, the dashboard records the
failed gate, the local model remediates the repository after approval, and
GitLab reruns the branch to a clean pass.

```bash
cd /home/cereal/SOC_TESTING/soc-dashboard
python3 scripts/agentic_gitlab_cicd_demo.py \
  --dashboard http://localhost:25480 \
  --gitlab http://localhost \
  --model qwen/qwen3.6-27b \
  --workspace /home/cereal/SOC_TESTING/soc-dashboard/demo_runs \
  --timeout 3000
```

The runner must be able to reach the dashboard and GitLab from inside job
containers. In the reference deployment the runner uses `network_mode =
"gitlab-net"`, mounts `/tmp/zap-wrk:/zap/wrk`, and passes
`SOC_DASHBOARD_URL=http://192.168.50.222:25480` to jobs.

## Demo Logins

Use the shared demo credential only from the local encrypted vault:

```powershell
python "C:\Users\cereal\.agents\skills\server-manager\credman.py" get demo_account_1
```

Never paste the password into docs, source, or chat transcripts.

Latest verified on 2026-05-18:

| System | URL | Login Status | Demo Notes |
| --- | --- | --- | --- |
| Agentic Operations | `http://192.168.50.222:25480` | Operational | Control plane demo does not require a platform password in the current lab. |
| iTop | `http://192.168.50.222:25432` | Verified | REST POST returns `code=0`; user has `Administrator` and `REST Services User`. |
| Wazuh Dashboard | `https://192.168.50.222:26443` | Verified | Browser/dashboard login works; native Wazuh API auth for the same user currently returns 401. |
| GitLab | `http://192.168.50.222` | Verified | Local login returns HTTP 302; Keycloak OIDC start redirects correctly. |
| Mailcow | `http://192.168.50.222:2581` | Verified | Bare root URL is routed to the admin UI and stale user-session cookies are recovered; login reaches `/admin/dashboard`; dashboard, system, mailbox, queue, and quarantine pages show no invalid JSON, SQL-column warning, or blank-page errors. `/webmail` renders Roundcube backed by real Mailcow IMAP/SMTP, and `/SOGo/so` redirects there for compatibility. Use `demo_account_1@mailcow.local` and the shared vault password. Report Phish proof: legacy demo ticket `578`/iTop `370`/quarantine `28cd6d435f7c88cd9a7b46983c62a1cb`; Roundcube proof ticket `580`/iTop `372`/quarantine `21a705b151642568d375c748a9ea1a6b` with agent `229` and access request `581`. |

For GitLab's Keycloak button, the demo workstation must resolve
`keycloak.internal` to `192.168.50.222` because the Keycloak realm advertises
that hostname. Add the hosts entry from an elevated PowerShell prompt when DNS
is not configured:

```powershell
Add-Content "$env:SystemRoot\System32\drivers\etc\hosts" "`n192.168.50.222 keycloak.internal"
```

Latest verified GitLab runner artifacts:

- GitLab project `root/agentic-cicd-demo-1778538475`, project id `15`
- Project URL `http://192.168.50.222/root/agentic-cicd-demo-1778538475`
- Ticket `83`
- Initial GitLab pipeline `9`: failed as intended after all scanner jobs ran
- Initial dashboard CI/CD run `11`: failed with seven findings
- Remediation agent `50`, task `48`
- Agent change request `39`: approved before file edits, completed afterward
- Remediation branch `agent/remediate-security-gate`
- Remediation commit `2f0984f2b074764927dd21ec024638eb020b9185`
- Merge request `!1`
- Final GitLab pipeline `10`: passed
- Final dashboard CI/CD run `12`: passed with zero findings
- Deployment change `40`: approved and completed
- Postmortem `21`: ready for review
- Full log `/home/cereal/SOC_TESTING/soc-dashboard/demo_runs/gitlab_agentic_cicd_20260511_162755.log`

Live verification:

- MR URL `http://192.168.50.222/root/agentic-cicd-demo-1778538475/-/merge_requests/1`
- Pipeline `9` on `main`: failed by design; unit tests and all scanner jobs
  succeeded, dashboard gate failed because findings existed
- Pipeline `10` on `agent/remediate-security-gate`: success; unit tests,
  Semgrep, Trivy, ZAP, Nuclei, and dashboard record all succeeded

## Cloud/Faster Model Demo Path

Point `AGENT_LLM_BASE_URL` or the proxy backend at faster external/cloud model infrastructure. Keep the dashboard API and provider model the same.

Suggested longer demo:

- create a richer phishing scenario
- include fake headers/URLs as ticket note/attachment metadata
- have agent scope recipients, defang URLs, create approval request, and write a remediation plan
- then run postmortem/workflow build

## Proof Points To Narrate

- The ticket can originate from the dashboard or provider.
- The agent does not need a prebuilt playbook for every task.
- The agent has a safe fast path for ticket work.
- Workflow creation happens after or when explicitly requested.
- Risky work is approval-gated.
- Everything is logged.
- The model can run local or cloud through a proxy/harness abstraction.
- iTop is a provider, not the architecture.
- Claude Code is a harness, not the architecture.
- SOC is the first proof area, not the final product boundary.
- The long-term product is an agentic enterprise operations layer that can
  replace broad IT/security/DevOps/service-desk labor through governed agents.
