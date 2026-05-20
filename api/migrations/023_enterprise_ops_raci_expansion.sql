-- Enterprise operations RACI expansion for broad demo/testing coverage.
-- These are provider-agnostic routing examples, not hardcoded product limits.
-- Raw PostgreSQL only; no ORM-managed schema.

INSERT INTO service_groups (name, description, default_assignee, risk_level) VALUES
    ('Cloud Operations', 'Cloud accounts, compute, storage, cost, and managed services.', 'cloud-operator', 'medium'),
    ('Database Operations', 'Database access, performance, backup, restore, and schema support.', 'database-operator', 'medium'),
    ('Procurement & Vendor Management', 'Software/license requests, vendor review, and purchasing workflow.', 'procurement-operator', 'low'),
    ('Executive Support', 'High-priority executive operations support and briefing requests.', 'exec-support', 'medium')
ON CONFLICT (name) DO UPDATE SET
    description = EXCLUDED.description,
    default_assignee = EXCLUDED.default_assignee,
    risk_level = EXCLUDED.risk_level,
    updated_at = NOW();

INSERT INTO service_raci_rules (
    name, intent, keywords, ticket_class, priority, assignment_group,
    responsible, accountable, consulted, informed, approval_required,
    approval_action, risk_level, knowledge_tags, auto_assign_agent,
    auto_agent_prompt, enabled
) VALUES
    (
        'Web application UI bug',
        'web-ui-bug',
        '["fix this ui", "web page", "button broken", "page layout", "blank page", "frontend bug", "css issue", "dashboard page", "ui error"]',
        'Incident', 'P3', 'Business Applications',
        'Business Applications', 'Application Owner',
        '["DevSecOps", "Endpoint Support"]', '["Requester Manager"]',
        false, null, 'low', '["application", "frontend", "support"]',
        false,
        'For UI bugs, gather URL, expected behavior, actual behavior, browser, screenshots when available, and route to app owner. Do not deploy code changes without a change gate.',
        true
    ),
    (
        'External or SaaS site access issue',
        'site-access',
        '["cannot access site", "blocked website", "site xyz", "website blocked", "url blocked", "proxy block", "cannot reach website", "saas login"]',
        'UserRequest', 'P3', 'Network Operations',
        'Network Operations', 'Network Service Owner',
        '["Identity & Access", "Security Operations"]', '["Requester Manager"]',
        true, 'Approve proxy, DNS, firewall, or allowlist change before altering site access controls.',
        'medium', '["network", "proxy", "access"]',
        false,
        'For site access, determine if this is DNS/proxy/firewall, SaaS identity, or user device. Do not allowlist external sites without approval and security review.',
        true
    ),
    (
        'Desktop software update',
        'software-update',
        '["update my software", "software update", "patch my laptop", "upgrade application", "outdated app", "update chrome", "update office"]',
        'UserRequest', 'P3', 'Endpoint Support',
        'Endpoint Support', 'Endpoint Service Owner',
        '["Security Operations"]', '[]',
        false, null, 'low', '["endpoint", "patching"]',
        false,
        'For software updates, identify device, app, business deadline, and standard deployment channel. Escalate only if admin rights, license, or production endpoint policy is needed.',
        true
    ),
    (
        'New software or license request',
        'software-license-request',
        '["new software", "software license", "license request", "install figma", "install visio", "install adobe", "buy software", "approved software"]',
        'UserRequest', 'P3', 'Procurement & Vendor Management',
        'Procurement & Vendor Management', 'Procurement Owner',
        '["Endpoint Support", "Security Operations", "Compliance & Audit"]', '["Requester Manager"]',
        true, 'Approve software/license purchase or deployment before installation.',
        'medium', '["procurement", "software", "endpoint"]',
        false,
        'For software/license requests, collect business justification, user/device, license count, data sensitivity, and approval owner before deployment.',
        true
    ),
    (
        'Employee onboarding',
        'employee-onboarding',
        '["new hire", "onboard user", "employee onboarding", "start date", "provision laptop", "create accounts"]',
        'UserRequest', 'P2', 'Identity & Access',
        'Identity & Access', 'IAM Service Owner',
        '["Endpoint Support", "Email Operations", "Business Applications"]', '["Requester Manager"]',
        true, 'Approve account, mailbox, device, and application provisioning before execution.',
        'medium', '["iam", "onboarding", "endpoint"]',
        false,
        'For onboarding, collect employee name, manager, start date, role, department, location, device needs, mailbox needs, and app access template.',
        true
    ),
    (
        'Employee offboarding',
        'employee-offboarding',
        '["terminate user", "offboard user", "employee offboarding", "disable account", "departing employee", "revoke access"]',
        'UserRequest', 'P1', 'Identity & Access',
        'Identity & Access', 'IAM Service Owner',
        '["Security Operations", "Email Operations", "Endpoint Support"]', '["Compliance & Audit"]',
        true, 'Approve account disablement, session revocation, mailbox handling, and device recovery before execution.',
        'high', '["iam", "offboarding", "security"]',
        false,
        'For offboarding, verify effective time, legal/HR approval, account/session scope, mailbox delegation, device recovery, and audit retention.',
        true
    ),
    (
        'Mailbox or distribution list change',
        'mailbox-group-change',
        '["distribution list", "shared mailbox", "mailbox access", "add to mailbox", "email group", "mail alias", "mail forwarding"]',
        'UserRequest', 'P3', 'Email Operations',
        'Email Operations', 'Email Service Owner',
        '["Identity & Access", "Compliance & Audit"]', '["Requester Manager"]',
        true, 'Approve mailbox, forwarding, alias, or distribution group change before execution.',
        'medium', '["email", "mailcow", "least-privilege"]',
        false,
        'For mailbox/group changes, collect mailbox/list, requested member, permission level, owner approval, expiration/review, and forwarding/compliance impact.',
        true
    ),
    (
        'DNS change',
        'dns-change',
        '["dns change", "dns record", "cname", "a record", "mx record", "txt record", "spf", "dmarc", "dkim"]',
        'Change', 'P2', 'Network Operations',
        'Network Operations', 'Network Service Owner',
        '["Email Operations", "Security Operations"]', '["Change Advisory Board"]',
        true, 'Approve DNS record change before execution.',
        'medium', '["network", "dns", "change-management"]',
        false,
        'For DNS changes, collect zone, record, value, TTL, owner, rollback, validation, and email/security impact.',
        true
    ),
    (
        'Firewall or network policy change',
        'firewall-change',
        '["firewall rule", "open port", "network allow", "network block", "allowlist ip", "block ip", "segmentation"]',
        'Change', 'P2', 'Network Operations',
        'Network Operations', 'Network Service Owner',
        '["Security Operations", "Compliance & Audit"]', '["Change Advisory Board"]',
        true, 'Approve firewall, routing, segmentation, or network policy change before execution.',
        'high', '["network", "firewall", "change-management"]',
        false,
        'For network changes, collect source/destination/protocol/port, business justification, owner, expiry, rollback, and test plan.',
        true
    ),
    (
        'TLS certificate request',
        'certificate-request',
        '["tls certificate", "ssl certificate", "certificate expiring", "renew cert", "cert request", "https cert"]',
        'UserRequest', 'P2', 'Infrastructure Operations',
        'Infrastructure Operations', 'Infrastructure Manager',
        '["Network Operations", "Security Operations"]', '["Requester Manager"]',
        true, 'Approve certificate issuance, renewal, or deployment before execution.',
        'medium', '["infrastructure", "tls", "security"]',
        false,
        'For certificate work, collect FQDN/SANs, owner, environment, expiry, issuance path, deployment target, validation, and rollback.',
        true
    ),
    (
        'Backup or restore request',
        'backup-restore',
        '["restore backup", "backup failed", "recover file", "recover server", "restore database", "backup validation"]',
        'Incident', 'P2', 'Infrastructure Operations',
        'Infrastructure Operations', 'Infrastructure Manager',
        '["Database Operations", "Compliance & Audit"]', '["Requester Manager"]',
        true, 'Approve restore, recovery, or backup policy change before execution.',
        'high', '["backup", "restore", "resilience"]',
        false,
        'For backup/restore, collect asset, restore point, scope, owner approval, data sensitivity, validation plan, and rollback/residual-risk notes.',
        true
    ),
    (
        'Cloud resource request',
        'cloud-resource',
        '["aws", "azure", "gcp", "cloud vm", "cloud storage", "s3 bucket", "azure vm", "ec2", "cloud cost"]',
        'UserRequest', 'P3', 'Cloud Operations',
        'Cloud Operations', 'Cloud Owner',
        '["Security Operations", "Compliance & Audit"]', '["Requester Manager"]',
        true, 'Approve cloud resource creation, access, or cost-impacting change before execution.',
        'medium', '["cloud", "finops", "security"]',
        false,
        'For cloud requests, collect provider/account/subscription, resource type, region, data classification, cost owner, security controls, and expiration.',
        true
    ),
    (
        'Database access or performance issue',
        'database-ops',
        '["database access", "database slow", "sql error", "postgres", "mysql", "query timeout", "schema change", "db backup"]',
        'Incident', 'P2', 'Database Operations',
        'Database Operations', 'Database Owner',
        '["DevSecOps", "Compliance & Audit"]', '["Requester Manager"]',
        true, 'Approve database access, schema, restore, or production-impacting change before execution.',
        'high', '["database", "data", "change-management"]',
        false,
        'For database work, collect DB/service, environment, error, affected users, data classification, requested access/change, rollback, and maintenance window.',
        true
    ),
    (
        'Executive support request',
        'executive-support',
        '["ceo locked out", "executive support", "board meeting", "customer call", "vp needs", "executive laptop"]',
        'Incident', 'P1', 'Executive Support',
        'Executive Support', 'Executive Support Owner',
        '["Identity & Access", "Endpoint Support", "Network Operations"]', '["Service Desk Manager"]',
        false, null, 'medium', '["executive", "service-desk"]',
        false,
        'For executive support, triage quickly, collect minimum context, avoid unsafe bypasses, and route identity/endpoint/network sub-work to the right owner.',
        true
    ),
    (
        'Policy exception request',
        'policy-exception',
        '["policy exception", "risk acceptance", "temporary exception", "compliance exception", "control exception"]',
        'UserRequest', 'P2', 'Compliance & Audit',
        'Compliance & Audit', 'Compliance Lead',
        '["Security Operations", "Change Advisory Board"]', '["Requester Manager"]',
        true, 'Approve policy exception with owner, expiry, compensating controls, and review date.',
        'high', '["compliance", "risk", "audit"]',
        false,
        'For policy exceptions, require scope, risk, owner, expiry, compensating controls, approval authority, and evidence trail.',
        true
    ),
    (
        'Platform self-repair request',
        'platform-self-repair',
        '["fix dashboard", "agentic ops broken", "agent queue broken", "proxy route broken", "workflow broken", "setup module broken"]',
        'Incident', 'P2', 'Platform Operations',
        'Platform Operations', 'Platform Owner',
        '["DevSecOps", "Security Operations"]', '["Change Advisory Board"]',
        true, 'Approve platform source, deployment, model proxy, or workflow change before execution.',
        'high', '["platform", "self-repair", "change-management"]',
        false,
        'For platform self-repair, collect failing page/API/workflow, logs, expected behavior, safe test plan, commit/deploy plan, and rollback.',
        true
    ),
    (
        'Data export or report request',
        'data-report',
        '["export report", "dashboard report", "sla report", "metrics report", "saved hours", "audit report", "ticket report"]',
        'UserRequest', 'P3', 'Compliance & Audit',
        'Compliance & Audit', 'Compliance Lead',
        '["Business Applications", "Platform Operations"]', '[]',
        false, null, 'low', '["reporting", "audit", "metrics"]',
        false,
        'For reporting, collect audience, date range, data scope, sensitivity, required format, and whether the report may include user/ticket details.',
        true
    )
ON CONFLICT (name) DO UPDATE SET
    intent = EXCLUDED.intent,
    keywords = EXCLUDED.keywords,
    ticket_class = EXCLUDED.ticket_class,
    priority = EXCLUDED.priority,
    assignment_group = EXCLUDED.assignment_group,
    responsible = EXCLUDED.responsible,
    accountable = EXCLUDED.accountable,
    consulted = EXCLUDED.consulted,
    informed = EXCLUDED.informed,
    approval_required = EXCLUDED.approval_required,
    approval_action = EXCLUDED.approval_action,
    risk_level = EXCLUDED.risk_level,
    knowledge_tags = EXCLUDED.knowledge_tags,
    auto_assign_agent = EXCLUDED.auto_assign_agent,
    auto_agent_prompt = EXCLUDED.auto_agent_prompt,
    enabled = true,
    updated_at = NOW();

-- Refinements from broad Ops Chat matrix testing. These keep account-access
-- requests under IAM while consulting system owners, and make common demo
-- phrasings route to the intended operating silo.
INSERT INTO service_raci_rules (
    name, intent, keywords, ticket_class, priority, assignment_group,
    responsible, accountable, consulted, informed, approval_required,
    approval_action, risk_level, knowledge_tags, auto_assign_agent,
    auto_agent_prompt, enabled
) VALUES
    (
        'GitLab repository access request',
        'access-gitlab',
        '["need gitlab repository access", "gitlab repository access", "grant gitlab access", "gitlab repo access", "project gitlab access"]',
        'UserRequest', 'P3', 'Identity & Access',
        'Identity & Access', 'IAM Service Owner',
        '["DevSecOps"]', '["Requester Manager"]',
        true, 'Approve GitLab group/project access before granting permissions.',
        'medium', '["iam", "gitlab", "least-privilege"]',
        false,
        'For GitLab access, collect project path, requested role, business reason, owner approval, expiry/review date, and least-privilege scope.',
        true
    ),
    (
        'Wazuh SIEM analyst access request',
        'access-wazuh',
        '["grant wazuh analyst access", "wazuh analyst access", "wazuh siem access", "need wazuh access", "siem analyst access"]',
        'UserRequest', 'P3', 'Identity & Access',
        'Identity & Access', 'IAM Service Owner',
        '["Security Operations"]', '["Requester Manager"]',
        true, 'Approve Wazuh/SIEM role access before granting permissions.',
        'medium', '["iam", "wazuh", "siem", "least-privilege"]',
        false,
        'For Wazuh access, collect requester, investigation need, role, duration, data scope, and Security Operations approval.',
        true
    )
ON CONFLICT (name) DO UPDATE SET
    intent = EXCLUDED.intent,
    keywords = EXCLUDED.keywords,
    ticket_class = EXCLUDED.ticket_class,
    priority = EXCLUDED.priority,
    assignment_group = EXCLUDED.assignment_group,
    responsible = EXCLUDED.responsible,
    accountable = EXCLUDED.accountable,
    consulted = EXCLUDED.consulted,
    informed = EXCLUDED.informed,
    approval_required = EXCLUDED.approval_required,
    approval_action = EXCLUDED.approval_action,
    risk_level = EXCLUDED.risk_level,
    knowledge_tags = EXCLUDED.knowledge_tags,
    auto_assign_agent = EXCLUDED.auto_assign_agent,
    auto_agent_prompt = EXCLUDED.auto_agent_prompt,
    enabled = true,
    updated_at = NOW();

UPDATE service_raci_rules
SET keywords = keywords || '["ceo is locked out", "locked out of sso", "board meeting", "customer meeting executive"]'::jsonb,
    updated_at = NOW()
WHERE name = 'Executive support request';

UPDATE service_raci_rules
SET keywords = keywords || '["forgot my password", "password reset", "reset my password", "mfa is not working"]'::jsonb,
    updated_at = NOW()
WHERE intent = 'identity-help';

UPDATE service_raci_rules
SET keywords = keywords || '["set temporary mail forwarding", "mail forwarding for employee", "temporary mail forwarding", "mail forwarding request"]'::jsonb,
    updated_at = NOW()
WHERE name = 'Mailbox or distribution list change';

UPDATE service_raci_rules
SET keywords = keywords || '["wazuh edr alert", "edr alert fired", "suspicious powershell", "endpoint edr alert"]'::jsonb,
    updated_at = NOW()
WHERE intent IN ('edr-siem-alert', 'phishing');

UPDATE service_raci_rules
SET keywords = keywords || '["block this suspicious url", "url block after sandbox", "sandbox review and approval", "block url after review"]'::jsonb,
    updated_at = NOW()
WHERE intent = 'phishing';

UPDATE service_raci_rules
SET keywords = keywords || '["update segmentation", "network segmentation", "segmentation change", "cannot reach dev systems"]'::jsonb,
    updated_at = NOW()
WHERE name = 'Firewall or network policy change';

UPDATE service_raci_rules
SET keywords = keywords || '["restore a deleted", "restore deleted file", "recover deleted file", "recover finance file"]'::jsonb,
    updated_at = NOW()
WHERE name = 'Backup or restore request';

UPDATE service_raci_rules
SET keywords = keywords || '["invalid json popup", "application invalid json", "business application error", "app error popup"]'::jsonb,
    updated_at = NOW()
WHERE name = 'Web application UI bug';

UPDATE service_raci_rules
SET keywords = keywords || '["phishing workflow is broken", "workflow is broken", "broken workflow", "needs a safe fix"]'::jsonb,
    updated_at = NOW()
WHERE name = 'Platform self-repair request';
