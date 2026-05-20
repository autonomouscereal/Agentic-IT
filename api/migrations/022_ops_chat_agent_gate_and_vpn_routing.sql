-- Ops Chat real-agent polish:
-- - chat-created approval gates are bound to the spawned agent in code so
--   approval can resume the waiting agent.
-- - VPN connectivity reports route to Network Operations instead of generic
--   access/entitlement handling when the issue is a broken tunnel.
-- Raw PostgreSQL only; no ORM-managed schema.

INSERT INTO service_raci_rules (
    name, intent, keywords, ticket_class, priority, assignment_group,
    responsible, accountable, consulted, informed, approval_required,
    approval_action, risk_level, knowledge_tags, auto_assign_agent,
    auto_agent_prompt, enabled
) VALUES (
    'VPN connectivity issue',
    'vpn-connectivity',
    '["vpn stopped connecting", "vpn connectivity", "vpn issue", "vpn tunnel", "vpn client", "cannot connect vpn", "finance file share via vpn", "file share via vpn", "vpn after reboot"]',
    'Incident',
    'P3',
    'Network Operations',
    'Network Operations',
    'Network Service Owner',
    '["Endpoint Support", "Identity & Access"]',
    '["Requester Manager"]',
    false,
    null,
    'medium',
    '["network", "vpn", "service-desk"]',
    false,
    'For VPN connectivity reports, first determine whether this is a broken VPN tunnel or a separate entitlement request. Do not make firewall, route, DNS, or VPN server changes without a change approval gate. If finance/share access was previously working, keep the work routed as a Network Operations connectivity issue rather than IAM.',
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
