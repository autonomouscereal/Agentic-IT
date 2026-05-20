-- Specific RACI routes for account/system access requests.
-- Raw PostgreSQL only; no ORM-managed schema.

INSERT INTO service_groups (name, description, default_assignee, risk_level) VALUES
    ('Platform Operations', 'Agentic Operations dashboard, model proxy, workflow, audit, and platform administration.', 'platform-operator', 'high')
ON CONFLICT (name) DO UPDATE SET
    description = EXCLUDED.description,
    default_assignee = EXCLUDED.default_assignee,
    risk_level = EXCLUDED.risk_level,
    updated_at = NOW();

INSERT INTO service_raci_rules (
    name, intent, keywords, ticket_class, priority, assignment_group,
    responsible, accountable, consulted, informed, approval_required,
    approval_action, risk_level, knowledge_tags, auto_assign_agent, auto_agent_prompt
) VALUES
    (
        'Mailcow mailbox access',
        'access-mailcow',
        '["mailcow", "mailbox", "webmail", "roundcube", "quarantine", "shared mailbox", "distribution group", "mail flow", "smtp", "imap"]',
        'UserRequest',
        'P3',
        'Email Operations',
        'Email Operations',
        'Email Service Owner',
        '["Identity & Access", "Compliance & Audit"]',
        '["Requester Manager"]',
        true,
        'Approve least-privilege mailbox, quarantine, webmail, or mail-flow access before any email-platform entitlement is changed.',
        'medium',
        '["access", "mailcow", "email", "least-privilege"]',
        false,
        'For Mailcow access requests, verify mailbox/domain scope, owner approval, expiration, and whether read-only evidence access is enough. Never expose mailbox passwords in notes.'
    ),
    (
        'Wazuh SIEM access',
        'access-wazuh',
        '["wazuh", "siem", "edr", "sysmon", "alert index", "rule", "security event", "manager api"]',
        'UserRequest',
        'P3',
        'Security Operations',
        'Security Operations',
        'Security Operations Manager',
        '["Identity & Access", "Compliance & Audit"]',
        '["Requester Manager"]',
        true,
        'Approve scoped SIEM or EDR evidence access before granting alert, rule, or manager API visibility.',
        'medium',
        '["access", "wazuh", "siem", "edr", "least-privilege"]',
        false,
        'For Wazuh/SIEM access, grant only the required rule, alert index, endpoint, or read API scope and record audit evidence.'
    ),
    (
        'GitLab repository access',
        'access-gitlab',
        '["gitlab", "repository", "repo", "project", "merge request", "branch", "pipeline", "runner", "group/project"]',
        'UserRequest',
        'P3',
        'DevSecOps',
        'DevSecOps',
        'Repository Owner',
        '["Identity & Access", "Compliance & Audit"]',
        '["Requester Manager"]',
        true,
        'Approve least-privilege repository or pipeline access before adding project, group, runner, or deployment permissions.',
        'medium',
        '["access", "gitlab", "repository", "devsecops", "least-privilege"]',
        false,
        'For GitLab access, prefer project-scoped reporter/developer access with an expiration and owner approval.'
    ),
    (
        'Keycloak identity administration access',
        'access-keycloak',
        '["keycloak", "identity provider", "realm", "oidc", "sso", "mfa reset", "password reset", "account unlock", "role mapping", "group membership"]',
        'UserRequest',
        'P2',
        'Identity & Access',
        'Identity & Access',
        'IAM Service Owner',
        '["Security Operations", "Compliance & Audit"]',
        '["Requester Manager"]',
        true,
        'Approve scoped identity administration access before changing users, groups, roles, MFA, or OIDC clients.',
        'high',
        '["access", "keycloak", "iam", "sso", "least-privilege"]',
        false,
        'For Keycloak/IAM access, verify requester authority, affected realm/client/group, audit scope, and rollback plan before granting.'
    ),
    (
        'iTop ITSM access',
        'access-itop',
        '["itop", "itsm", "ticketing", "cmdb", "service catalog", "incident queue", "change queue", "team membership"]',
        'UserRequest',
        'P3',
        'Business Applications',
        'Business Applications',
        'ITSM Platform Owner',
        '["Identity & Access", "Compliance & Audit"]',
        '["Requester Manager"]',
        true,
        'Approve scoped ITSM/CMDB access before changing ticket queues, profiles, teams, or service catalog ownership.',
        'medium',
        '["access", "itop", "itsm", "cmdb", "least-privilege"]',
        false,
        'For iTop access, grant only the profile/team needed for the ticket class or CMDB object family and record owner approval.'
    ),
    (
        'Agentic platform administration access',
        'access-agentic-platform',
        '["dashboard", "agentic operations", "agentic ops", "ai proxy", "model proxy", "workflow admin", "raci admin", "audit trail", "agent queue", "setup module"]',
        'UserRequest',
        'P2',
        'Platform Operations',
        'Platform Operations',
        'Platform Owner',
        '["Identity & Access", "Security Operations", "Compliance & Audit"]',
        '["Change Advisory Board"]',
        true,
        'Approve platform administration access before granting dashboard, workflow, proxy, RACI, setup, or audit administration permissions.',
        'high',
        '["access", "agentic-operations", "platform", "least-privilege"]',
        false,
        'For platform admin access, verify role inheritance, maximum data classification, agent permission boundaries, and audit logging.'
    ),
    (
        'Network control access',
        'access-network',
        '["firewall", "dns", "vpn", "proxy", "waf", "routing", "segmentation", "network device", "switch", "router"]',
        'UserRequest',
        'P2',
        'Network Operations',
        'Network Operations',
        'Network Service Owner',
        '["Security Operations", "Compliance & Audit"]',
        '["Change Advisory Board"]',
        true,
        'Approve scoped network-control access before changing routing, firewall, DNS, VPN, proxy, WAF, or segmentation permissions.',
        'high',
        '["access", "network", "change-management", "least-privilege"]',
        false,
        'For network access, require exact device/scope, implementation window, rollback, and change-control evidence.'
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
    auto_agent_model = COALESCE(service_raci_rules.auto_agent_model, EXCLUDED.auto_agent_model),
    auto_agent_prompt = EXCLUDED.auto_agent_prompt,
    enabled = true,
    updated_at = NOW();

UPDATE service_raci_rules
SET keywords = (
        SELECT jsonb_agg(DISTINCT value)
        FROM jsonb_array_elements_text(
            keywords || '["cannot log", "can''t log", "cant log", "login issue", "sign in", "sign-in", "unable to login", "account locked", "account unlock"]'::jsonb
        ) AS items(value)
    ),
    updated_at = NOW()
WHERE name = 'Account locked or MFA help';
