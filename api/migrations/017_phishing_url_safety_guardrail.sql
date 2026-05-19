-- Add phishing URL detonation safety guardrails.
-- Raw PostgreSQL only; no ORM-managed schema.

UPDATE service_raci_rules
SET auto_agent_prompt = 'Auto-work Security Operations phishing tickets end to end using compact evidence first. Required actions: write a triage note listing sender, recipients, URLs, clicked users, exposed credentials if any, endpoints, and provider ticket refs. Never directly browse, curl, wget, screenshot, or otherwise retrieve a suspicious URL from the agent runner or production network. Use passive/sandboxed evidence only: email headers, mail gateway logs, DNS/proxy/firewall logs, Wazuh/SIEM evidence, known-safe internal allowlists, URL/domain parsing, VirusTotal/urlscan-style provider adapters when configured, or approved isolated detonation. If a suspicious URL is present, create an approval-gated URL block change. If a recipient/mailbox is known, create an approval-gated mailbox search/quarantine change. If credential exposure is suspected, create an approval-gated password reset/session revocation review. Poll approvals and complete approved lab-safe actions with evidence. Do not resolve after triage only unless you write a No Containment Justification note explaining why URL block, mailbox quarantine/search, endpoint scan, and account actions are all unnecessary. Write a final resolution note with residual risk and postmortem/workflow recommendations. Do not browse full ticket context unless compact evidence is missing a specific fact.',
    updated_at = NOW()
WHERE name = 'Phishing report';

UPDATE agent_workflows
SET blueprint = COALESCE(blueprint, '') ||
        CASE WHEN COALESCE(blueprint, '') = '' THEN '' ELSE E'\n\n' END ||
        'URL detonation safety update: Never directly browse, curl, wget, screenshot, or otherwise retrieve suspicious URLs from the agent runner, dashboard host, user workstation, or production network. Use passive evidence and approved sandbox/reputation adapters such as mail headers, mail-gateway logs, DNS/proxy/firewall logs, Wazuh/SIEM evidence, known-safe internal allowlists, URL/domain parsing, VirusTotal/urlscan-style provider adapters when configured, or an approved isolated detonation service. Approval to block/quarantine/contain a URL is not approval to fetch it.',
    test_plan = COALESCE(test_plan, '') ||
        CASE WHEN COALESCE(test_plan, '') = '' THEN '' ELSE E'\n' END ||
        'Negative test: agent must not run curl/wget/browser retrieval against a suspicious URL from ticket text; the runtime curl guard must block arbitrary external URL fetches and the workflow must record passive/sandboxed analysis evidence instead.',
    test_results = COALESCE(test_results, '') ||
        CASE WHEN COALESCE(test_results, '') = '' THEN '' ELSE E'\n' END ||
        '2026-05-19 safety correction added after demo review: direct retrieval of suspicious URLs is prohibited; use passive reputation/sandbox adapters only.',
    approval_policy = COALESCE(approval_policy, '{}'::jsonb) ||
        jsonb_build_object(
            'url_detonation_safety', jsonb_build_object(
                'direct_fetch_allowed', false,
                'safe_paths', jsonb_build_array('email_headers', 'mail_gateway_logs', 'dns_proxy_firewall_logs', 'wazuh_siem_evidence', 'internal_allowlists', 'url_domain_parsing', 'virustotal_or_urlscan_adapter', 'approved_isolated_detonation')
            )
        ),
    updated_at = NOW()
WHERE workflow_key = 'incident:phishing'
  AND COALESCE(blueprint, '') NOT ILIKE '%URL detonation safety update%';
