# Provider Sync Cleanup 2026-05-15

Known issue fixed: several dashboard-created demo/proof tickets bypassed the
active ticket provider by forcing `provider: local` or `sync_provider: false`.
Some tests also wrote non-provider ticket classes such as `BrokerLeaseProof`,
`WorkflowReuseSmoke...`, and generic `Change`.

Expected behavior:

- Product and demo workflows sync through the active provider when one is
  configured.
- Explicit `provider: local` is reserved for provider-adapter negative controls
  and isolated permission/RBAC tests.
- Ticket classes stay provider-compatible: `Incident`, `UserRequest`,
  `RoutineChange`, `NormalChange`, or `EmergencyChange`.
- Generic `Change` is normalized to `RoutineChange`.
- Unknown proof/smoke classes are normalized to a provider-compatible class
  before insert or provider push.

Fixes:

- `ticket_service.create_ticket()` now normalizes ticket classes before insert
  and before outbound provider create.
- Ad hoc agent tickets no longer force local-only creation.
- Setup tickets now sync to the active provider by default unless explicitly
  local.
- CI/CD security tickets use provider-compatible change/request classes and
  sync by default.
- Workflow canonicalization smoke tickets no longer bypass provider sync.

Validation:

- `tests.test_ticket_service_provider_sync` covers default provider sync,
  explicit local opt-out, and class normalization.
- Live cleanup normalized the bad proof classes and pushed the active learning
  cleanup ticket to iTop.
