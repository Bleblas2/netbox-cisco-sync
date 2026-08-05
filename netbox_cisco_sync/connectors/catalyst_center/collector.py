"""Normalizacja inventory Catalyst Center do wspólnego DTO synchronizacji."""

import ipaddress

from ...dto import CollectedDevice, CollectedInterface
from ...plugin_settings import plugin_setting

DEVICE_DOMAIN_SUFFIX = ".raben-group.com"
CORE_ROLE_NAME = "Core Switch"
ACCESS_ROLE_NAME = "Branches Access Switches"


def _float_or_none(value):
    """Zamień współrzędną z API na liczbę albo None dla pustej/błędnej wartości."""
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def is_building_site(site):
    """Rozpoznaj Building w zagnieżdżonych metadanych Location."""
    for info in site.get("additionalInfo") or []:
        if "Location" not in str(info.get("nameSpace") or ""):
            continue
        return str((info.get("attributes") or {}).get("type") or "").casefold() == "building"
    return False


def building_coordinates(site):
    """Pobierz latitude i longitude z metadanych Location budynku CCC."""
    for info in site.get("additionalInfo") or []:
        if "Location" not in str(info.get("nameSpace") or ""):
            continue
        attributes = info.get("attributes") or {}
        if not isinstance(attributes, dict):
            continue
        latitude = _float_or_none(attributes.get("latitude"))
        longitude = _float_or_none(attributes.get("longitude"))
        if latitude is not None and longitude is not None:
            return latitude, longitude
    return None, None


def collect_site_memberships(client, sites):
    """Zbuduj mapę numer seryjny → Building wraz ze współrzędnymi."""
    memberships = {}
    for site in sites:
        if not is_building_site(site):
            continue
        latitude, longitude = building_coordinates(site)
        for device in client.get_site_membership(site.get("id")):
            serial = str(device.get("serialNumber") or "").strip()
            if serial:
                memberships[serial] = {
                    "id": str(site.get("id") or ""),
                    "name": str(site.get("name") or ""),
                    "latitude": latitude,
                    "longitude": longitude,
                }
    return memberships


def collect_inventory(raw_devices, site_memberships, allowed_roles=""):
    """Zachowaj wspierane urządzenia zgodne z filtrem Family lub Role."""
    allowed = {
        value.strip().casefold()
        for value in str(allowed_roles or "").split(",")
        if value.strip()
    }
    return [
        parse_device(row, site_memberships.get(str(row.get("serialNumber") or "").strip()))
        for row in raw_devices
        if str(row.get("deviceSupportLevel") or "").casefold() == "supported"
        and (
            not allowed
            or str(row.get("role") or "").strip().casefold() in allowed
            or str(row.get("family") or "").strip().casefold() in allowed
        )
    ]


def parse_device(raw, site=None):
    """Zamień rekord CCC i Building na DTO niezależne od formatu API."""
    hostname = normalize_hostname(raw.get("hostname"))
    management_ip = str(raw.get("managementIpAddress") or "").strip()
    platform_id = normalize_platform_id(raw.get("platformId"))
    interfaces = []
    if management_ip:
        interfaces.append(CollectedInterface(
            name="Management",
            description="Catalyst Center management address",
            interface_type="virtual",
            ipv4_address=management_ip,
            ipv4_mask="255.255.255.255",
        ))
    return CollectedDevice(
        system_ip=management_ip,
        hostname=hostname,
        uuid=str(raw.get("id") or ""),
        serial_number=str(raw.get("serialNumber") or "").strip(),
        model=platform_id,
        site_id=str((site or {}).get("id") or ""),
        site_name=str((site or {}).get("name") or ""),
        latitude=_float_or_none((site or {}).get("latitude")),
        longitude=_float_or_none((site or {}).get("longitude")),
        reachability=str(raw.get("reachabilityStatus") or ""),
        interfaces=interfaces,
        role_name=role_name(hostname),
        platform_name=plugin_setting("ccc_default_platform_name"),
        platform_slug=plugin_setting("ccc_default_platform_slug"),
        device_type_part_number=platform_id,
        require_existing_device_type=True,
        status="active" if str(raw.get("reachabilityStatus") or "").casefold() == "reachable" else "failed",
        source_role=str(raw.get("role") or "").strip(),
        source_family=str(raw.get("family") or "").strip(),
    )


def collect_device_interfaces(device, raw_interfaces):
    """Dodaj wyłącznie adresowane interfejsy L3 i usuń duplikat Management."""
    collected = []
    for raw in raw_interfaces or []:
        name = str(raw.get("portName") or raw.get("name") or "").strip()
        ipv4_address = str(raw.get("ipv4Address") or "").strip()
        addresses = raw.get("addresses") or []
        ipv6_addresses = _ipv6_addresses(addresses)
        is_l3 = (
            str(raw.get("portMode") or "").casefold() == "routed"
            or str(raw.get("interfaceType") or "").casefold() == "virtual"
            or str(raw.get("portType") or "").casefold() == "ethernet svi"
        )
        if not name or not is_l3 or not (ipv4_address or addresses):
            continue
        collected.append(CollectedInterface(
            name=name,
            description=str(raw.get("description") or ""),
            interface_type="virtual" if str(raw.get("interfaceType") or "").casefold() == "virtual" else "other",
            admin_up=str(raw.get("adminStatus") or "").casefold() == "up",
            oper_up=str(raw.get("status") or "").casefold() == "up",
            mac_address=str(raw.get("macAddress") or "").strip(),
            ipv4_address=ipv4_address,
            ipv4_mask=str(raw.get("ipv4Mask") or "").strip(),
            ipv6_addresses=ipv6_addresses,
            mtu=_int_or_none(raw.get("mtu")),
            speed_mbps=_speed_mbps(raw.get("speed")),
        ))

    real_addresses = {
        row.ipv4_address for row in collected if row.ipv4_address
    }
    device.interfaces = [
        row for row in device.interfaces
        if row.name != "Management" or row.ipv4_address not in real_addresses
    ]
    device.interfaces.extend(collected)
    return device


def _int_or_none(value):
    """Zamień wartość całkowitą z API na int albo None."""
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _speed_mbps(value):
    """Zamień prędkość Catalyst Center podawaną w kb/s na Mb/s."""
    speed = _int_or_none(value)
    return speed / 1000 if speed is not None else None


def _ipv6_addresses(addresses):
    """Wyodrębnij adresy IPv6 z niejednolitej listy addresses API."""
    result = []
    for value in addresses if isinstance(addresses, list) else []:
        address = value
        if isinstance(value, dict):
            address = value.get("ipAddress") or value.get("address")
            if isinstance(address, dict):
                address = address.get("address")
        text = str(address or "").strip()
        try:
            parsed = ipaddress.ip_interface(text)
        except ValueError:
            continue
        if parsed.version == 6:
            result.append(text)
    return result


def normalize_hostname(value):
    hostname = str(value or "").strip()
    if hostname.casefold().endswith(DEVICE_DOMAIN_SUFFIX.casefold()):
        return hostname[:-len(DEVICE_DOMAIN_SUFFIX)]
    return hostname


def normalize_platform_id(value):
    # Stos Catalyst może raportować kilka PID rozdzielonych przecinkiem.
    # Pierwszy PID jest zgodny z part_number Device Type używanym przez Apply.
    return str(value or "").split(",", 1)[0].strip()


def role_name(hostname):
    return CORE_ROLE_NAME if "CORE" in str(hostname or "").upper() else ACCESS_ROLE_NAME
