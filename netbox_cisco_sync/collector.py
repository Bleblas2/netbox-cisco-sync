"""Compatibility facade for the former vManage collector location."""

from .connectors.vmanage.collector import (
    collect_details,
    collect_inventory,
    configured_device_types,
    is_edge,
    parse_device,
    parse_interface,
    parse_vrrp,
)

__all__ = (
    "collect_details",
    "collect_inventory",
    "configured_device_types",
    "is_edge",
    "parse_device",
    "parse_interface",
    "parse_vrrp",
)
