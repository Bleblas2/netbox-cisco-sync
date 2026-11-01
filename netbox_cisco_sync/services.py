"""Operacje aplikacyjne współdzielone przez widoki UI oraz zadania NetBox."""

from django.utils import timezone

from dcim.models import Site

from .choices import MatchMethodChoices
from .connectors.vmanage import VmanageConnector
from .matcher import match_site, site_prefix_bindings
from .models import DeviceVmanageConfig, VmanageSyncConfig
from .interface_cache import collect_cached_config


def discover_devices():
    """Odśwież inventory Edge bez nadpisywania ręcznych mapowań i pola enabled."""
    settings = VmanageSyncConfig.get()
    if not settings.enabled:
        raise RuntimeError("vManage integration is disabled in Settings.")
    connector = VmanageConnector(settings).connect()
    devices = connector.collect_inventory()
    # Site pobieramy raz. Dopasowanie wielu urządzeń nie powinno wykonywać osobnego
    # zapytania do bazy dla każdego Edge.
    sites = list(Site.objects.all())
    prefix_bindings = site_prefix_bindings(sites)
    created = updated = 0

    for device in devices:
        # system-ip jest stabilnym kluczem odpowiedzi /dataservice/device i dlatego
        # identyfikuje zapisany rekord discovery.
        config = DeviceVmanageConfig.objects.filter(system_ip=device.system_ip).first()
        is_new = config is None
        if is_new:
            config = DeviceVmanageConfig(system_ip=device.system_ip, hostname=device.hostname)

        config.vmanage_uuid = device.uuid
        config.hostname = device.hostname
        config.serial_number = device.serial_number
        config.device_model = device.model
        config.vmanage_site_id = device.site_id
        config.vmanage_site_name = device.site_name
        config.latitude = device.latitude
        config.longitude = device.longitude
        config.device_groups = device.device_groups
        config.reachability = device.reachability
        config.last_discovered = timezone.now()

        # Ręczny wybór administratora zawsze ma pierwszeństwo nad kolejnym discovery.
        if not config.manual_site_override:
            site, method = match_site(
                device,
                sites,
                settings.gps_max_distance_km,
                prefix_bindings=prefix_bindings,
            )
            config.netbox_site = site
            config.match_method = method
        elif config.netbox_site_id:
            config.match_method = MatchMethodChoices.MANUAL

        config.save()
        created += int(is_new)
        updated += int(not is_new)

    return {"seen": len(devices), "created": created, "updated": updated}


def vmanage_inventory_dto(config):
    """Odtwórz podstawowe DTO vManage bez wykonywania połączenia do API."""
    from .dto import CollectedDevice

    return CollectedDevice(
        system_ip=str(config.system_ip),
        hostname=config.hostname,
        uuid=config.vmanage_uuid,
        serial_number=config.serial_number,
        model=config.device_model,
        site_id=config.vmanage_site_id,
        site_name=config.vmanage_site_name,
        latitude=float(config.latitude) if config.latitude is not None else None,
        longitude=float(config.longitude) if config.longitude is not None else None,
        device_groups=list(config.device_groups or []),
        reachability=config.reachability,
    )


def collect_config_details(
    config,
    *,
    client=None,
    settings=None,
    include_unselected=False,
    force_refresh=False,
    refresh_missing=True,
):
    """Zwróć vManage DTO przez wspólny przepływ cache."""
    settings = settings or VmanageSyncConfig.get()
    if not settings.enabled:
        raise RuntimeError("vManage integration is disabled in Settings.")
    data = vmanage_inventory_dto(config)

    def collect():
        """Odpytaj connector wyłącznie przy jawnym odświeżeniu lub pustym cache."""
        connector = VmanageConnector(settings, client=client) if client else VmanageConnector(settings).connect()
        return connector.collect_device(data)

    return collect_cached_config(
        config, data, settings, collect, include_unselected=include_unselected,
        force_refresh=force_refresh, refresh_missing=refresh_missing,
    )
