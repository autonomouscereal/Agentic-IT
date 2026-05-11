"""External ticket URL helpers."""

import os
from urllib.parse import urlencode


ITOP_WEB_BASE = os.getenv("ITOP_WEB_BASE", f"http://{os.getenv('ITOP_HOST', 'localhost')}:{os.getenv('ITOP_PORT', '25432')}")
SERVICENOW_INSTANCE_URL = (os.getenv("SERVICENOW_INSTANCE_URL") or "").rstrip("/")
JIRA_BASE_URL = (os.getenv("JIRA_BASE_URL") or "").rstrip("/")


def external_ticket_url(ticket):
    """Return a best-effort link to the source ticketing system."""
    if not ticket:
        return None
    if ticket.get("provider_url"):
        return ticket["provider_url"]
    provider = ticket.get("provider")
    provider_ref = ticket.get("provider_ref")
    provider_class = ticket.get("provider_class")

    if provider == "servicenow" and SERVICENOW_INSTANCE_URL and provider_ref:
        table = provider_class or "incident"
        return f"{SERVICENOW_INSTANCE_URL}/nav_to.do?uri={table}_list.do?sysparm_query=number={provider_ref}"
    if provider == "jira" and JIRA_BASE_URL and provider_ref:
        return f"{JIRA_BASE_URL}/browse/{provider_ref}"

    if provider and provider != "itop":
        return None

    ticket_class = ticket.get("itop_class")
    ticket_ref = ticket.get("itop_ref")
    if not ticket_class or not ticket_ref:
        return None

    if str(ticket_ref).startswith("LOCAL-"):
        return None

    query = urlencode({
        "operation": "details",
        "class": ticket_class,
        "id": ticket_ref,
    })
    return f"{ITOP_WEB_BASE.rstrip('/')}/pages/UI.php?{query}"
