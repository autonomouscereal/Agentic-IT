# Module Registry

`platform/manifest.json` is the setup source of truth. It lets the dashboard build product-agnostic deployment plans from capabilities rather than hardcoding one stack.

## Status Values

- `implemented`: usable now through dashboard code or an existing skill.
- `blueprint`: planned or partially documented module that can be tracked as setup work.
- `planned`: future module that should appear in roadmaps and workflow tickets.
- `optional`: supported only when a customer explicitly asks for it.

## Deployment Strategies

- `dashboard`: provided by the control plane itself.
- `compose`: deployed with this repository.
- `skill`: deployed or managed through a skill under `.agents/skills` or `.claude/skills`.
- `planned`: not yet a first-class deployer.
- `external`: customer-owned or optional integration.

## Provider-Agnostic Rule

Every module should describe the capability it provides, not just the product name. For example, Mailcow is the reference email platform, but the real capability is email intake, mailbox context, and phishing-report handling. A customer mail security provider should be able to replace Mailcow by implementing that capability through an adapter.

Provider-contract modules are intentionally separate from reference products. Mark a provider contract as existing when the customer already has a product for that capability, then either exclude the matching reference module or leave it as a test/sandbox deployment.

## Mailcow Reference Email Module

The Mailcow module is a reference implementation of the email-provider capability. It can be deployed when an environment has no email system or when the platform needs an open-source sandbox for demos and tests.

Important boundaries:

- Direct MySQL through the Keycloak-Mailcow bridge remains the canonical Mailcow write/provisioning path in the reference deployment.
- The optional Mailcow HTTP API shim is a read-only compatibility surface for domain, mailbox, and alias inventory.
- The shim should be represented as part of the Mailcow reference module, not as a required platform-wide dependency.
- If an environment already has Exchange, Gmail, Proofpoint, Mimecast, or another mail security provider, mark the email-provider capability as existing and use or build that provider adapter instead.

Reference docs:

- `docs/MAILCOW_API_SHIM.md`
- `reference_skills/keycloak-mailcow-bridge/SKILL.md`
- `reference_skills/mailcow/SKILL.md`

## Adding A Module

Add an object to `platform/manifest.json` with:

- `id`
- `name`
- `category`
- `status`
- `deployable`
- `deploy_strategy`
- `skill`
- `depends_on`
- `provides`
- `required_secrets`
- `ports`
- `health_checks`
- `test_commands`
- `notes`

Do not put credentials, customer URLs with secrets, tokens, or passwords in the manifest.

## Setup API

- `GET /api/setup/manifest`: full registry.
- `GET /api/setup/profiles`: setup profiles.
- `POST /api/setup/plan`: generates an ordered plan from profile, includes, excludes, existing tools, and deploy-missing preference.
- `POST /api/setup/ticket`: creates an auditable setup ticket and can optionally spawn a setup agent.

## Current Exclusions

ComfyUI and media tooling are explicitly excluded from platform setup. They can stay in the broader skills directory for unrelated work, but they should not appear in IT/SOC deployment plans.
