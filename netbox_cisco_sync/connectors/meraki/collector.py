"""Normalizacja danych Meraki do wspólnego DTO synchronizacji."""

import ipaddress

from ..base import ConnectorError
from ...dto import CollectedDevice, CollectedInterface
from ...plugin_settings import plugin_setting


def product_family(model):
    """Zwróć dwuliterową rodzinę produktu, np. MS, MX albo MR."""
    return str(model or "")[:2].upper()


def parse_inventory_device(raw, network):
    model = str(raw.get("model") or "")
    lan_ip = str(raw.get("lanIp") or raw.get("wan1Ip") or "").strip()
    return CollectedDevice(
        system_ip=lan_ip,
        hostname=str(raw.get("name") or raw.get("serial") or ""),
        uuid=str(raw.get("serial") or ""),
        serial_number=str(raw.get("serial") or ""),
        model=model,
        site_id=str(network.get("id") or ""),
        site_name=str(network.get("name") or ""),
        latitude=_float_or_none(raw.get("lat")),
        longitude=_float_or_none(raw.get("lng")),
        reachability=str(raw.get("status") or ""),
        role_name="Meraki Device",
        platform_name=plugin_setting("meraki_default_platform_name"),
        platform_slug=plugin_setting("meraki_default_platform_slug"),
        device_type_part_number=model,
        source_family=product_family(model),
    )


def collect_device_details(device, client):
    """Pobierz interfejsy właściwe dla rodziny MS, MX lub MR."""
    interfaces = []
    family_types = plugin_setting("meraki_family_interface_types")
    if device.source_family == "MS":
        statuses = {
            str(row.get("portId") or ""): row
            for row in client.get_switch_port_statuses(device.serial_number)
        }
        for row in client.get_switch_ports(device.serial_number):
            port_id = str(row.get("portId") or "")
            status = statuses.get(port_id, {})
            interfaces.append(CollectedInterface(
                name=port_id,
                description=str(row.get("name") or ""),
                interface_type=family_types.get("MS", "1000base-t"),
                admin_up=bool(row.get("enabled", True)),
                oper_up=str(status.get("status") or "").casefold() == "connected",
                speed_mbps=_speed_mbps(status.get("speed")),
            ))
    elif device.source_family == "MX":
        raw = client.get_device(device.serial_number)
        # Nazwy i zachowanie odpowiadają sprawdzonej integracji referencyjnej.
        for name, description, address in (
            ("WAN 1", "WAN 1 uplink", raw.get("wan1Ip")),
            ("WAN 2", "WAN 2 uplink", raw.get("wan2Ip")),
        ):
            if address:
                interfaces.append(CollectedInterface(
                    name=name,
                    description=description,
                    interface_type=family_types.get("MX", "1000base-t"),
                    admin_up=True,
                    oper_up=True,
                    ipv4_address=str(address),
                    # Dashboard API nie zwraca maski w tym obiekcie. /32 zachowuje
                    # adres bez zgadywania prefiksu sieci użytkownika.
                    ipv4_mask="255.255.255.255",
                ))
        single_lan = {}
        try:
            single_lan = client.get_appliance_single_lan(device.site_id)
        except ConnectorError:
            # Sieć MX z włączonymi VLAN-ami może nie udostępniać singleLan.
            # Wtedy zachowujemy historyczny lanIp jako bezpieczny fallback.
            pass
        appliance_ip = str(single_lan.get("applianceIp") or "").strip()
        if appliance_ip:
            interfaces.append(CollectedInterface(
                name="SingleLan",
                description="Meraki MX single LAN",
                interface_type=family_types.get("MX", "1000base-t"),
                admin_up=True,
                oper_up=True,
                ipv4_address=appliance_ip,
                ipv4_mask=_subnet_mask(single_lan.get("subnet")),
            ))
        elif raw.get("lanIp"):
            interfaces.append(CollectedInterface(
                name="LAN",
                description="LAN interface",
                interface_type=family_types.get("MX", "1000base-t"),
                admin_up=True,
                oper_up=True,
                ipv4_address=str(raw.get("lanIp")),
                ipv4_mask="255.255.255.255",
            ))
    elif device.source_family == "MR":
        interfaces.append(CollectedInterface(
            name="Radio 0",
            description=device.model,
            interface_type=family_types.get("MR", "ieee802.11ax"),
            admin_up=True,
            oper_up=True,
        ))

    # Dla rodzin bez dedykowanego modelu portów albo pustej odpowiedzi API
    # zachowujemy pojedynczy interfejs zarządzający zamiast utraty adresu IP.
    if not interfaces:
        interfaces.append(CollectedInterface(
            name="Management",
            description="Meraki management address",
            interface_type="virtual",
            ipv4_address=device.system_ip,
            ipv4_mask="255.255.255.255" if device.system_ip else "",
        ))
    device.interfaces = interfaces
    return device


def _float_or_none(value):
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _speed_mbps(value):
    text = str(value or "").strip().casefold()
    try:
        if "gbps" in text:
            return float(text.replace("gbps", "").strip()) * 1000
        if "mbps" in text:
            return float(text.replace("mbps", "").strip())
    except ValueError:
        pass
    return None


def _subnet_mask(value):
    """Zamień podsieć CIDR z singleLan na maskę oczekiwaną przez wspólny DTO."""
    try:
        return str(ipaddress.ip_network(str(value), strict=False).netmask)
    except ValueError:
        return "255.255.255.255"
