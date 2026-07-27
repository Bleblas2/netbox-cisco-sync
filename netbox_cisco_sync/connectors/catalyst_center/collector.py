"""Normalizacja inventory Catalyst Center do wspólnego DTO synchronizacji."""

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
