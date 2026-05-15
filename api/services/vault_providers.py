"""Credential vault provider metadata.

The dashboard brokers scoped credential leases, but it must not become a
secret-return API. This module centralizes the configurable vault-provider
metadata so deployments can plug in server-manager, HashiCorp Vault, cloud
secret managers, or a customer resolver while the agent-facing contract stays
the same: return references and audit decisions, never secret values.
"""

import os


def provider_name():
    return os.getenv("CREDENTIAL_VAULT_PROVIDER", "server-manager").strip() or "server-manager"


def resolver_mode():
    return os.getenv("CREDENTIAL_VAULT_RESOLVER_MODE", "reference-only").strip() or "reference-only"


def broker_metadata(system=None, broker_mode="lease-reference"):
    return {
        "vault_provider": provider_name(),
        "resolver_mode": resolver_mode(),
        "system": system,
        "broker_mode": broker_mode,
        "secret_values_returned": False,
        "credential_value_returned": False,
        "credential_boundary": (
            "The dashboard returns scoped vault references and audited provider "
            "results. Secret values stay in the configured vault provider."
        ),
    }
