"""Normalizacja odpowiedzi vManage do przewidywalnych obiektów DTO."""

import re

from ...dto import CollectedDevice, CollectedInterface, CollectedVrrp
from ...plugin_settings import plugin_setting

def is_edge(raw):
    """Rozpoznaj Edge na podstawie obu pól, bo wersje vManage używają ich różnie."""
    personality = str(raw.get("personality") or "").lower()
    device_type = str(raw.get("device-type") or "").lower()
    controller_types = configured_device_types("controller_types")
    edge_types = configured_device_types("edge_types")
    if personality in controller_types or device_type in controller_types:
        return False
    return personality in edge_types or device_type in edge_types


def configured_device_types(setting_name):
    """Zwróć skonfigurowane typy vManage bez rozróżniania wielkości liter."""
    return {str(value).casefold() for value in plugin_setting(f"vmanage_{setting_name}")}


def collect_inventory(raw_devices):
    """Zwróć wyłącznie lekkie rekordy Edge używane na ekranie discovery."""
    return [parse_device(raw) for raw in raw_devices if is_edge(raw)]


def collect_details(client, inventory_device):
    """Uzupełnij rekord inventory o kosztowniejsze zapytania per-device."""
    # Interfejsy i VRRP pobieramy dopiero dla wybranego urządzenia. Discovery nie wykonuje
    # setek dodatkowych requestów i dzięki temu szybko odświeża tabelę konfiguracji.
    inventory_device.interfaces = [parse_interface(row) for row in client.get_interfaces(inventory_device.system_ip)]
    inventory_device.vrrp_groups = [parse_vrrp(row) for row in client.get_vrrp(inventory_device.system_ip)]
    return inventory_device


def parse_device(raw):
    """Zachowaj tylko pola potrzebne do identyfikacji, mapowania Site i tworzenia Device."""
    uuid = str(raw.get("uuid") or "").strip()
    return CollectedDevice(
        system_ip=str(raw.get("system-ip") or raw.get("deviceId") or ""),
        hostname=str(raw.get("host-name") or raw.get("system-ip") or ""),
        uuid=uuid,
        # W inventory vManage właściwy numer seryjny sprzętu jest ostatnim
        # segmentem UUID, np. C1161X-8PLTEP-FGL2620LC9E -> FGL2620LC9E.
        # Pole board-serial ma inne znaczenie i nie zapisujemy go jako serial NetBox.
        serial_number=_serial_from_uuid(uuid),
        # vManage poprzedza model Edge prefiksem "vedge-", którego nie ma
        # w nazwie właściwego modelu/part number urządzenia w NetBox.
        model=_normalize_device_model(raw.get("device-model")),
        site_id=str(raw.get("site-id") or ""),
        site_name=str(raw.get("site-name") or ""),
        latitude=_float_or_none(raw.get("latitude")),
        longitude=_float_or_none(raw.get("longitude")),
        device_groups=list(raw.get("device-groups") or []),
        reachability=str(raw.get("reachability") or ""),
        platform_name=plugin_setting("vmanage_default_platform_name"),
        platform_slug=plugin_setting("vmanage_default_platform_slug"),
    )


def _serial_from_uuid(value):
    """Zwróć ostatni niepusty segment UUID jako numer seryjny urządzenia."""
    uuid = str(value or "").strip()
    if not uuid:
        return ""
    return uuid.rsplit("-", 1)[-1].strip()


def _normalize_device_model(value):
    """Usuń wyłącznie początkowy prefiks vManage ``vedge-`` z nazwy modelu."""
    model = str(value or "").strip()
    prefix = "vedge-"
    if model.lower().startswith(prefix):
        return model[len(prefix):]
    return model


def parse_interface(raw):
    """Ujednolić nazwy pól CEdge i przygotować listę adresów IPv6."""
    ipv6 = raw.get("ipv6-addrs") or raw.get("ipv6-address") or []
    if isinstance(ipv6, str):
        # W zależności od platformy vManage zwraca pojedynczy string, listę albo
        # wartości rozdzielone przecinkiem/spacją.
        ipv6 = [value.strip() for value in re.split(r"[, ]+", ipv6) if value.strip() and value != "-"]
    return CollectedInterface(
        name=str(raw.get("ifname") or ""),
        description=str(raw.get("description") or ""),
        interface_type=str(raw.get("interface-type") or ""),
        admin_up=str(raw.get("if-admin-status") or "").lower() in {"up", "if-state-up"},
        oper_up=str(raw.get("if-oper-status") or "").lower() in {"up", "if-oper-state-ready"},
        mac_address=str(raw.get("hwaddr") or ""),
        ipv4_address=str(raw.get("ip-address") or ""),
        ipv4_mask=str(raw.get("ipv4-subnet-mask") or ""),
        ipv6_addresses=ipv6,
        mtu=_int_or_none(raw.get("mtu")),
        speed_mbps=_float_or_none(raw.get("speed-mbps")),
        vpn_id=str(raw.get("vpn-id") or ""),
    )


def parse_vrrp(raw):
    """Przekształć operacyjny rekord VRRP do pól obsługiwanych przez NetBox FHRP."""
    return CollectedVrrp(
        interface_name=str(raw.get("if-name") or ""),
        group_id=int(raw.get("group-id")),
        version=str(raw.get("version") or ""),
        virtual_ip=str(raw.get("virtual-ip") or ""),
        master_ip=str(raw.get("master-ip") or ""),
        virtual_mac=str(raw.get("virtual-mac") or ""),
        priority=_int_or_none(raw.get("priority")),
    )


def _float_or_none(value):
    # Brak lub tekst typu N/A nie powinien przerwać discovery całego vManage.
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int_or_none(value):
    # Liczby w API bywają zwracane jako stringi, dlatego konwersja jest jawna.
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
