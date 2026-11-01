"""Wspólny kontrakt implementowany przez wszystkie źródła danych Cisco."""

from abc import ABC, abstractmethod

import requests


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


def init_controller_client(client, settings):
    """Przygotuj sesję kontrolera bez ujawniania danych dostępowych w logach."""
    client.base_url = settings.base_url.rstrip("/")
    client.username = settings.username
    client.password = settings.password
    client.timeout = settings.request_timeout
    client.retries = settings.request_retries
    client.session = requests.Session()
    client.session.verify = settings.ca_bundle or settings.verify_ssl
    client.session.headers.update({"Accept": "application/json"})
