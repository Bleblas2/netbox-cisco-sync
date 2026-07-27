"""Operacje discovery i odtwarzania danych urządzeń Cisco Meraki."""

from django.utils import timezone
from dcim.models import Site

from .choices import MatchMethodChoices
from .connectors.meraki import MerakiConnector
from .dto import CollectedDevice
from .matcher import match_site
from .models import DeviceMerakiConfig, MerakiConfig
from .sync.interfaces import filter_collected_data
from .interface_cache import (
    collected_device_from_cache,
    has_interface_cache,
    refresh_interface_cache,
)


def discover_meraki_devices():
    """Odśwież inventory Meraki bez nadpisywania ręcznych mapowań i enabled."""
    settings = MerakiConfig.get()
    if not settings.enabled:
        raise RuntimeError("Meraki integration is disabled in Settings.")
    devices = MerakiConnector(settings).connect().collect_inventory()
    sites = list(Site.objects.all())
    created = updated = 0
    for row in devices:
        config = DeviceMerakiConfig.objects.filter(serial_number=row.serial_number).first()
        is_new = config is None
        if is_new:
            config = DeviceMerakiConfig(serial_number=row.serial_number, hostname=row.hostname)
        config.hostname = row.hostname
        config.device_model = row.model
        config.product_family = row.source_family
        config.network_id = row.site_id
        config.network_name = row.site_name
        config.management_ip = row.system_ip or None
        config.latitude = row.latitude
        config.longitude = row.longitude
        config.last_discovered = timezone.now()
        if not config.manual_site_override:
            # Meraki Network nie ma pola SdwanSiteId; dopasowujemy nazwą, potem GPS.
            site, method = match_site(row, sites, settings.gps_max_distance_km, use_custom_field=False)
            config.netbox_site = site
            config.match_method = method
        elif config.netbox_site_id:
            config.match_method = MatchMethodChoices.MANUAL
        config.save()
        created += int(is_new)
        updated += int(not is_new)
    return {"seen": len(devices), "created": created, "updated": updated}


def meraki_inventory_dto(config):
    """Odtwórz lekki DTO zapisany przez discovery do późniejszego Preview."""
    return CollectedDevice(
        system_ip=str(config.management_ip or ""), hostname=config.hostname,
        uuid=config.serial_number, serial_number=config.serial_number,
        model=config.device_model, site_id=config.network_id, site_name=config.network_name,
        latitude=float(config.latitude) if config.latitude is not None else None,
        longitude=float(config.longitude) if config.longitude is not None else None,
        reachability="", role_name=MerakiConfig.get().default_device_role,
        platform_name="Cisco Meraki", platform_slug="cisco-meraki",
        device_type_part_number=config.device_model, source_family=config.product_family,
    )


def collect_meraki_config(
    config,
    *,
    client=None,
    settings=None,
    include_unselected=False,
    force_refresh=False,
):
    """Zwróć Meraki DTO z cache; API odpytaj tylko dla pustego cache lub Refresh."""
    settings = settings or MerakiConfig.get()
    if not settings.enabled:
        raise RuntimeError("Meraki integration is disabled in Settings.")
    base_data = meraki_inventory_dto(config)
    if force_refresh or not has_interface_cache(config):
        connector = (
            MerakiConnector(settings, client=client)
            if client
            else MerakiConnector(settings).connect()
        )
        collected = connector.collect_device(base_data)
        refresh_interface_cache(config, collected, settings)
        config.refresh_from_db()

    cached = collected_device_from_cache(
        config,
        base_data,
        selected_only=not include_unselected,
        include_absent=include_unselected,
    )
    if include_unselected:
        return cached
    return filter_collected_data(cached, settings, config=config)
