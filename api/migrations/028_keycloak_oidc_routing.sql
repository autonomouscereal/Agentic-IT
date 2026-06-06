-- Keep Keycloak/OIDC client management under IAM ownership even when the
-- affected application is an Ops Chat or platform component.
INSERT INTO service_raci_rules (
    name, intent, keywords, ticket_class, priority, assignment_group,
    responsible, accountable, consulted, informed, approval_required,
    approval_action, risk_level, knowledge_tags, auto_assign_agent,
    auto_agent_prompt, enabled
) VALUES (
    'Keycloak OIDC client management',
    'keycloak-oidc-client',
    '["keycloak oidc client", "oidc client redirect", "client redirect uri", "openid connect client", "identity provider redirect", "realm client", "sso client redirect", "ops chat keycloak"]',
    'UserRequest', 'P3', 'Identity & Access',
    'Identity & Access', 'IAM Service Owner',
    '["Platform Operations", "Compliance & Audit"]', '["Requester Manager"]',
    true, 'Approve identity-provider client, redirect URI, scope, or role-mapping changes before applying them.',
    'medium', '["iam", "keycloak", "oidc", "sso", "least-privilege"]',
    false,
    'For Keycloak/OIDC client work, collect client id, application owner, requested redirect URI or scope change, environment, risk notes, and approval before changing identity-provider configuration.',
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
