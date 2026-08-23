"""Wspólna polityka obsługi prywatnych adresów IPv4 na portach WAN."""

import ipaddress
import re


RFC1918_NETWORKS = tuple(
    ipaddress.ip_network(value)
    for value in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
)
MANAGED_DESCRIPTION_PREFIX = "Cisco Sync RFC1918 WAN IP:"
WAN_NAME_PATTERN = re.compile(r"^wan\s*\d*$", re.IGNORECASE)


def is_wan_interface(row):
    """Rozpoznaj WAN, WAN z numerem oraz port Meraki oznaczony etykietą WAN."""
    return any(
        WAN_NAME_PATTERN.fullmatch(str(value or "").strip())
        for value in (getattr(row, "name", ""), getattr(row, "label", ""))
    )


def is_rfc1918_ipv4(value):
    """Sprawdź przynależność IPv4 wyłącznie do trzech zakresów RFC1918."""
    try:
        address = ipaddress.ip_interface(str(value)).ip
    except ValueError:
        return False
    return address.version == 4 and any(address in network for network in RFC1918_NETWORKS)


def ignored_rfc1918_wan_cidr(row, settings):
    """Zwróć CIDR pomijanego adresu WAN albo pustą wartość."""
    if not getattr(settings, "ignore_rfc1918_wan_ips", False):
        return ""
    if not is_wan_interface(row):
        return ""
    from .addresses import ipv4_cidr

    cidr = ipv4_cidr(row.ipv4_address, row.ipv4_mask)
    return cidr if cidr and is_rfc1918_ipv4(cidr) else ""


def effective_interface_description(row, settings):
    """Dodaj pomijany prywatny adres WAN do opisu bez dublowania wpisu."""
    description = str(getattr(row, "description", "") or "").strip()
    cidr = ignored_rfc1918_wan_cidr(row, settings)
    if not cidr:
        return description
    marker = f"{MANAGED_DESCRIPTION_PREFIX} {cidr}"
    if marker.casefold() in description.casefold():
        return description
    return f"{description} | {marker}" if description else marker
