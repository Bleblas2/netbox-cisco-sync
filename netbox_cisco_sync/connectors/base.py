"""Wspólny kontrakt implementowany przez wszystkie źródła danych Cisco."""

from abc import ABC, abstractmethod


class ConnectorError(RuntimeError):
    """Kontrolowany błąd źródła, który można bezpiecznie pokazać w NetBox."""


class BaseConnector(ABC):
    """Minimalny kontrakt używany przez Discovery i usługi synchronizacji."""

    source_type = ""

    @abstractmethod
    def connect(self):
        """Uwierzytelnij połączenie i zwróć gotowy connector."""

    @abstractmethod
    def collect_inventory(self):
        """Zwróć lekkie, znormalizowane rekordy urządzeń do Discovery."""

    @abstractmethod
    def collect_device(self, inventory_device):
        """Uzupełnij jeden rekord inventory o szczegółowe dane źródłowe."""
