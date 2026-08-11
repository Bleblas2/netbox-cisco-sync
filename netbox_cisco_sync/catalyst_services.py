"""Application services for Catalyst Center discovery and collection."""

from django.db import transaction
from django.utils import timezone

from dcim.models import Site

from .choices import MatchMethodChoices
from .connectors.catalyst_center import CatalystCenterConnector
from .connectors.catalyst_center.collector import parse_device
from .dto import CollectedStackMember
from .matcher import match_site
from .models import CatalystCenterConfig, CatalystStackMember, DeviceCatalystCenterConfig
from .interface_cache import (
    collected_device_from_cache,
    has_interface_cache,
    refresh_interface_cache,
)


def discover_catalyst_devices():
    settings = CatalystCenterConfig.get()
    if not settings.enabled:
        raise RuntimeError("Catalyst Center integration is disabled in Settings.")
    devices = CatalystCenterConnector(settings).connect().collect_inventory()
    sites = list(Site.objects.all())
    created = updated = 0
    for row in devices:
        config = DeviceCatalystCenterConfig.objects.filter(catalyst_id=row.uuid).first()
        is_new = config is None
        if is_new:
            config = DeviceCatalystCenterConfig(catalyst_id=row.uuid, hostname=row.hostname)
        config.management_ip = row.system_ip or None
        config.hostname = row.hostname
        config.serial_number = row.serial_number
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
            )
            config.netbox_site = site
            config.match_method = method
        elif config.netbox_site_id:
            config.match_method = MatchMethodChoices.MANUAL
        config.save()
        _refresh_stack_members(config, row.stack_members)
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
    cached_members = [
        {
            "position": member.position,
            "serial_number": member.serial_number,
            "model": member.device_model,
        }
        for member in config.stack_members.filter(present=True).order_by("position")
    ]
    if cached_members:
        data.stack_members = [CollectedStackMember(**row) for row in cached_members]
    return data


def _refresh_stack_members(config, members):
    """Odśwież lokalny skład stacka, zachowując powiązania z Device."""
    seen = set()
    for member in members:
        seen.add(member.position)
        CatalystStackMember.objects.update_or_create(
            catalyst_config=config,
            position=member.position,
            defaults={
                "serial_number": member.serial_number,
                "device_model": member.model,
                "present": True,
            },
        )
    config.stack_members.exclude(position__in=seen).update(present=False)


def collect_catalyst_config(
    config,
    *,
    settings=None,
    include_unselected=False,
    force_refresh=False,
    refresh_missing=True,
):
    """Zwróć Catalyst DTO z cache zarządzanego przez wspólny interfejs Refresh."""
    from .sync.interfaces import filter_collected_data

    settings = settings or CatalystCenterConfig.get()
    base_data = catalyst_inventory_dto(config)
    cache_mode_changed = (
        has_interface_cache(config)
        and config.interfaces_stack_detailed != bool(settings.stack_detailed)
    )
    if cache_mode_changed and not force_refresh:
        raise RuntimeError(
            "Catalyst stack representation changed. Refresh interfaces before Preview or Apply."
        )
    if not has_interface_cache(config) and not (force_refresh or refresh_missing):
        raise RuntimeError(
            "Interface cache is empty. Refresh interfaces before Sync and Apply."
        )
    if force_refresh or not has_interface_cache(config):
        collected = CatalystCenterConnector(settings).connect().collect_device(base_data)
        with transaction.atomic():
            _refresh_stack_members(config, collected.stack_members)
            refresh_interface_cache(config, collected, settings)
        base_data.stack_members = list(collected.stack_members)
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
