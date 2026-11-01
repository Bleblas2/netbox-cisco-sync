"""Platform-specific data sources exposed through a common connector contract."""

from .base import BaseConnector, ConnectorError

__all__ = ("BaseConnector", "ConnectorError")
