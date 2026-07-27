"""Implementacja wspólnego kontraktu źródła dla Catalyst Center."""

from ..base import BaseConnector
from .client import CatalystCenterClient
from .collector import collect_inventory, collect_site_memberships


class CatalystCenterConnector(BaseConnector):
    source_type = "catalyst_center"

    def __init__(self, settings, *, client=None):
        self.settings = settings
        self.client = client or CatalystCenterClient(settings)
        self.connected = client is not None

    def connect(self):
        if not self.connected:
            self.client.login()
            self.connected = True
        return self

    def collect_inventory(self):
        self.connect()
        # Membership jest pobierany per Building, a następnie łączony z listą
        # urządzeń stabilnym numerem seryjnym przed filtrowaniem Family/Role.
        sites = self.client.get_sites()
        memberships = collect_site_memberships(self.client, sites)
        return collect_inventory(
            self.client.get_devices(),
            memberships,
            self.settings.import_device_roles,
        )

    def collect_device(self, inventory_device):
        # Aktualny lekki rekord CCC zawiera komplet danych wspieranych przez
        # connector. Metoda zachowuje wspólny interfejs dla wszystkich źródeł.
        return inventory_device
