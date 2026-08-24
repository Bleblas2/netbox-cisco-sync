"""Implementacja wspólnego kontraktu źródła dla Catalyst Center."""

from ..base import BaseConnector
from .client import CatalystCenterClient
from .collector import (
    collect_device_interfaces,
    collect_inventory,
    collect_site_device_assignments,
    collect_site_memberships,
    is_stack_device,
    merge_stack_details,
)


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
        # urządzeń po deviceId. Starsze CCC używają fallbacku po serialu.
        sites = self.client.get_sites()
        site_device_assignments = collect_site_device_assignments(
            self.client,
            sites,
        )
        memberships = (
            collect_site_memberships(self.client, sites)
            if site_device_assignments is None
            else {}
        )
        devices = self.client.get_devices()
        enriched_devices = []
        for raw in devices:
            if is_stack_device(raw):
                raw = merge_stack_details(
                    raw,
                    self.client.get_device_stack(raw.get("id")),
                )
            enriched_devices.append(raw)
        return collect_inventory(
            enriched_devices,
            memberships,
            self.settings.import_device_roles,
            site_device_assignments=site_device_assignments,
        )

    def collect_device(self, inventory_device):
        self.connect()
        return collect_device_interfaces(
            inventory_device,
            self.client.get_device_interfaces(inventory_device.uuid),
        )
