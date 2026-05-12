"""SIEM connectors — pluggable, fault-tolerant, SIEM-agnostic."""

from .connector import SIEMConnector, NullConnector
from .wazuh_connector import WazuhConnector

__all__ = [
    "SIEMConnector",
    "NullConnector",
    "WazuhConnector",
    "create_connector",
]

_connector_map = {
    "wazuh": WazuhConnector,
    "null": NullConnector,
}


def register_connector(name: str, cls) -> None:
    """Register a new SIEM connector type (e.g., Splunk, ELK)."""
    _connector_map[name.lower()] = cls


def create_connector(siem_type: str = "wazuh", config: dict = None) -> SIEMConnector:
    """Factory — returns appropriate connector for the named SIEM."""
    cls = _connector_map.get(siem_type.lower(), NullConnector)
    return cls(config or {})
