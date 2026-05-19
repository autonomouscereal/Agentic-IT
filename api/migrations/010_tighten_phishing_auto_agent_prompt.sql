-- Keep phishing auto-assignment bounded enough for local-model agents.
-- Raw PostgreSQL only; no ORM-managed schema.

UPDATE service_raci_rules
SET auto_agent_prompt = 'Auto-work Security Operations phishing tickets end to end using compact evidence first. Required actions: write a triage note listing sender, recipients, URLs, clicked users, exposed credentials if any, endpoints, and provider ticket refs; never directly browse, curl, wget, screenshot, or otherwise retrieve a suspicious URL from the agent runner or production network; use passive/sandboxed evidence only, such as email headers, mail gateway logs, DNS/proxy/firewall logs, Wazuh/SIEM evidence, known-safe internal allowlists, URL/domain parsing, VirusTotal/urlscan-style provider adapters when configured, or approved isolated detonation; create approval-gated changes for URL blocking, message quarantine/search, and endpoint scan/account containment when evidence supports them; poll approvals; complete approved lab-safe actions with evidence; write a final resolution note with residual risk and postmortem/workflow recommendations. Do not browse full ticket context unless compact evidence is missing a specific fact.',
    updated_at = NOW()
WHERE name = 'Phishing report';
