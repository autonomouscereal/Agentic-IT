"""Infer scoped credential lease requests from access-request metadata."""
import re


def _permission_action(permission):
    text = (permission or "").strip().lower()
    if any(word in text for word in ("write", "edit", "modify", "admin", "manage", "contain", "disable")):
        return "write"
    return "read"


def _clean_resource_id(value):
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text or "*"


def infer_lease_request(resource, permission=None, account_ref=None):
    """Return a best-effort lease request for known provider access wording.

    Agents should still submit an explicit lease_request when they can. This
    inference is a safety net so an approved access request does not produce an
    empty lease set just because the local model described the resource in
    human language.
    """
    resource_text = _clean_resource_id(resource)
    lower = resource_text.lower()
    action = _permission_action(permission)

    if "wazuh" in lower or "siem" in lower:
        if "alert index" in lower:
            match = re.search(r"alert\s+index\s+([A-Za-z0-9_.:/@-]+)", resource_text, re.IGNORECASE)
            return {
                "system": "wazuh",
                "resource_type": "alert_index",
                "resource_id": match.group(1) if match else "*",
                "action": action,
            }
        if "api" in lower or "manager" in lower:
            return {
                "system": "wazuh",
                "resource_type": "api",
                "resource_id": "wazuh.manager",
                "action": action,
            }

    if "gitlab" in lower:
        match = re.search(r"(?:project|repo(?:sitory)?)\s+([A-Za-z0-9_.:/@-]+)", resource_text, re.IGNORECASE)
        return {
            "system": "gitlab",
            "resource_type": "project",
            "resource_id": match.group(1) if match else "*",
            "action": action,
        }

    if "mailcow" in lower or "mailbox" in lower or "email" in lower:
        return {
            "system": "mailcow",
            "resource_type": "mailbox" if "mailbox" in lower else "api",
            "resource_id": account_ref or "*",
            "action": action,
        }

    if "itop" in lower or "ticket" in lower:
        return {
            "system": "itop",
            "resource_type": "ticket",
            "resource_id": account_ref or "*",
            "action": action,
        }

    return None
