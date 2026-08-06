"""Cykliczna synchronizacja i retencja historii zarejestrowane jako zadania NetBox."""

from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from core.choices import JobIntervalChoices
from netbox.jobs import JobRunner, system_job

from .choices import SyncModeChoices, SyncStatusChoices, SyncTriggerChoices
from .catalyst_services import collect_catalyst_config
from .meraki_services import collect_meraki_config
from .connectors.meraki import MerakiConnector
from .connectors.vmanage import VmanageConnector
from .engine import sync_collected_device
from .models import (
    CatalystCenterConfig,
    DeviceCatalystCenterConfig,
    DeviceVmanageConfig,
    DeviceMerakiConfig,
    MerakiConfig,
    SyncRun,
    VmanageSyncConfig,
    record_changes,
    record_created_objects,
)
from .services import collect_config_details, discover_devices

BULK_JOB_NAME = "Bulk vManage Sync and Apply"
VMANAGE_INTERFACE_REFRESH_JOB_NAME = "Bulk vManage Interface Refresh"
CATALYST_BULK_JOB_NAME = "Bulk Catalyst Center Sync and Apply"
CATALYST_INTERFACE_REFRESH_JOB_NAME = "Bulk Catalyst Center Interface Refresh"
MERAKI_BULK_JOB_NAME = "Bulk Meraki Sync and Apply"
MERAKI_INTERFACE_REFRESH_JOB_NAME = "Bulk Meraki Interface Refresh"
SCHEDULED_JOB_NAME = "Scheduled vManage Sync"
ACTIVE_JOB_STATUSES = ("pending", "scheduled", "running")
SCHEDULED_JOB_BLOCKING_STATUSES = ("running",)


def active_sync_job(*names, statuses=ACTIVE_JOB_STATUSES):
    """Znajdź aktywny job zapisujący dane vManage i zapobiegaj konkurencyjnemu Apply."""
    from core.models import Job

    return Job.objects.filter(
        name__in=names,
        status__in=statuses,
    ).order_by("-created").first()


def apply_config(config, settings, client, trigger, logger=None):
    """Zastosuj jeden Edge atomowo i zawsze zapisz osobny wynik Sync Run."""
    data = None
    try:
        data = collect_config_details(
            config, client=client, settings=settings, refresh_missing=False,
        )
        with transaction.atomic():
            result, device = sync_collected_device(config, data, settings, apply=True)
            run = SyncRun.objects.create(
                config=config, device=device, trigger=trigger,
                mode=SyncModeChoices.APPLY,
                status=SyncStatusChoices.SKIPPED if result.skipped else SyncStatusChoices.OK,
                devices_created=result.devices_created, devices_updated=result.devices_updated,
                interfaces_created=result.interfaces_created, interfaces_updated=result.interfaces_updated,
                ips_created=result.ips_created, macs_created=result.macs_created,
                fhrp_groups_created=result.fhrp_groups_created,
                message=result.message, source_data=data.to_dict(),
            )
            record_created_objects(run, result.created_objects)
            record_changes(run, result.changes)
            config.device = device
            config.last_sync_at = timezone.now()
            config.last_sync_status = run.status
            config.last_sync_message = result.message[:255]
            config.save(update_fields=("device", "last_sync_at", "last_sync_status", "last_sync_message"))
            return run.status
    except Exception as exc:  # noqa: BLE001 - błąd jednego Edge nie zatrzymuje całej serii.
        run = SyncRun.objects.create(
            config=config, trigger=trigger,
            mode=SyncModeChoices.APPLY, status=SyncStatusChoices.FAILED,
            message=str(exc), source_data=data.to_dict() if data is not None else {},
        )
        if logger:
            logger.error(f"{config}: {exc}")
        return run.status


def enabled_configs():
    """Zwróć deterministyczną listę włączonych Edge mających mapowanie Site."""
    return DeviceVmanageConfig.objects.filter(
        enabled=True,
        netbox_site__isnull=False,
    ).select_related("netbox_site", "device").order_by("hostname", "system_ip")


def enabled_catalyst_configs(settings=None):
    """Zwróć włączone urządzenia CCC zgodne z filtrem Family/Role i Site."""
    settings = settings or CatalystCenterConfig.get()
    queryset = DeviceCatalystCenterConfig.objects.filter(
        enabled=True,
        netbox_site__isnull=False,
    ).select_related("netbox_site", "device").order_by("hostname", "management_ip")
    allowed = [value.strip() for value in settings.import_device_roles.split(",") if value.strip()]
    if allowed:
        # Jedno pole Settings filtruje po dwóch niezależnych polach źródłowych.
        # Każda wartość rozdzielona przecinkiem działa jako alternatywa OR.
        role_filter = Q()
        for value in allowed:
            role_filter |= Q(catalyst_role__iexact=value) | Q(catalyst_family__iexact=value)
        queryset = queryset.filter(role_filter)
    return queryset


def apply_catalyst_config(config, settings, trigger, logger=None):
    """Zastosuj jeden lokalny snapshot CCC i zapisz audytowy Sync Run."""
    data = None
    try:
        # Apply celowo nie odpytuje kontrolera. Odczyt interfejsów jest osobną,
        # świadomą akcją użytkownika wykonywaną przed zatwierdzeniem snapshotu.
        data = collect_catalyst_config(
            config,
            settings=settings,
            refresh_missing=False,
        )
        with transaction.atomic():
            result, device = sync_collected_device(config, data, settings, apply=True)
            run = SyncRun.objects.create(
                catalyst_config=config, device=device, trigger=trigger,
                mode=SyncModeChoices.APPLY,
                status=SyncStatusChoices.SKIPPED if result.skipped else SyncStatusChoices.OK,
                devices_created=result.devices_created, devices_updated=result.devices_updated,
                interfaces_created=result.interfaces_created, interfaces_updated=result.interfaces_updated,
                ips_created=result.ips_created, macs_created=result.macs_created,
                fhrp_groups_created=result.fhrp_groups_created,
                message=result.message, source_data=data.to_dict(),
            )
            record_created_objects(run, result.created_objects)
            record_changes(run, result.changes)
            config.device = device
            config.last_sync_at = timezone.now()
            config.last_sync_status = run.status
            config.last_sync_message = result.message[:255]
            config.save(update_fields=("device", "last_sync_at", "last_sync_status", "last_sync_message"))
            return run.status
    except Exception as exc:  # noqa: BLE001 - błąd urządzenia nie zatrzymuje serii.
        SyncRun.objects.create(
            catalyst_config=config, trigger=trigger, mode=SyncModeChoices.APPLY,
            status=SyncStatusChoices.FAILED, message=str(exc),
            source_data=data.to_dict() if data is not None else {},
        )
        if logger:
            logger.error(f"{config}: {exc}")
        return SyncStatusChoices.FAILED


def enabled_meraki_configs(settings=None):
    """Zwróć włączone urządzenia Meraki zgodne z filtrem rodzin i mapowaniem Site."""
    settings = settings or MerakiConfig.get()
    queryset = DeviceMerakiConfig.objects.filter(
        enabled=True, netbox_site__isnull=False,
    ).select_related("netbox_site", "device").order_by("hostname", "serial_number")
    allowed = [value.strip() for value in settings.import_device_families.split(",") if value.strip()]
    if allowed:
        family_filter = Q()
        for value in allowed:
            family_filter |= Q(product_family__iexact=value)
        queryset = queryset.filter(family_filter)
    return queryset


def apply_meraki_config(config, settings, client, trigger, logger=None):
    """Zastosuj jeden snapshot Meraki i zapisz audytowy Sync Run."""
    data = None
    try:
        data = collect_meraki_config(
            config, client=client, settings=settings, refresh_missing=False,
        )
        with transaction.atomic():
            result, device = sync_collected_device(config, data, settings, apply=True)
            run = SyncRun.objects.create(
                meraki_config=config, device=device, trigger=trigger, mode=SyncModeChoices.APPLY,
                status=SyncStatusChoices.SKIPPED if result.skipped else SyncStatusChoices.OK,
                devices_created=result.devices_created, devices_updated=result.devices_updated,
                interfaces_created=result.interfaces_created, interfaces_updated=result.interfaces_updated,
                ips_created=result.ips_created, macs_created=result.macs_created,
                fhrp_groups_created=result.fhrp_groups_created,
                message=result.message, source_data=data.to_dict(),
            )
            record_created_objects(run, result.created_objects)
            record_changes(run, result.changes)
            config.device = device
            config.last_sync_at = timezone.now()
            config.last_sync_status = run.status
            config.last_sync_message = result.message[:255]
            config.save(update_fields=("device", "last_sync_at", "last_sync_status", "last_sync_message"))
            return run.status
    except Exception as exc:  # noqa: BLE001 - błąd urządzenia nie zatrzymuje serii.
        SyncRun.objects.create(
            meraki_config=config, trigger=trigger, mode=SyncModeChoices.APPLY,
            status=SyncStatusChoices.FAILED, message=str(exc),
            source_data=data.to_dict() if data is not None else {},
        )
        if logger:
            logger.error(f"{config}: {exc}")
        return SyncStatusChoices.FAILED


class BulkVmanageSyncJob(JobRunner):
    """Ręczny Apply wszystkich włączonych urządzeń, uruchamiany z listy UI."""
    class Meta:
        name = BULK_JOB_NAME

    def run(self, *args, **kwargs):
        settings = VmanageSyncConfig.get()
        if not settings.enabled:
            message = "vManage integration is disabled in Settings."
            self.logger.info(message)
            return message
        configs = enabled_configs()
        total = configs.count()
        if total == 0:
            message = "No enabled vManage devices with a NetBox Site mapping."
            self.logger.info(message)
            return message

        # Masowy Apply korzysta wyłącznie z wcześniej zatwierdzonego cache.
        client = None
        counts = {
            SyncStatusChoices.OK: 0,
            SyncStatusChoices.SKIPPED: 0,
            SyncStatusChoices.FAILED: 0,
        }
        for config in configs.iterator():
            status = apply_config(
                config,
                settings,
                client,
                SyncTriggerChoices.MANUAL,
                self.logger,
            )
            counts[status] += 1

        message = bulk_result_message(total, counts)
        self.logger.info(message)
        return message


class BulkVmanageInterfaceRefreshJob(JobRunner):
    """Odśwież cache zaznaczonych urządzeń vManage bez wykonywania Apply."""

    class Meta:
        name = VMANAGE_INTERFACE_REFRESH_JOB_NAME

    def run(self, *args, **kwargs):
        settings = VmanageSyncConfig.get()
        configs = DeviceVmanageConfig.objects.filter(pk__in=kwargs.get("config_ids", [])).order_by("hostname")
        return refresh_interface_configs(
            self, "vManage", configs,
            lambda config: collect_config_details(config, settings=settings, include_unselected=True, force_refresh=True),
        )


class BulkCatalystCenterSyncJob(JobRunner):
    """Ręczny Apply wszystkich włączonych urządzeń Catalyst Center."""

    class Meta:
        name = CATALYST_BULK_JOB_NAME

    def run(self, *args, **kwargs):
        settings = CatalystCenterConfig.get()
        if not settings.enabled:
            message = "Catalyst Center integration is disabled in Settings."
            self.logger.info(message)
            return message
        configs = enabled_catalyst_configs(settings)
        total = configs.count()
        counts = {
            SyncStatusChoices.OK: 0,
            SyncStatusChoices.SKIPPED: 0,
            SyncStatusChoices.FAILED: 0,
        }
        for config in configs.iterator():
            counts[apply_catalyst_config(config, settings, SyncTriggerChoices.MANUAL, self.logger)] += 1
        message = source_bulk_result_message("Catalyst Center", total, counts)
        self.logger.info(message)
        return message


class BulkCatalystCenterInterfaceRefreshJob(JobRunner):
    """Odśwież cache interfejsów zaznaczonych urządzeń bez wykonywania Apply."""

    class Meta:
        name = CATALYST_INTERFACE_REFRESH_JOB_NAME

    def run(self, *args, **kwargs):
        settings = CatalystCenterConfig.get()
        if not settings.enabled:
            message = "Catalyst Center integration is disabled in Settings."
            self.logger.info(message)
            return message
        config_ids = kwargs.get("config_ids") or []
        configs = DeviceCatalystCenterConfig.objects.filter(pk__in=config_ids).order_by(
            "hostname", "management_ip"
        )
        total = configs.count()
        refreshed = failed = 0
        for config in configs.iterator():
            try:
                collect_catalyst_config(
                    config,
                    settings=settings,
                    include_unselected=True,
                    force_refresh=True,
                )
                refreshed += 1
            except Exception as exc:  # noqa: BLE001 - awaria jednego urządzenia nie zatrzymuje serii.
                failed += 1
                self.logger.error(f"{config}: {exc}")
        message = (
            f"Catalyst Center interface refresh finished: {total} selected, "
            f"{refreshed} refreshed, {failed} failed. No changes were applied to NetBox devices."
        )
        self.logger.info(message)
        return message


class BulkMerakiSyncJob(JobRunner):
    """Ręczny Apply wszystkich włączonych urządzeń Meraki Dashboard."""

    class Meta:
        name = MERAKI_BULK_JOB_NAME

    def run(self, *args, **kwargs):
        settings = MerakiConfig.get()
        if not settings.enabled:
            message = "Meraki integration is disabled in Settings."
            self.logger.info(message)
            return message
        configs = enabled_meraki_configs(settings)
        total = configs.count()
        client = None
        counts = {SyncStatusChoices.OK: 0, SyncStatusChoices.SKIPPED: 0, SyncStatusChoices.FAILED: 0}
        for config in configs.iterator():
            status = apply_meraki_config(config, settings, client, SyncTriggerChoices.MANUAL, self.logger)
            counts[status] += 1
        message = source_bulk_result_message("Meraki", total, counts)
        self.logger.info(message)
        return message


class BulkMerakiInterfaceRefreshJob(JobRunner):
    """Odśwież cache zaznaczonych urządzeń Meraki bez wykonywania Apply."""

    class Meta:
        name = MERAKI_INTERFACE_REFRESH_JOB_NAME

    def run(self, *args, **kwargs):
        settings = MerakiConfig.get()
        configs = DeviceMerakiConfig.objects.filter(pk__in=kwargs.get("config_ids", [])).order_by("hostname")
        return refresh_interface_configs(
            self, "Meraki", configs,
            lambda config: collect_meraki_config(config, settings=settings, include_unselected=True, force_refresh=True),
        )


def refresh_interface_configs(job, source_name, configs, collector):
    """Wspólnie odśwież zaznaczone cache i nie przerywaj serii po jednym błędzie."""
    total = configs.count()
    refreshed = failed = 0
    for config in configs.iterator():
        try:
            collector(config)
            refreshed += 1
        except Exception as exc:  # noqa: BLE001 - błąd jednego urządzenia nie zatrzymuje serii.
            failed += 1
            job.logger.error(f"{config}: {exc}")
    message = (
        f"{source_name} interface refresh finished: {total} selected, "
        f"{refreshed} refreshed, {failed} failed. No changes were applied to NetBox devices."
    )
    job.logger.info(message)
    return message


def bulk_result_message(total, counts):
    """Zbuduj jednoznaczne podsumowanie widoczne na stronie zakończonego joba."""
    return source_bulk_result_message("vManage", total, counts)


def source_bulk_result_message(source, total, counts):
    return (
        f"Bulk {source} sync finished: {total} device(s), "
        f"{counts[SyncStatusChoices.OK]} OK, "
        f"{counts[SyncStatusChoices.SKIPPED]} skipped, "
        f"{counts[SyncStatusChoices.FAILED]} failed."
    )


@system_job(interval=60)
class ScheduledVmanageSyncJob(JobRunner):
    """Co godzinę sprawdź, czy według Settings należy wykonać synchronizację."""
    class Meta:
        name = SCHEDULED_JOB_NAME

    def run(self, *args, **kwargs):
        settings = VmanageSyncConfig.get()
        if not settings.enabled or settings.sync_interval_hours <= 0:
            self.logger.info("Scheduled vManage sync is disabled.")
            return
        if active_sync_job(BULK_JOB_NAME):
            self.logger.info("Scheduled vManage sync skipped: bulk sync is active.")
            return

        # Przed synchronizacją odświeżamy inventory i automatyczne mapowania Site.
        # Ręczne mapowania pozostają chronione przez manual_site_override.
        discover_devices()
        cutoff = timezone.now() - timedelta(hours=settings.sync_interval_hours)
        configs = enabled_configs()
        configs = configs.filter(last_sync_at__isnull=True) | configs.filter(last_sync_at__lte=cutoff)
        client = None
        if configs.filter(interfaces_last_refreshed__isnull=True).exists():
            client = VmanageConnector(settings).connect().client
        # Każdy Edge ma własną transakcję i Sync Run. Awaria jednego urządzenia
        # nie wycofuje poprawnie zsynchronizowanych urządzeń z tej samej serii.
        for config in configs.distinct():
            apply_config(
                config,
                settings,
                client,
                SyncTriggerChoices.SCHEDULED,
                self.logger,
            )


@system_job(interval=JobIntervalChoices.INTERVAL_DAILY)
class PruneVmanageSyncRunsJob(JobRunner):
    """Codziennie usuń wyłącznie starą historię, nigdy obiekty infrastruktury."""
    class Meta:
        name = "Prune vManage Sync history"

    def run(self, *args, **kwargs):
        keep_days = VmanageSyncConfig.get().history_keep_days
        if keep_days > 0:
            deleted, _ = SyncRun.objects.filter(created__lt=timezone.now() - timedelta(days=keep_days)).delete()
            self.logger.info(f"Pruned {deleted} old vManage sync history row(s).")
