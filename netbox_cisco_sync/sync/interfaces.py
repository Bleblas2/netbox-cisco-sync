"""Synchronizacja interfejsów, adresów MAC i reguł filtrowania portów."""

import re

from django.contrib.contenttypes.models import ContentType

from ..plugin_settings import platform_plugin_setting
from .result import record_synced_object, update_fields
from .wan import effective_interface_description
from .vlans import sync_interface_vlans


NOMINAL_INTERFACE_SPEEDS_MBPS = {
    "100base-tx": 100,
    "1000base-t": 1000,
    "2.5gbase-t": 2500,
    "5gbase-t": 5000,
    "10gbase-t": 10000,
    "10gbase-x-sfpp": 10000,
    "40gbase-x-qsfpp": 40000,
    "100gbase-x-qsfp28": 100000,
}


def nominal_interface_speed_mbps(interface_type_name):
    """Zwróć nominalną prędkość wynikającą z typu interfejsu NetBox."""
    return NOMINAL_INTERFACE_SPEEDS_MBPS.get(
        str(interface_type_name or "").casefold()
    )


def sync_interfaces(device, rows, settings, result, config=None):
    """Utwórz lub opcjonalnie zaktualizuj interfejsy i ich adresy MAC."""
    from dcim.models import Interface

    interfaces = {}
    # Bridge musi powstać przed portami członkowskimi, a interfejs fizyczny przed
    # subinterfejsem z kropką, aby relacje wskazywały zapisane obiekty NetBox.
    ordered = sorted(
        (
            row
            for row in syncable_interface_rows(rows, settings, config=config)
            if row.name
        ),
        key=lambda row: (
            str(row.interface_type or "").casefold() != "bridge",
            interface_type(row, settings) != "lag",
            "." in row.name,
            row.name.casefold(),
        ),
    )
    for row in ordered:
        interface = Interface.objects.filter(device=device, name=row.name).first()
        legacy_name = _legacy_meraki_interface_name(row.name, settings)
        if interface is None and legacy_name:
            interface = Interface.objects.filter(device=device, name=legacy_name).first()
        parent_name = row.name.rsplit(".", 1)[0] if "." in row.name else ""
        parent = (
            interfaces.get(parent_name)
            or Interface.objects.filter(device=device, name=parent_name).first()
        )
        bridge = (
            interfaces.get(row.bridge_name)
            or Interface.objects.filter(device=device, name=row.bridge_name).first()
            if row.bridge_name
            else None
        )
        if row.bridge_name and bridge is None:
            raise ValueError(
                f"Bridge interface {row.bridge_name} required by {row.name} does not exist."
            )
        if bridge is not None and bridge.type != "bridge":
            raise ValueError(
                f"Interface {row.bridge_name} required by {row.name} is not a bridge."
            )
        lag_name = getattr(row, "lag_name", "")
        lag = (
            interfaces.get(lag_name)
            or Interface.objects.filter(device=device, name=lag_name).first()
            if lag_name else None
        )
        if lag_name and (lag is None or lag.type != "lag"):
            raise ValueError(
                f"LAG interface {lag_name} required by {row.name} does not exist or is not a LAG."
            )
        values = {
            "type": interface_type(row, settings),
            "enabled": row.admin_up,
            "description": effective_interface_description(row, settings),
            "label": row.label,
            "mtu": row.mtu,
        }
        if interface is not None and interface.name != row.name:
            values["name"] = row.name
        if row.mode in {"access", "trunk", "tagged-all"}:
            values["mode"] = {
                "access": "access",
                "trunk": "tagged",
                "tagged-all": "tagged-all",
            }[row.mode]
        if parent:
            values["parent"] = parent
        if bridge:
            values["bridge"] = bridge
        if lag:
            values["lag"] = lag
        if interface is None:
            interface = Interface.objects.create(device=device, name=row.name, **values)
            result.interfaces_created += 1
            result.created_objects.append(interface)
        else:
            update_fields(interface, values, result)
            result.interfaces_updated += 1
        interfaces[row.name] = interface
        sync_interface_vlans(interface, row, result)
        record_synced_object(result, interface)
        if settings.sync_mac_addresses and valid_mac(row.mac_address):
            sync_mac(interface, row.mac_address, result)
    return interfaces


def _legacy_meraki_interface_name(name, settings):
    """Znajdź nazwę zapisaną przed ujednoliceniem z Device Type Library."""
    if settings is None or settings.__class__.__name__ != "MerakiConfig":
        return ""
    normalized = str(name or "").casefold()
    aliases = {
        "internet 1": "WAN 1",
        "internet 2": "WAN 2",
        "singlelan": "SingleLan",
        "port 2": "port2",
        "port 3": "port3",
        "port 4": "port4",
        "port 5": "port5",
    }
    return aliases.get(normalized, "")


def syncable_interface_rows(rows, settings, config=None, selected_names=None):
    """Wybierz porty według Settings, ustawień urządzenia albo jawnej listy."""
    if not settings.sync_interfaces:
        return []

    selected = []
    for row in rows:
        if not getattr(row, "present", True):
            # Port zachowujemy w historii cache, ale nie wolno go wysłać do Apply,
            # jeśli ostatnie odświeżenie nie zwróciło go ze źródła.
            continue
        if settings.ignore_disabled_interfaces and not row.admin_up:
            # Globalne ustawienie ma pierwszeństwo przed wyborem pojedynczego portu.
            continue
        if not interface_is_selected(
            row,
            settings,
            config=config,
            selected_names=selected_names,
        ):
            continue
        selected.append(row)
    return selected


def filter_collected_data(data, settings, config=None, selected_names=None):
    """Pozostaw w snapshotcie wyłącznie interfejsy wybrane do synchronizacji."""
    selected = syncable_interface_rows(
        data.interfaces,
        settings,
        config=config,
        selected_names=selected_names,
    )
    selected_names = {row.name for row in selected}

    # Modyfikujemy DTO przed jego serializacją do SyncRun.source_data. Dzięki temu
    # tabela Preview i późniejszy Apply korzystają z dokładnie tego samego zestawu.
    data.interfaces = selected
    data.vrrp_groups = [
        row for row in data.vrrp_groups
        if row.interface_name in selected_names
    ]
    return data


def selected_interface_names(rows, settings, config=None):
    """Zwróć nazwy portów zaznaczonych według zapisanej konfiguracji urządzenia."""
    return [
        row.name
        for row in syncable_interface_rows(rows, settings, config=config)
        if row.name
    ]


def interface_is_selected(row, settings, config=None, selected_names=None):
    """Rozstrzygnij checkbox portu, zachowując ignored jako wartość domyślną."""
    name = str(getattr(row, "name", "") or "")
    if selected_names is not None:
        normalized_selected = {
            str(value).casefold()
            for value in selected_names
        }
        return name.casefold() in normalized_selected

    cached_selection = getattr(row, "selected", None)
    if cached_selection is not None:
        return bool(cached_selection)

    overrides = getattr(config, "interface_selection", {}) or {}
    normalized_name = name.casefold()
    if normalized_name in overrides:
        return bool(overrides[normalized_name])

    # Reguły DEFAULT_PLUGIN_SETTINGS nie usuwają już danych z kolektora. Określają
    # jedynie początkowy stan checkboxa dla portu bez ręcznej decyzji.
    return not ignored_system_interface(row, settings)


def ignored_system_interface(row, settings=None):
    """Rozpoznaj interfejs domyślnie odznaczony dla właściwego źródła."""
    name = (getattr(row, "name", "") or "").casefold()
    mac_address = getattr(row, "mac_address", "")

    # Zerowy MAC identyfikuje operacyjne tunele raportujące adres portu WAN.
    # Pominięcie całego interfejsu zapobiega dublowaniu WAN w modelu NetBox.
    if zero_mac(mac_address):
        return True
    # NVI0 oraz vmanage_system są wewnętrznymi interfejsami raportowanymi przez
    # warstwę SD-WAN i nie reprezentują portów, które chcemy utrzymywać w NetBox.
    if name in configured_ignored_interface_names(settings):
        return True
    # Pełne dopasowanie chroni podobnie nazwane interfejsy przed pominięciem.
    if any(pattern.fullmatch(name) for pattern in configured_ignored_interface_patterns(settings)):
        return True
    return False


def configured_ignored_interface_names(settings=None):
    """Zwróć nazwy ignorowane dla wskazanego źródła; bez źródła użyj vManage."""
    source = settings or type("VmanageSettings", (), {})()
    return {str(value).casefold() for value in platform_plugin_setting(source, "ignored_interface_names")}


def configured_ignored_interface_patterns(settings=None):
    """Skompiluj wzorce wykluczeń właściwe dla wskazanego źródła."""
    source = settings or type("VmanageSettings", (), {})()
    return tuple(
        re.compile(str(pattern).casefold())
        for pattern in platform_plugin_setting(source, "ignored_interface_patterns")
    )


def sync_mac(interface, value, result):
    """Dodaj nieistniejący MAC i ustaw go jako primary MAC wolnego interfejsu."""
    from dcim.models import MACAddress

    # MAC może już należeć do innego interfejsu, ponieważ fizyczny port oraz
    # subinterfejs bywają raportowane przez vManage z tym samym adresem.
    mac = MACAddress.objects.filter(mac_address=value).first()
    if mac is None:
        content_type = ContentType.objects.get_for_model(interface)
        mac = MACAddress.objects.create(
            mac_address=value,
            assigned_object_type=content_type,
            assigned_object_id=interface.pk,
        )
        result.macs_created += 1
        result.created_objects.append(mac)
    record_synced_object(result, mac)
    if hasattr(interface, "primary_mac_id") and interface.primary_mac_id is None:
        interface.primary_mac = mac
        interface.save(update_fields=("primary_mac",))


def interface_type(row, settings=None):
    """Mapuj typ i szybkość źródła na prawidłową wartość choices NetBox."""
    name = row.name.casefold()
    kind = row.interface_type.casefold()
    if kind == "lag" or re.fullmatch(r"(?:port-?channel|po)\d+", name):
        return "lag"
    if kind == "cisco-stackwise":
        return "cisco-stackwise"
    if kind == "bridge":
        return "bridge"
    if any(token in name for token in ("loopback", "tunnel", "vmanage_system", "sdwan-system")):
        return "virtual"
    if (
        "." in row.name
        or name.startswith("vlan")
        or "virtual" in kind
        or "loopback" in kind
        or "tunnel" in kind
    ):
        return "virtual"
    speed = row.speed_mbps or 0
    if settings is not None and settings.__class__.__name__ == "MerakiConfig":
        # Meraki raportuje kilka prędkości pośrednich, których nie wolno
        # zaokrąglać progowo do 1G albo 10G.
        speed_map = platform_plugin_setting(settings, "speed_to_interface_type")
        exact_type = speed_map.get(speed) or speed_map.get(str(int(speed))) if speed else None
        if exact_type:
            return exact_type
        if row.interface_type:
            return row.interface_type
    if (
        settings is not None
        and settings.__class__.__name__ == "CatalystCenterConfig"
        and kind in NOMINAL_INTERFACE_SPEEDS_MBPS
    ):
        return kind
    if speed >= 100000:
        return "100gbase-x-qsfp28"
    if speed >= 40000:
        return "40gbase-x-qsfpp"
    if speed >= 10000:
        return "10gbase-t"
    if speed >= 1000:
        return "1000base-t"
    if speed >= 100:
        return "100base-tx"
    return "other"


def valid_mac(value):
    """Odrzuć brakujące, niepełne i zerowe adresy MAC."""
    compact = compact_mac(value)
    return len(compact) == 12 and not zero_mac(value)


def zero_mac(value):
    """Rozpoznaj pełny zerowy MAC niezależnie od separatora i wielkości liter."""
    return compact_mac(value) == "000000000000"


def compact_mac(value):
    """Sprowadź zapis MAC do dwunastu znaków używanych przez walidatory."""
    return (value or "").lower().replace(":", "").replace("-", "")
