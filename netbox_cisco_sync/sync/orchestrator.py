"""Orkiestracja Preview i Apply dla pojedynczego urządzenia Edge."""

from django.utils.text import slugify

from ..plugin_settings import plugin_setting
from .addresses import candidate_ip_rows, sync_addresses
from .device_custom_fields import sync_switch_stack_fields
from .fhrp import sync_fhrp
from .interfaces import sync_interfaces, syncable_interface_rows, valid_mac
from .result import SyncResult, record_synced_object, update_fields
from .sites import sync_site_meraki_id, sync_site_sdwan_id
from .tags import tag_synced_objects

DEFAULT_PLATFORM_NAME = plugin_setting("vmanage_default_platform_name")
DEFAULT_PLATFORM_SLUG = plugin_setting("vmanage_default_platform_slug")
NETBOX_DEVICE_SERIAL_MAX_LENGTH = 50


def netbox_device_serial(value):
    """Skróć źródłowy serial do limitu pola dcim.Device.serial."""
    return str(value or "")[:NETBOX_DEVICE_SERIAL_MAX_LENGTH]


def sync_collected_device(config, data, settings, *, apply=False):
    """Porównaj albo zapisz jeden Edge; Site jest obowiązkowy."""
    from dcim.models import Device

    result = SyncResult()
    # Samo wykrycie Edge, w szczególności huba, nie może spowodować zapisu.
    if not config.enabled:
        result.skipped = True
        result.warnings.append("Device is disabled in Device vManage Config")
        return result, None
    if not config.netbox_site_id:
        result.skipped = True
        result.warnings.append("No NetBox Site mapping")
        return result, None

    # Identyfikacja: przypisany Site i nazwa, a serial jest fallbackiem oraz
    # zabezpieczeniem przed przeniesieniem urządzenia między Site.
    device = Device.objects.filter(
        site=config.netbox_site,
        name__iexact=data.hostname,
    ).first()
    device_serial = netbox_device_serial(data.serial_number)
    if len(str(data.serial_number or "")) > NETBOX_DEVICE_SERIAL_MAX_LENGTH:
        result.warnings.append("Source serial number was truncated to 50 characters for NetBox")
    if device is None and device_serial:
        serial_match = Device.objects.filter(serial=device_serial).first()
        if serial_match and serial_match.site_id != config.netbox_site_id:
            result.skipped = True
            result.warnings.append(
                f"Serial number already belongs to {serial_match} in another Site"
            )
            return result, serial_match
        device = serial_match

    if device is not None and not settings.update_existing:
        result.skipped = True
        result.warnings.append("Skipped: update existing disabled")
        return result, device

    if not apply:
        build_preview_result(result, device, data, settings, config=config)
        return result, device

    _, device_type, role, platform = ensure_device_prerequisites(
        data.model,
        data.role_name or settings.default_device_role,
        result,
        platform_name=data.platform_name or plugin_setting("vmanage_default_platform_name"),
        platform_slug=data.platform_slug or plugin_setting("vmanage_default_platform_slug"),
        part_number=data.device_type_part_number,
        require_existing_device_type=data.require_existing_device_type,
    )
    if device is None:
        device = Device.objects.create(
            name=data.hostname,
            serial=device_serial,
            device_type=device_type,
            role=role,
            platform=platform,
            site=config.netbox_site,
            status=data.status or "active",
        )
        result.devices_created += 1
        result.created_objects.append(device)
    else:
        update_fields(
            device,
            {
                "serial": device_serial,
                "device_type": device_type,
                "platform": platform,
                "status": data.status or "active",
            },
            result,
        )
        result.devices_updated += 1
    record_synced_object(result, device)
    if hasattr(config, "catalyst_id"):
        sync_switch_stack_fields(device, data, result)

    # Kolejność: Device -> interfejsy/MAC -> zwykłe IP -> grupa FHRP ->
    # członkostwo interfejsu -> VIP.
    interfaces = sync_interfaces(
        device,
        data.interfaces,
        settings,
        result,
        config=config,
    )
    ip_by_text = sync_addresses(device, interfaces, data, settings, result)
    # Nie każde źródło udostępnia FHRP; brak przełącznika oznacza wyłączenie.
    if getattr(settings, "sync_fhrp", False):
        sync_fhrp(interfaces, data, ip_by_text, settings, result)

    # Dopiero zaakceptowany Apply synchronizuje identyfikator Site właściwy dla
    # źródła. Istniejąca wartość jest chroniona bez opcji Update existing.
    if hasattr(config, "vmanage_site_id"):
        sync_site_sdwan_id(config, settings, result)
    elif hasattr(config, "network_id"):
        sync_site_meraki_id(config, settings, result)

    # Tagi z Settings trafiają na obiekty nowe i istniejące objęte Apply.
    tag_synced_objects(
        [*result.created_objects, *result.synced_objects],
        settings.tags.all(),
    )
    config.device = device
    return result, device


def build_preview_result(result, device, data, settings, config=None):
    """Wypełnij liczniki Preview bez wykonywania zapisów ORM."""
    interface_rows = syncable_interface_rows(
        data.interfaces,
        settings,
        config=config,
    )
    interface_names = {row.name for row in interface_rows if row.name}
    result.devices_created = int(device is None)
    result.devices_updated = int(device is not None)
    result.interfaces_created = len(interface_names)
    result.ips_created = len(candidate_ip_rows(interface_rows))
    result.macs_created = len({
        row.mac_address.lower()
        for row in interface_rows
        if valid_mac(row.mac_address)
    })
    result.fhrp_groups_created = len({
        (row.interface_name, row.group_id)
        for row in data.vrrp_groups
        if row.interface_name in interface_names and row.virtual_ip
    })


def ensure_device_prerequisites(
    model_name,
    role_name,
    result,
    *,
    platform_name=None,
    platform_slug=None,
    part_number="",
    require_existing_device_type=False,
):
    """Zapewnij producenta, rolę, DeviceType i platformę przed Device."""
    from dcim.models import DeviceRole, DeviceType, Manufacturer, Platform

    manufacturer, created = Manufacturer.objects.get_or_create(
        name="Cisco",
        defaults={"slug": "cisco"},
    )
    if created:
        result.created_objects.append(manufacturer)
    role, created = DeviceRole.objects.get_or_create(
        name=role_name,
        defaults={"slug": slugify(role_name)},
    )
    if created:
        result.created_objects.append(role)
    # Platformę identyfikujemy po stałym slugu, aby wszystkie urządzenia z vManage
    # korzystały z jednego obiektu niezależnie od konkretnego modelu sprzętu.
    platform_name = platform_name or plugin_setting("vmanage_default_platform_name")
    platform_slug = platform_slug or plugin_setting("vmanage_default_platform_slug")
    platform, created = Platform.objects.get_or_create(
        slug=platform_slug,
        defaults={
            "name": platform_name,
            "manufacturer": manufacturer,
        },
    )
    if created:
        result.created_objects.append(platform)
    model_name = model_name or "Cisco SD-WAN Edge"
    if require_existing_device_type:
        device_type = DeviceType.objects.get(part_number=part_number or model_name)
        created = False
    else:
        device_type, created = DeviceType.objects.get_or_create(
            manufacturer=manufacturer,
            model=model_name,
            defaults={"slug": slugify(model_name)[:100]},
        )
    if created:
        result.created_objects.append(device_type)
    return manufacturer, device_type, role, platform
