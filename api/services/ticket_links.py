"""External ticket URL helpers."""

import os
from urllib.parse import urlencode


ITOP_WEB_BASE = os.getenv("ITOP_WEB_BASE", f"http://{os.getenv('ITOP_HOST', 'localhost')}:{os.getenv('ITOP_PORT', '25432')}")


def external_ticket_url(ticket):
    """Return a best-effort link to the source ticketing system."""
    if not ticket:
        return None
    if ticket.get("provider_url"):
        return ticket["provider_url"]
    if ticket.get("provider") and ticket.get("provider") != "itop":
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
