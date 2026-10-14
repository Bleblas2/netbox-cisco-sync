"""Normalizacja inventory Catalyst Center do wspólnego DTO synchronizacji."""

import ipaddress
import re

from ...dto import CollectedDevice, CollectedInterface
from ...plugin_settings import plugin_setting
from .client import CatalystCenterError

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


def collect_site_device_assignments(client, sites):
    """Zbuduj mapę deviceId → Building przez nowszy endpoint Site Design."""
    assignments = {}
    for site in sites:
        if not is_building_site(site):
            continue
        rows = client.get_site_assigned_devices(site.get("id"))
        if rows is None:
            return None
        latitude, longitude = building_coordinates(site)
        building = {
            "id": str(site.get("id") or ""),
            "name": str(site.get("name") or ""),
            "latitude": latitude,
            "longitude": longitude,
        }
        for row in rows:
            device_id = str(row.get("deviceId") or "").strip()
            if device_id:
                assignments[device_id] = building
    return assignments


def collect_inventory(
    raw_devices,
    site_memberships,
    allowed_roles="",
    *,
    site_device_assignments=None,
):
    """Zachowaj wspierane urządzenia zgodne z filtrem Family lub Role."""
    allowed = {
        value.strip().casefold()
        for value in str(allowed_roles or "").split(",")
        if value.strip()
    }
    return [
        parse_device(
            row,
            _device_site(row, site_memberships, site_device_assignments),
        )
        for row in raw_devices
        if str(row.get("deviceSupportLevel") or "").casefold() == "supported"
        and (
            not allowed
            or str(row.get("role") or "").strip().casefold() in allowed
            or str(row.get("family") or "").strip().casefold() in allowed
        )
    ]


def _device_site(raw, site_memberships, site_device_assignments=None):
    """Znajdź Building najpierw po deviceId, a następnie po serialu."""
    device_id = str(raw.get("id") or "").strip()
    if device_id and site_device_assignments:
        matched = site_device_assignments.get(device_id)
        if matched is not None:
            return matched
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
    stack_info = normalize_stack_switch_info(raw.get("stackSwitchInfo"))
    master_serial = stack_master_serial(stack_info, serial_numbers)
    stack_serials = _unique_values([
        *(row["serialNumber"] for row in stack_info),
        *serial_numbers,
    ])
    # Dla stacka Custom Field przechowuje kompletną listę członków, również
    # ACTIVE zapisanego równolegle w Device.serial. Pojedynczy switch nie jest
    # prezentowany jako jednoelementowy stack.
    is_stack = len(stack_serials) > 1 or len(stack_info) > 1
    platform_id = normalize_platform_id(platform_source)
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
        serial_number=master_serial,
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
        status="active" if str(raw.get("reachabilityStatus") or "").casefold() == "reachable" else "failed",
        source_role=str(raw.get("role") or "").strip(),
        source_family=str(raw.get("family") or "").strip(),
        switch_stack_serials=stack_serials if is_stack else [],
        switch_stack_info=stack_info,
    )


def is_stack_device(raw):
    """Rozpoznaj rekord wymagający osobnego odczytu szczegółów stacka."""
    if raw.get("stackDevice") is True:
        return True
    serials = _source_values(raw.get("serialNumbers") or raw.get("serialNumber"))
    return len(serials) > 1


def merge_stack_details(raw, details):
    """Połącz odpowiedź endpointu stacka z rekordem inventory bez mutacji wejścia."""
    merged = dict(raw)
    stack_info = details.get("stackSwitchInfo") if isinstance(details, dict) else None
    if isinstance(stack_info, list):
        merged["stackSwitchInfo"] = stack_info
        serials = _unique_values([
            *(row.get("serialNumber") for row in stack_info if isinstance(row, dict)),
            *_source_values(raw.get("serialNumbers") or raw.get("serialNumber")),
        ])
        if serials:
            merged["serialNumbers"] = serials
    return merged


def collect_device_interfaces(device, raw_interfaces):
    """Dodaj adresowane L3 oraz wszystkie fizyczne porty L2 urządzenia."""
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
        is_physical = str(raw.get("interfaceType") or "").casefold() == "physical"
        is_lag = bool(re.fullmatch(r"(?:port-?channel|po)\d+", name, re.IGNORECASE))
        if not name or not (
            (is_l3 and (ipv4_address or addresses))
            or is_physical
            or is_lag
        ):
            continue
        speed_mbps = _speed_mbps(raw.get("speed"))
        collected.append(CollectedInterface(
            name=name,
            description=str(raw.get("description") or ""),
            interface_type=(
                "lag" if is_lag else (
                    "virtual"
                    if str(raw.get("interfaceType") or "").casefold() == "virtual"
                    else _physical_interface_type(name, speed_mbps)
                )
            ),
            admin_up=str(raw.get("adminStatus") or "").casefold() == "up",
            oper_up=str(raw.get("status") or "").casefold() == "up",
            mac_address=str(raw.get("macAddress") or "").strip(),
            ipv4_address=ipv4_address,
            ipv4_mask=str(raw.get("ipv4Mask") or "").strip(),
            ipv6_addresses=ipv6_addresses,
            mtu=_int_or_none(raw.get("mtu")),
            speed_mbps=speed_mbps,
            mode=str(raw.get("portMode") or "").casefold(),
            untagged_vlan=_vlan_id(
                raw.get("vlanId")
                if str(raw.get("portMode") or "").casefold() == "access"
                else raw.get("nativeVlanId") or raw.get("nativeVlan")
                if str(raw.get("portMode") or "").casefold() == "trunk"
                else None
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


def merge_port_channel_members(device, lag, details):
    """Powiąż wyłącznie fizyczne porty wskazane przez endpoint szczegółów LAG."""
    if details.get("networkDeviceId") != device.uuid or str(details.get("name") or "").casefold() != lag.name.casefold():
        raise CatalystCenterError(f"Port channel response does not match {lag.name} or device.")
    members = details.get("interfaces")
    if members is None:
        return device
    if not isinstance(members, list):
        raise CatalystCenterError(f"Invalid member list for {lag.name}.")
    by_name = {row.name.casefold(): row for row in device.interfaces}
    for member in members:
        name = str(member.get("name") or "") if isinstance(member, dict) else ""
        row = by_name.get(name.casefold())
        if row is None or row.interface_type in {"lag", "virtual", "bridge", "cisco-stackwise"}:
            raise CatalystCenterError(f"Physical member {name} of {lag.name} was not found in inventory.")
        if row.lag_name and row.lag_name != lag.name:
            raise CatalystCenterError(f"Interface {name} belongs to multiple port channels.")
        row.lag_name = lag.name
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


def _source_values(value):
    """Znormalizuj starszy CSV oraz nowszą listę wartości Catalyst Center."""
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def _unique_values(values):
    """Usuń puste i powtórzone wartości bez zmiany kolejności z CCC."""
    result = []
    for value in values:
        normalized = str(value or "").strip()
        if normalized and normalized not in result:
            result.append(normalized)
    return result


def normalize_stack_switch_info(value):
    """Zachowaj stabilny format JSON członków stacka Catalyst Center."""
    rows = value if isinstance(value, list) else []
    result = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        serial = str(row.get("serialNumber") or "").strip()
        if not serial:
            continue
        result.append({
            "stackMemberNumber": _int_or_none(row.get("stackMemberNumber")),
            "switchPriority": _int_or_none(row.get("switchPriority")),
            "role": str(row.get("role") or "").strip(),
            "serialNumber": serial,
            "platformId": str(row.get("platformId") or "").strip(),
        })
    return sorted(
        result,
        key=lambda row: (
            row["stackMemberNumber"] is None,
            row["stackMemberNumber"] or 0,
        ),
    )


def stack_master_serial(stack_info, fallback_serials=()):
    """Wybierz serial ACTIVE, następnie member 1, a na końcu pierwszy serial."""
    for role in ("active", "master"):
        for row in stack_info:
            if str(row.get("role") or "").casefold() == role:
                return row["serialNumber"]
    for row in stack_info:
        if row.get("stackMemberNumber") == 1:
            return row["serialNumber"]
    serials = _source_values(fallback_serials)
    return serials[0] if serials else ""


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
        vid = int(value) if value not in (None, "") else None
        return vid if vid is not None and 1 <= vid <= 4094 else None
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
