"""Widoki inventory, Preview, Apply i Discovery platformy vManage."""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render
from django.views.generic import View

from netbox.object_actions import BulkDelete, BulkExport
from netbox.views import generic
from utilities.views import register_model_view

from .. import filtersets, forms, tables
from ..jobs import (
    BULK_JOB_NAME,
    VMANAGE_INTERFACE_REFRESH_JOB_NAME,
    SCHEDULED_JOB_NAME,
    SCHEDULED_JOB_BLOCKING_STATUSES,
    BulkVmanageSyncJob,
    BulkVmanageInterfaceRefreshJob,
    active_sync_job,
    enabled_configs,
)
from ..models import DeviceVmanageConfig, VmanageSyncConfig
from ..services import collect_config_details, discover_devices

from .common import (
    BulkApplySelectedAction,
    BulkApplySelectedView,
    BulkInterfaceRefreshView,
    BulkRefreshInterfacesAction,
    CombinedDeviceSyncEditView,
    DeviceConfigToggleEnabledView,
    DeviceEditRedirectView,
)


@register_model_view(DeviceVmanageConfig, name="list", path="", detail=False)
class DeviceVmanageConfigListView(generic.ObjectListView):
    """Lista discovery z mapowaniem vManage Edge do NetBox Site i Device."""
    queryset = DeviceVmanageConfig.objects.select_related("netbox_site", "device")
    table = tables.DeviceVmanageConfigTable
    filterset = filtersets.DeviceVmanageConfigFilterSet
    template_name = "netbox_cisco_sync/devicevmanageconfig_list.html"
    extra_context = {"discovered_source": "vmanage"}
    # Inventory powstaje wyłącznie przez discovery. Nie udostępniamy ręcznego
    # dodawania, importu, zmiany nazw ani masowej edycji rekordów źródłowych.
    actions = (
        BulkRefreshInterfacesAction,
        BulkApplySelectedAction,
        BulkExport,
        BulkDelete,
    )


@register_model_view(DeviceVmanageConfig, name="bulk_refresh_interfaces", path="refresh-interfaces", detail=False)
class BulkVmanageInterfaceRefreshView(BulkInterfaceRefreshView):
    model = DeviceVmanageConfig
    filterset_class = filtersets.DeviceVmanageConfigFilterSet
    job_class = BulkVmanageInterfaceRefreshJob
    job_name = VMANAGE_INTERFACE_REFRESH_JOB_NAME
    permission_name = "netbox_cisco_sync.change_devicevmanageconfig"
    source_name = "vManage"
    list_url_name = "plugins:netbox_cisco_sync:devicevmanageconfig_list"


@register_model_view(DeviceVmanageConfig, name="bulk_apply_selected", path="apply-selected", detail=False)
class BulkVmanageApplySelectedView(BulkApplySelectedView):
    model = DeviceVmanageConfig
    filterset_class = filtersets.DeviceVmanageConfigFilterSet
    eligible_queryset = staticmethod(enabled_configs)
    job_class = BulkVmanageSyncJob
    job_name = BULK_JOB_NAME
    competing_job_names = (SCHEDULED_JOB_NAME,)
    competing_job_statuses = SCHEDULED_JOB_BLOCKING_STATUSES
    permission_name = "netbox_cisco_sync.change_devicevmanageconfig"
    source_name = "vManage"
    list_url_name = "plugins:netbox_cisco_sync:devicevmanageconfig_list"


class BulkVmanageSyncView(LoginRequiredMixin, View):
    """Potwierdź i zakolejkuj Apply wszystkich włączonych urządzeń."""
    template_name = "netbox_cisco_sync/bulk_sync_confirm.html"

    def get(self, request):
        if not request.user.has_perm("netbox_cisco_sync.change_devicevmanageconfig"):
            messages.error(request, "You do not have permission to run bulk vManage sync.")
            return redirect("plugins:netbox_cisco_sync:devicevmanageconfig_list")
        return render(request, self.template_name, {"device_count": enabled_configs().count()})

    def post(self, request):
        if not request.user.has_perm("netbox_cisco_sync.change_devicevmanageconfig"):
            messages.error(request, "You do not have permission to run bulk vManage sync.")
            return redirect("plugins:netbox_cisco_sync:devicevmanageconfig_list")

        device_count = enabled_configs().count()
        if device_count == 0:
            messages.warning(request, "No enabled vManage devices with a NetBox Site mapping.")
            return redirect("plugins:netbox_cisco_sync:devicevmanageconfig_list")

        # Nie kolejkujemy drugiej identycznej serii, ponieważ równoległe Apply mogłyby
        # ścigać się podczas tworzenia tych samych urządzeń, interfejsów i adresów IP.
        # Systemowy scheduler pozostaje w NetBox ze statusem ``scheduled`` nawet
        # przy interwale 0. Blokuje bulk wyłącznie wtedy, gdy naprawdę już działa.
        active_job = active_sync_job(BULK_JOB_NAME) or active_sync_job(
            SCHEDULED_JOB_NAME,
            statuses=SCHEDULED_JOB_BLOCKING_STATUSES,
        )
        if active_job:
            messages.warning(request, "A vManage sync job is already queued or running.")
            return redirect(active_job.get_absolute_url())

        job = BulkVmanageSyncJob.enqueue(user=request.user)
        messages.success(request, f"Queued Sync and Apply for {device_count} enabled device(s).")
        return redirect(job.get_absolute_url())


@register_model_view(DeviceVmanageConfig)
class DeviceVmanageConfigView(DeviceEditRedirectView):
    """Przekieruj stronę szczegółów vManage do połączonej edycji i Preview."""

    model = DeviceVmanageConfig


@register_model_view(DeviceVmanageConfig, name="edit")
class DeviceVmanageConfigEditView(CombinedDeviceSyncEditView):
    model = DeviceVmanageConfig
    form_class = forms.DeviceVmanageConfigForm
    settings_model = VmanageSyncConfig
    permission_name = "netbox_cisco_sync.change_devicevmanageconfig"
    run_field = "config"
    source_name = "vManage"
    source_key = "vmanage"
    list_url_name = "plugins:netbox_cisco_sync:devicevmanageconfig_list"
    delete_url_name = "plugins:netbox_cisco_sync:devicevmanageconfig_delete"

    def collect_full_data(self, config, settings, *, force_refresh=False):
        return collect_config_details(
            config,
            settings=settings,
            include_unselected=True,
            force_refresh=force_refresh,
        )

    def source_context(self, config):
        return {
            "source_site_label": "vManage Site",
            "source_site_name": config.vmanage_site_name,
            "source_identifier_label": "vManage Site ID",
            "source_identifier": config.vmanage_site_id,
            "source_management_ip": config.system_ip,
        }


@register_model_view(DeviceVmanageConfig, name="delete")
class DeviceVmanageConfigDeleteView(generic.ObjectDeleteView):
    """Usuń wyłącznie rekord discovery vManage, nie powiązane urządzenie NetBox."""
    queryset = DeviceVmanageConfig.objects.all()


@register_model_view(DeviceVmanageConfig, name="bulk_delete", detail=False)
class DeviceVmanageConfigBulkDeleteView(generic.BulkDeleteView):
    """Zbiorczo usuń zaznaczone rekordy inventory vManage."""
    queryset = DeviceVmanageConfig.objects.all()
    table = tables.DeviceVmanageConfigTable


@register_model_view(DeviceVmanageConfig, name="toggle_enabled", path="toggle-enabled")
class DeviceVmanageConfigToggleEnabledView(DeviceConfigToggleEnabledView):
    model = DeviceVmanageConfig
    permission_name = "netbox_cisco_sync.change_devicevmanageconfig"
    source_name = "vManage"
    list_url_name = "plugins:netbox_cisco_sync:devicevmanageconfig_list"


class DiscoverDevicesView(LoginRequiredMixin, View):
    """Ręczna akcja odświeżająca lekkie inventory z /dataservice/device."""
    def get(self, request):
        return self.post(request)

    def post(self, request):
        if not request.user.has_perm("netbox_cisco_sync.change_devicevmanageconfig"):
            messages.error(request, "You do not have permission to run vManage discovery.")
            return redirect("plugins:netbox_cisco_sync:devicevmanageconfig_list")
        # Błąd API pokazujemy jako komunikat, ale nie czyścimy poprzedniego inventory.
        try:
            result = discover_devices()
            messages.success(
                request,
                f"vManage discovery: {result['seen']} Edge device(s), {result['created']} created, "
                f"{result['updated']} refreshed.",
            )
        except Exception as exc:  # noqa: BLE001 - użytkownik musi zobaczyć błąd API.
            messages.error(request, f"vManage discovery failed: {exc}")
        return redirect("plugins:netbox_cisco_sync:devicevmanageconfig_list")


@register_model_view(DeviceVmanageConfig, name="sync", path="sync")
class DeviceVmanageConfigSyncView(DeviceEditRedirectView):
    model = DeviceVmanageConfig
