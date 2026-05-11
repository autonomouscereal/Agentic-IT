"""Abstract ticket provider interface - makes the dashboard ticketing-system agnostic.

Any ticketing system (iTop, ServiceNow, Jira, etc.) can be integrated by
implementing this interface. The dashboard only knows about providers,
not specific platforms.
"""


class TicketProvider:
    """Base interface for ticket providers.

    Each provider manages its own sync cycle, ticket discovery,
    and ticket CRUD operations against the external system.
    """

    # Provider identifier (e.g., "itop", "servicenow", "jira")
    name = "generic"

    # Classes/types of tickets to sync
    ticket_classes = []

    def __init__(self, config=None):
        self.config = config or {}
        self._connected = False

    async def connect(self):
        """Initialize connection to the ticketing system."""
        raise NotImplementedError

    async def is_connected(self) -> bool:
        """Check if the provider is connected."""
        return self._connected

    async def discover_new(self) -> list:
        """Quick discovery: return list of new ticket refs since last sync.

        Should be lightweight - just detect changes, not fetch full data.
        Returns list of dicts: {"class": str, "key": str}
        """
        raise NotImplementedError

    async def sync_ticket(self, ticket_class: str, ticket_key) -> dict:
        """Sync a single ticket from the external system to local DB.

        Returns {"status": "synced", "itop_ref": str, "itop_class": str}
        or {"error": str} on failure.
        """
        raise NotImplementedError

    async def create_ticket(self, ticket_id: int, fields: dict) -> dict:
        """Create a provider-side ticket from a canonical dashboard ticket.

        Provider adapters should return a provider reference and class on
        success, or an `error` string on failure. Implementations must not
        silently claim success when required provider fields are missing.
        """
        raise NotImplementedError

    async def full_sync(self) -> dict:
        """Sync all known tickets.

        Returns {"synced": int, "errors": int, "new": int}
        """
        raise NotImplementedError

    async def get_ticket(self, ticket_id: int) -> dict:
        """Fetch full ticket details from external system."""
        raise NotImplementedError

    async def update_ticket(self, ticket_id: int, fields: dict) -> dict:
        """Push status/note changes back to the external system."""
        raise NotImplementedError

    async def close_ticket(self, ticket_id: int, notes: str) -> dict:
        """Close a ticket with resolution notes."""
        raise NotImplementedError

    async def sync_loop(self, broadcast_fn=None):
        """Run the background sync loop.

        broadcast_fn: optional callback to push real-time updates
        """
        raise NotImplementedError
