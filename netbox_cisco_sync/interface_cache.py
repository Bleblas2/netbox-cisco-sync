"""Relacyjny cache interfejsów wykrytych na platformach Cisco."""

from django.db import transaction
from django.utils import timezone

from .dto import CollectedInterface, device_from_dict
from .models import (
    DeviceCatalystCenterConfig,
    DeviceMerakiConfig,
    DeviceVmanageConfig,
    DiscoveredInterface,
)
from .sync.interfaces import interface_is_selected, nominal_interface_speed_mbps


def config_relation(config):
    """Zwróć nazwę relacji cache odpowiadającą typowi konfiguracji urządzenia."""
    if isinstance(config, DeviceVmanageConfig):
        return "vmanage_config"
    if isinstance(config, DeviceCatalystCenterConfig):
        return "catalyst_config"
    if isinstance(config, DeviceMerakiConfig):
        return "meraki_config"
    raise TypeError(f"Unsupported interface cache configuration: {type(config)!r}")


def cached_interface_queryset(config, *, present_only=False):
    """Zwróć interfejsy cache przypisane do jednego rekordu discovery."""
    queryset = DiscoveredInterface.objects.filter(
        **{config_relation(config): config}
    )
    if present_only:
        queryset = queryset.filter(present=True)
    return queryset.order_by("name")


def has_interface_cache(config):
    """Sprawdź, czy urządzenie było już skutecznie odświeżone."""
    return config.interfaces_last_refreshed is not None


@transaction.atomic
def refresh_interface_cache(config, data, settings):
    """Atomowo zaktualizuj cache, zachowując ręczny wybór znanych portów."""
    relation = config_relation(config)
    now = timezone.now()
    existing = {
        row.normalized_name: row
        for row in cached_interface_queryset(config)
    }
    seen = set()

    for source_row in data.interfaces:
        name = str(source_row.name or "").strip()
        if not name:
            continue
        normalized_name = name.casefold()
        seen.add(normalized_name)
        cached = existing.get(normalized_name)
        selected = (
            cached.selected
            if cached is not None
            else interface_is_selected(source_row, settings, config=config)
        )
        speed_mbps = source_row.speed_mbps
        if speed_mbps is None and isinstance(config, DeviceMerakiConfig):
            # Dashboard często nie podaje speed dla rozłączonego portu MS.
            # Wtedy zapisujemy nominalną prędkość domyślnego typu NetBox.
            speed_mbps = nominal_interface_speed_mbps(
                source_row.interface_type
            )
        values = {
            "name": name,
            "description": source_row.description,
            "label": source_row.label,
            "interface_type": source_row.interface_type,
            "admin_up": source_row.admin_up,
            "oper_up": source_row.oper_up,
            "mac_address": source_row.mac_address,
            "ipv4_address": source_row.ipv4_address,
            "ipv4_mask": source_row.ipv4_mask,
            "ipv6_addresses": list(source_row.ipv6_addresses or []),
            "mtu": source_row.mtu,
            "speed_mbps": speed_mbps,
            "vpn_id": source_row.vpn_id,
            "mode": source_row.mode,
            "untagged_vlan": source_row.untagged_vlan,
            "tagged_vlans": list(source_row.tagged_vlans or []),
            "bridge_name": source_row.bridge_name,
            "selected": selected,
            "present": True,
            "last_seen": now,
        }
        if cached is None:
            DiscoveredInterface.objects.create(
                **{relation: config},
                normalized_name=normalized_name,
                **values,
            )
        else:
            for field, value in values.items():
                setattr(cached, field, value)
            cached.save(update_fields=(*values.keys(), "last_updated"))

    cached_interface_queryset(config).exclude(
        normalized_name__in=seen,
    ).update(present=False)
    config.interfaces_last_refreshed = now
    config.cached_vrrp_groups = [
        {
            "interface_name": row.interface_name,
            "group_id": row.group_id,
            "version": row.version,
            "virtual_ip": row.virtual_ip,
            "master_ip": row.master_ip,
            "virtual_mac": row.virtual_mac,
            "priority": row.priority,
        }
        for row in data.vrrp_groups
    ]
    update_fields = [
        "interfaces_last_refreshed",
        "cached_vrrp_groups",
        "last_updated",
    ]
    config.save(update_fields=update_fields)


def collected_device_from_cache(
    config,
    base_data,
    *,
    selected_only=False,
    include_absent=False,
):
    """Odtwórz DTO z podstawowych danych urządzenia i relacyjnego cache portów."""
    data = device_from_dict(base_data.to_dict())
    if isinstance(config, DeviceMerakiConfig):
        # Uzupełniamy również rekordy zapisane przed wprowadzeniem fallbacku,
        # bez ponownego odpytywania Dashboard API.
        for type_name, speed_mbps in (
            ("100base-tx", 100),
            ("1000base-t", 1000),
            ("2.5gbase-t", 2500),
            ("5gbase-t", 5000),
            ("10gbase-t", 10000),
            ("10gbase-x-sfpp", 10000),
            ("40gbase-x-qsfpp", 40000),
            ("100gbase-x-qsfp28", 100000),
        ):
            cached_interface_queryset(config).filter(
                speed_mbps__isnull=True,
                interface_type__iexact=type_name,
            ).update(speed_mbps=speed_mbps)
    queryset = cached_interface_queryset(config, present_only=not include_absent)
    if selected_only:
        queryset = queryset.filter(selected=True)
    data.interfaces = [
        CollectedInterface(
            name=row.name,
            description=row.description,
            label=row.label,
            interface_type=row.interface_type,
            admin_up=row.admin_up,
            oper_up=row.oper_up,
            mac_address=row.mac_address,
            ipv4_address=row.ipv4_address,
            ipv4_mask=row.ipv4_mask,
            ipv6_addresses=list(row.ipv6_addresses or []),
            mtu=row.mtu,
            speed_mbps=row.speed_mbps,
            vpn_id=row.vpn_id,
            mode=row.mode,
            untagged_vlan=row.untagged_vlan,
            tagged_vlans=list(row.tagged_vlans or []),
            bridge_name=row.bridge_name,
            selected=row.selected,
            present=row.present,
            last_seen=row.last_seen.isoformat() if row.last_seen else "",
        )
        for row in queryset
    ]
    payload = data.to_dict()
    payload["vrrp_groups"] = list(config.cached_vrrp_groups or [])
    return device_from_dict(payload)
