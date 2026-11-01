"""Implementacja wspólnego kontraktu źródła dla vManage."""

from ..base import BaseConnector
from .client import VmanageClient
from .collector import collect_details, collect_inventory


class VmanageConnector(BaseConnector):
    source_type = "vmanage"

    def __init__(self, settings, *, client=None):
        self.settings = settings
        self.client = client or VmanageClient(settings)
        self.connected = client is not None

    def connect(self):
        # Connector może dostać gotowego klienta z joba masowego. Wtedy ponowne
        # logowanie dla każdego urządzenia byłoby zbędne i obciążałoby vManage.
        if not self.connected:
            self.client.login()
            self.connected = True
        return self

    def collect_inventory(self):
        # Discovery pobiera wyłącznie lekką listę. Szczegóły portów pozostają
        # odroczone do pierwszego wejścia w urządzenie lub jawnego Refresh.
        self.connect()
        return collect_inventory(self.client.get_devices())

    def collect_device(self, inventory_device):
        self.connect()
        return collect_details(self.client, inventory_device)
