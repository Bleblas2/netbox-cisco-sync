"""Implementacja wspólnego kontraktu źródła dla Meraki."""

from ..base import BaseConnector
from .client import MerakiClient
from .collector import collect_device_details, parse_inventory_device


class MerakiConnector(BaseConnector):
    source_type = "meraki"

    def __init__(self, settings, *, client=None):
        self.settings = settings
        self.client = client or MerakiClient(settings)
        self.connected = client is not None

    def connect(self):
        if not self.connected:
            self.client.connect()
            self.connected = True
        return self

    def collect_inventory(self):
        self.connect()
        allowed_orgs = {
            value.strip() for value in self.settings.organization_ids.split(",") if value.strip()
        }
        allowed_families = {
            value.strip().casefold()
            for value in self.settings.import_device_families.split(",") if value.strip()
        }
        devices = []
        for organization in self.client.get_organizations():
            org_id = str(organization.get("id") or "")
            if allowed_orgs and org_id not in allowed_orgs:
                continue
            for network in self.client.get_networks(org_id):
                for raw in self.client.get_devices(network.get("id")):
                    row = parse_inventory_device(raw, network)
                    if not allowed_families or row.source_family.casefold() in allowed_families:
                        devices.append(row)
        return devices

    def collect_device(self, inventory_device):
        self.connect()
        return collect_device_details(inventory_device, self.client)
