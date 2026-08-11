"""Normalizacja inventory Catalyst Center do wspólnego DTO synchronizacji."""

import ipaddress
import re

from ...dto import CollectedDevice, CollectedInterface, CollectedStackMember
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
        parse_device(row, _device_site(row, site_memberships))
        for row in raw_devices
        if str(row.get("deviceSupportLevel") or "").casefold() == "supported"
        and (
            not allowed
            or str(row.get("role") or "").strip().casefold() in allowed
            or str(row.get("family") or "").strip().casefold() in allowed
        )
    ]


def _device_site(raw, site_memberships):
    """Znajdź Building po dowolnym serialu logicznego urządzenia lub stacka."""
    serials = _source_values(raw.get("serialNumbers") or raw.get("serialNumber"))
    return next(
        (site_memberships[serial] for serial in serials if serial in site_memberships),
        None,
    )


def parse_device(raw, site=None):
    """Zamień rekord CCC i Building na DTO niezależne od formatu API."""
    hostname = normalize_hostname(raw.get("hostname"))
    management_ip = str(raw.get("managementIpAddress") or "").strip()
    serial_source = raw.get("serialNumbers") or raw.get("serialNumber")
    platform_source = raw.get("platformIds") or raw.get("platformId")
    serial_numbers = _source_values(serial_source)
    platform_id = normalize_platform_id(platform_source)
    stack_members = parse_stack_members(
        serial_source,
        platform_source,
    )
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
        serial_number=", ".join(serial_numbers),
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
        stack_members=stack_members,
    )


def collect_device_interfaces(device, raw_interfaces, *, include_l2=False):
    """Dodaj interfejsy L3, a w trybie szczegółowym również fizyczne porty L2."""
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
        is_l2 = (
            str(raw.get("interfaceType") or "").casefold() == "physical"
            and str(raw.get("portMode") or "").casefold() != "routed"
        )
        if not name or not (
            (is_l3 and (ipv4_address or addresses))
            or (include_l2 and is_l2)
        ):
            continue
        speed_mbps = _speed_mbps(raw.get("speed"))
        collected.append(CollectedInterface(
            name=name,
            description=str(raw.get("description") or ""),
            interface_type=(
                "virtual"
                if str(raw.get("interfaceType") or "").casefold() == "virtual"
                else _physical_interface_type(name, speed_mbps)
            ),
            admin_up=str(raw.get("adminStatus") or "").casefold() == "up",
            oper_up=str(raw.get("status") or "").casefold() == "up",
            mac_address=str(raw.get("macAddress") or "").strip(),
            ipv4_address=ipv4_address,
            ipv4_mask=str(raw.get("ipv4Mask") or "").strip(),
            ipv6_addresses=ipv6_addresses,
            mtu=_int_or_none(raw.get("mtu")),
            speed_mbps=speed_mbps,
            stack_member_position=_stack_member_position(name),
            mode=str(raw.get("portMode") or "").casefold(),
            untagged_vlan=_vlan_id(
                raw.get("vlanId")
                or raw.get("nativeVlanId")
                or raw.get("nativeVlan")
            ),
            tagged_vlans=_vlan_ids(
                raw.get("allowedVlanIds")
                or raw.get("allowedVlans")
                or raw.get("vlanIds")
            ),
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
    values = _source_values(value)
    return values[0] if values else ""


def parse_stack_members(serial_numbers, platform_ids):
    """Rozbij zagregowane pola inventory CCC na uporządkowanych członków stacka."""
    serials = _source_values(serial_numbers)
    models = _source_values(platform_ids)
    if len(serials) <= 1 and len(models) <= 1:
        return []
    if not serials or len(serials) != len(models):
        return []
    return [
        CollectedStackMember(position=position, serial_number=serial, model=model)
        for position, (serial, model) in enumerate(zip(serials, models), start=1)
    ]


def _source_values(value):
    """Znormalizuj starszy CSV oraz nowszą listę wartości Catalyst Center."""
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def collect_stack_members_from_equipment(rows, *, fallback=()):
    """Zbuduj członków z fizycznych chassis, a brakującą pozycję ustal stabilnie."""
    candidates = []
    seen_serials = set()
    fallback_positions = {
        member.serial_number: member.position for member in fallback or []
    }
    for order, row in enumerate(rows or [], start=1):
        serial = str(row.get("serialNumber") or "").strip()
        model = str(row.get("productId") or "").strip()
        if not serial or not model or serial in seen_serials:
            continue
        seen_serials.add(serial)
        label = " ".join(
            str(row.get(key) or "")
            for key in ("name", "description", "vendorEquipmentType")
        )
        match = re.search(r"(?:switch|member|chassis|stack)\s*#?\s*(\d+)", label, re.IGNORECASE)
        position = (
            int(match.group(1))
            if match
            else fallback_positions.get(serial, order)
        )
        candidates.append((position, order, serial, model))
    if not candidates:
        return list(fallback or [])
    candidates.sort(key=lambda value: (value[0], value[1]))
    return [
        CollectedStackMember(
            position=position,
            serial_number=serial,
            model=model,
        )
        for position, (_, _, serial, model) in enumerate(candidates, start=1)
    ]


def _stack_member_position(name):
    """Pobierz numer członka z nazw typu GigabitEthernet2/0/10."""
    match = re.search(r"(?:Ethernet|StackPort)(\d+)/", str(name or ""), re.IGNORECASE)
    position = int(match.group(1)) if match else None
    return position if position and position > 0 else None


def _physical_interface_type(name, speed_mbps):
    """Dobierz typ NetBox na podstawie nazwy i prędkości portu CCC."""
    normalized = str(name or "").casefold()
    if normalized.startswith("stackport"):
        return "cisco-stackwise"
    if speed_mbps is not None and speed_mbps >= 100000:
        return "100gbase-x-qsfp28"
    if speed_mbps is not None and speed_mbps >= 40000:
        return "40gbase-x-qsfpp"
    if speed_mbps is not None and speed_mbps >= 10000:
        return "10gbase-x-sfpp"
    return "1000base-t"


def _vlan_id(value):
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _vlan_ids(value):
    """Znormalizuj listę lub zakresy VLAN zwracane w różnych wersjach CCC."""
    if isinstance(value, list):
        return [vlan for item in value if (vlan := _vlan_id(item)) is not None]
    result = []
    for token in str(value or "").split(","):
        token = token.strip()
        if not token:
            continue
        if "-" in token:
            first, last = token.split("-", 1)
            try:
                result.extend(range(int(first), int(last) + 1))
            except ValueError:
                continue
        elif (vlan := _vlan_id(token)) is not None:
            result.append(vlan)
    return result


def role_name(hostname):
    return CORE_ROLE_NAME if "CORE" in str(hostname or "").upper() else ACCESS_ROLE_NAME
