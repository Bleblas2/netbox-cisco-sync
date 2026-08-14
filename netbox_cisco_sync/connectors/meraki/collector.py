"""Normalizacja danych Meraki do wspólnego DTO synchronizacji."""

import ipaddress
import re

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
        try:
            uplink_settings = client.get_appliance_uplinks_settings(
                device.serial_number
            )
        except ConnectorError:
            # Starszy model lub zakres uprawnień może nie udostępniać endpointu.
            uplink_settings = {}
        interfaces.extend(_collect_appliance_uplinks(
            raw,
            uplink_settings,
            family_types.get("MX", "1000base-t"),
        ))
        reserved_lan_ports = _wan_reserved_lan_ports(
            device.model,
            raw,
            uplink_settings,
        )
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
                name="singlelan",
                description="Meraki MX single LAN",
                interface_type="bridge",
                admin_up=True,
                oper_up=True,
                ipv4_address=appliance_ip,
                ipv4_mask=_subnet_mask(single_lan.get("subnet")),
            ))
            interfaces.extend(
                CollectedInterface(
                    name=f"Port {port_number}",
                    description="Meraki MX single LAN member",
                    interface_type=family_types.get("MX", "1000base-t"),
                    admin_up=True,
                    oper_up=True,
                    bridge_name="singlelan",
                )
                for port_number in range(2, 6)
                if port_number not in reserved_lan_ports
            )
        else:
            try:
                appliance_ports = client.get_appliance_ports(device.site_id)
            except ConnectorError:
                appliance_ports = []
            interfaces.extend(
                _collect_appliance_ports(
                    appliance_ports,
                    family_types.get("MX", "1000base-t"),
                    excluded_ports=reserved_lan_ports,
                )
            )
            if raw.get("lanIp"):
                interfaces.append(CollectedInterface(
                    name="LAN",
                    description="LAN interface",
                    interface_type="virtual",
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


def _collect_appliance_ports(rows, interface_type, *, excluded_ports=()):
    """Znormalizuj konfigurację portów LAN MX zwracaną dla całej sieci."""
    result = []
    excluded = {str(value) for value in excluded_ports}
    for row in rows if isinstance(rows, list) else []:
        port_number = row.get("number")
        if port_number in (None, "") or str(port_number) in excluded:
            continue
        mode = str(row.get("type") or "").strip().casefold()
        allowed_vlans = str(row.get("allowedVlans") or "").strip()
        netbox_mode = (
            "tagged-all"
            if mode == "trunk" and allowed_vlans.casefold() == "all"
            else mode if mode in {"access", "trunk"} else ""
        )
        result.append(CollectedInterface(
            name=f"Port {port_number}",
            description="Meraki MX LAN port",
            interface_type=interface_type,
            admin_up=bool(row.get("enabled", True)),
            # Ten endpoint zwraca konfigurację, ale nie stan fizycznego linku.
            oper_up=False,
            mode=netbox_mode,
            untagged_vlan=(
                None
                if bool(row.get("dropUntaggedTraffic"))
                else _vlan_id(row.get("vlan"))
            ),
            tagged_vlans=_vlan_ids(allowed_vlans) if mode == "trunk" else [],
        ))
    return result


def _wan_reserved_lan_ports(model, device_data, uplink_settings):
    """Wyklucz Port 2, gdy MX64/MX67 wykorzystuje go jako fizyczny WAN2."""
    if str(model or "").strip().upper() not in {"MX64", "MX67"}:
        return set()
    configured = (
        uplink_settings.get("interfaces", {})
        if isinstance(uplink_settings, dict)
        else {}
    )
    wan2 = configured.get("wan2") if isinstance(configured, dict) else None
    if isinstance(wan2, dict):
        wan2_used = wan2.get("enabled") is True
    else:
        # Fallback dla starszego API: obecny adres WAN2 oznacza wykorzystanie portu.
        wan2_used = bool(str(device_data.get("wan2Ip") or "").strip())
    return {2} if wan2_used else set()


def _collect_appliance_uplinks(device_data, settings, interface_type):
    """Połącz konfigurację WAN z aktualnymi adresami zwracanymi przez Device."""
    configured = settings.get("interfaces", {}) if isinstance(settings, dict) else {}
    names = {
        str(name).casefold()
        for name in configured
        if re.fullmatch(r"wan\d+", str(name), re.IGNORECASE)
    }
    names.update(
        match.group(1).casefold()
        for key in device_data if (match := re.fullmatch(r"(wan\d+)Ip", str(key), re.IGNORECASE))
    )
    # Zachowaj dotychczasową obsługę WAN1/WAN2, gdy endpoint ustawień jest
    # niedostępny, ale Device zwraca tylko jedno z pól adresowych.
    if not names:
        names.update({"wan1", "wan2"})

    result = []
    for name in sorted(names, key=lambda value: int(value[3:])):
        number = int(name[3:])
        config = configured.get(name, {})
        if not isinstance(config, dict):
            config = {}
        address, mask = _uplink_ipv4(device_data, name, config)
        # Bez endpointu ustawień zachowujemy wcześniejszą zasadę: port bez
        # raportowanego adresu nie jest zgadywany na podstawie numeru.
        if not configured and not address:
            continue
        vlan_tagging = config.get("vlanTagging") or {}
        interfaces_type = str(interface_type or "1000base-t")
        result.append(CollectedInterface(
            name=f"Internet {number}",
            description=f"WAN {number} uplink",
            label=f"WAN{number}",
            interface_type=interfaces_type,
            admin_up=bool(config.get("enabled", True)),
            oper_up=bool(address),
            ipv4_address=address,
            ipv4_mask=mask,
            untagged_vlan=(
                _vlan_id(vlan_tagging.get("vlanId"))
                if vlan_tagging.get("enabled") is True
                else None
            ),
        ))
    return result


def _uplink_ipv4(device_data, name, config):
    """Pobierz aktualny lub skonfigurowany statyczny adres IPv4 WAN."""
    value = str(device_data.get(f"{name}Ip") or "").strip()
    if not value:
        ipv4 = ((config.get("svis") or {}).get("ipv4") or {})
        value = str(ipv4.get("address") or "").strip()
    if not value:
        return "", ""
    try:
        parsed = ipaddress.ip_interface(value)
    except ValueError:
        return value, "255.255.255.255"
    return str(parsed.ip), str(parsed.netmask)


def _vlan_id(value):
    """Zamień pojedynczy identyfikator VLAN na liczbę."""
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _vlan_ids(value):
    """Rozwiń listę i zakresy VLAN; wartość all pozostaw bez zgadywania."""
    result = []
    for token in str(value or "").split(","):
        token = token.strip()
        if not token or token.casefold() == "all":
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
