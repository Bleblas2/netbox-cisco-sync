"""Implementacja wspólnego kontraktu źródła dla Catalyst Center."""

from ..base import BaseConnector
from .client import CatalystCenterClient, CatalystCenterError
from .collector import (
    collect_device_interfaces,
    collect_inventory,
    collect_site_device_assignments,
    collect_site_memberships,
    is_stack_device,
    merge_stack_details,
    merge_port_channel_members,
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
        raw_interfaces = self.client.get_device_interfaces(inventory_device.uuid)
        device = collect_device_interfaces(inventory_device, raw_interfaces)
        raw_by_name = {
            str(row.get("portName") or row.get("name") or "").strip().casefold(): row
            for row in raw_interfaces or []
        }
        for lag in device.interfaces:
            if lag.interface_type != "lag":
                continue
            interface_id = raw_by_name[lag.name.casefold()].get("id")
            if not interface_id:
                raise CatalystCenterError(f"Port channel {lag.name} has no interface ID.")
            details = self.client.get_port_channel(device.uuid, interface_id)
            merge_port_channel_members(device, lag, details)
        return device
