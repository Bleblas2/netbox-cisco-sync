"""Application services for Catalyst Center discovery and collection."""

from django.utils import timezone

from dcim.models import Site

from .choices import MatchMethodChoices
from .connectors.catalyst_center import CatalystCenterConnector
from .connectors.catalyst_center.collector import parse_device
from .matcher import match_site, site_prefix_bindings
from .models import CatalystCenterConfig, DeviceCatalystCenterConfig
from .interface_cache import collect_cached_config


def discover_catalyst_devices():
    settings = CatalystCenterConfig.get()
    if not settings.enabled:
        raise RuntimeError("Catalyst Center integration is disabled in Settings.")
    devices = CatalystCenterConnector(settings).connect().collect_inventory()
    sites = list(Site.objects.all())
    prefix_bindings = site_prefix_bindings(sites)
    created = updated = 0
    for row in devices:
        config = DeviceCatalystCenterConfig.objects.filter(catalyst_id=row.uuid).first()
        is_new = config is None
        if is_new:
            config = DeviceCatalystCenterConfig(catalyst_id=row.uuid, hostname=row.hostname)
        config.management_ip = row.system_ip or None
        config.hostname = row.hostname
        config.serial_number = row.serial_number
        config.switch_stack_serials = list(row.switch_stack_serials)
        config.switch_stack_info = list(row.switch_stack_info)
        config.device_model = row.model
        config.catalyst_site_id = row.site_id
        config.catalyst_site_name = row.site_name
        config.latitude = row.latitude
        config.longitude = row.longitude
        config.reachability = row.reachability
        config.catalyst_role = row.source_role
        config.catalyst_family = row.source_family
        config.last_discovered = timezone.now()
        if not config.manual_site_override:
            # ID Building z CCC nie jest identyfikatorem SdwanSiteId używanym przez
            # vManage, dlatego dla CCC stosujemy nazwę, a następnie odległość GPS.
            site, method = match_site(
                row,
                sites,
                settings.gps_max_distance_km,
                use_custom_field=False,
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


def catalyst_inventory_dto(config):
    """Odtwórz podstawowe DTO Catalyst Center zapisane podczas Discovery."""
    data = parse_device(
        {
            "id": config.catalyst_id,
            "hostname": config.hostname,
            "managementIpAddress": str(config.management_ip or ""),
            "serialNumber": config.serial_number,
            "serialNumbers": [config.serial_number, *config.switch_stack_serials],
            "stackSwitchInfo": config.switch_stack_info,
            "platformId": config.device_model,
            "reachabilityStatus": config.reachability,
            "role": config.catalyst_role,
            "family": config.catalyst_family,
        },
        {
            "id": config.catalyst_site_id,
            "name": config.catalyst_site_name,
            "latitude": float(config.latitude) if config.latitude is not None else None,
            "longitude": float(config.longitude) if config.longitude is not None else None,
        },
    )
    return data


def collect_catalyst_config(
    config,
    *,
    settings=None,
    include_unselected=False,
    force_refresh=False,
    refresh_missing=True,
):
    """Zwróć Catalyst Center DTO przez wspólny przepływ cache."""
    settings = settings or CatalystCenterConfig.get()
    data = catalyst_inventory_dto(config)

    def collect():
        """Odpytaj connector wyłącznie przy jawnym odświeżeniu lub pustym cache."""
        connector = CatalystCenterConnector(settings).connect()
        return connector.collect_device(data)

    return collect_cached_config(
        config, data, settings, collect, include_unselected=include_unselected,
        force_refresh=force_refresh, refresh_missing=refresh_missing,
    )
