"""Ticketing connectors — pluggable, ticketing-system-agnostic."""

from .connector import TicketingConnector, NullTicketingConnector
from .itop_connector import ITOPConnector

__all__ = [
    "TicketingConnector",
    "NullTicketingConnector",
    "ITOPConnector",
    "create_connector",
]

_connector_map = {
    "itop": ITOPConnector,
    "null": NullTicketingConnector,
}


def register_connector(name: str, cls) -> None:
    """Register a new ticketing connector type (e.g., Jira, ServiceNow)."""
    _connector_map[name.lower()] = cls


def create_connector(ticketing_type: str = "itop", config: dict = None) -> TicketingConnector:
    """Factory — returns appropriate connector for the named ticketing system."""
    cls = _connector_map.get(ticketing_type.lower(), NullTicketingConnector)
    return cls(config or {})
