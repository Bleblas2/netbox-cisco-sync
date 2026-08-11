"""Implementacja wspólnego kontraktu źródła dla Catalyst Center."""

from ..base import BaseConnector
from .client import CatalystCenterClient
from .collector import (
    collect_device_interfaces,
    collect_inventory,
    collect_site_memberships,
    collect_stack_members_from_equipment,
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
        # urządzeń stabilnym numerem seryjnym przed filtrowaniem Family/Role.
        sites = self.client.get_sites()
        memberships = collect_site_memberships(self.client, sites)
        return collect_inventory(
            self.client.get_devices(),
            memberships,
            self.settings.import_device_roles,
        )

    def collect_device(self, inventory_device):
        self.connect()
        detailed = getattr(self.settings, "stack_detailed", False) is True
        if detailed and (
            inventory_device.stack_members
            or "," in str(inventory_device.serial_number or "")
        ):
            try:
                equipment = self.client.get_device_chassis(inventory_device.uuid)
            except Exception:  # noqa: BLE001 - starsze CCC korzysta z danych inventory.
                equipment = []
            inventory_device.stack_members = collect_stack_members_from_equipment(
                equipment,
                fallback=inventory_device.stack_members,
            )
        return collect_device_interfaces(
            inventory_device,
            self.client.get_device_interfaces(inventory_device.uuid),
            include_l2=detailed,
        )
