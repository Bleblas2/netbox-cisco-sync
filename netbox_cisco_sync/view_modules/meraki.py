"""Widoki inventory, Preview, Apply i Discovery platformy Meraki."""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render
from django.views.generic import View

from netbox.object_actions import BulkDelete, BulkExport
from netbox.views import generic
from utilities.views import register_model_view

from .. import filtersets, forms, tables
from ..jobs import (
    MERAKI_BULK_JOB_NAME,
    MERAKI_INTERFACE_REFRESH_JOB_NAME,
    BulkMerakiSyncJob,
    BulkMerakiInterfaceRefreshJob,
    active_sync_job,
    enabled_meraki_configs,
)
from ..models import DeviceMerakiConfig, MerakiConfig
from ..meraki_services import collect_meraki_config, discover_meraki_devices

from .common import (
    BulkApplySelectedAction,
    BulkApplySelectedView,
    BulkEnableSelectedAction,
    BulkEnableSelectedView,
    BulkInterfaceRefreshView,
    BulkRefreshInterfacesAction,
    CombinedDeviceSyncEditView,
    DeviceConfigToggleEnabledView,
    DeviceEditRedirectView,
)


@register_model_view(DeviceMerakiConfig, name="list", path="", detail=False)
class DeviceMerakiConfigListView(generic.ObjectListView):
    """Lista urządzeń wykrytych w organizacjach i sieciach Meraki."""
    queryset = DeviceMerakiConfig.objects.select_related("netbox_site", "device")
    table = tables.DeviceMerakiConfigTable
    filterset = filtersets.DeviceMerakiConfigFilterSet
    template_name = "netbox_cisco_sync/devicemerakiconfig_list.html"
    extra_context = {"discovered_source": "meraki"}
    actions = (
        BulkRefreshInterfacesAction,
        BulkApplySelectedAction,
        BulkEnableSelectedAction,
        BulkExport,
        BulkDelete,
    )


@register_model_view(DeviceMerakiConfig, name="bulk_refresh_interfaces", path="refresh-interfaces", detail=False)
class BulkMerakiInterfaceRefreshView(BulkInterfaceRefreshView):
    model = DeviceMerakiConfig
    filterset_class = filtersets.DeviceMerakiConfigFilterSet
    job_class = BulkMerakiInterfaceRefreshJob
    job_name = MERAKI_INTERFACE_REFRESH_JOB_NAME
    permission_name = "netbox_cisco_sync.change_devicemerakiconfig"
    source_name = "Meraki"
    list_url_name = "plugins:netbox_cisco_sync:devicemerakiconfig_list"


@register_model_view(DeviceMerakiConfig, name="bulk_apply_selected", path="apply-selected", detail=False)
class BulkMerakiApplySelectedView(BulkApplySelectedView):
    model = DeviceMerakiConfig
    filterset_class = filtersets.DeviceMerakiConfigFilterSet
    eligible_queryset = staticmethod(enabled_meraki_configs)
    job_class = BulkMerakiSyncJob
    job_name = MERAKI_BULK_JOB_NAME
    permission_name = "netbox_cisco_sync.change_devicemerakiconfig"
    source_name = "Meraki"
    list_url_name = "plugins:netbox_cisco_sync:devicemerakiconfig_list"


@register_model_view(DeviceMerakiConfig)
class DeviceMerakiConfigView(DeviceEditRedirectView):
    model = DeviceMerakiConfig


@register_model_view(DeviceMerakiConfig, name="edit")
class DeviceMerakiConfigEditView(CombinedDeviceSyncEditView):
    model = DeviceMerakiConfig
    form_class = forms.DeviceMerakiConfigForm
    settings_model = MerakiConfig
    permission_name = "netbox_cisco_sync.change_devicemerakiconfig"
    run_field = "meraki_config"
    source_name = "Meraki"
    source_key = "meraki"
    list_url_name = "plugins:netbox_cisco_sync:devicemerakiconfig_list"
    delete_url_name = "plugins:netbox_cisco_sync:devicemerakiconfig_delete"

    def collect_full_data(self, config, settings, *, force_refresh=False):
        return collect_meraki_config(
            config,
            settings=settings,
            include_unselected=True,
            force_refresh=force_refresh,
        )

    def source_context(self, config):
        return {
            "source_site_label": "Meraki Network",
            "source_site_name": config.network_name,
            "source_identifier_label": "Network ID",
            "source_identifier": config.network_id,
            "source_management_ip": config.management_ip,
        }


@register_model_view(DeviceMerakiConfig, name="delete")
class DeviceMerakiConfigDeleteView(generic.ObjectDeleteView):
    """Usuń rekord discovery Meraki bez usuwania urządzenia NetBox."""
    queryset = DeviceMerakiConfig.objects.all()


@register_model_view(DeviceMerakiConfig, name="bulk_delete", detail=False)
class DeviceMerakiConfigBulkDeleteView(generic.BulkDeleteView):
    queryset = DeviceMerakiConfig.objects.all()
    table = tables.DeviceMerakiConfigTable


@register_model_view(DeviceMerakiConfig, name="bulk_enable_selected", path="enable-selected", detail=False)
class DeviceMerakiConfigBulkEnableSelectedView(BulkEnableSelectedView):
    model = DeviceMerakiConfig
    filterset_class = filtersets.DeviceMerakiConfigFilterSet
    permission_name = "netbox_cisco_sync.change_devicemerakiconfig"
    source_name = "Meraki"
    list_url_name = "plugins:netbox_cisco_sync:devicemerakiconfig_list"


@register_model_view(DeviceMerakiConfig, name="toggle_enabled", path="toggle-enabled")
class DeviceMerakiConfigToggleEnabledView(DeviceConfigToggleEnabledView):
    model = DeviceMerakiConfig
    permission_name = "netbox_cisco_sync.change_devicemerakiconfig"
    source_name = "Meraki"
    list_url_name = "plugins:netbox_cisco_sync:devicemerakiconfig_list"


class DiscoverMerakiDevicesView(LoginRequiredMixin, View):
    """Ręcznie odśwież inventory z Meraki Dashboard API."""
    def get(self, request):
        return self.post(request)

    def post(self, request):
        if not request.user.has_perm("netbox_cisco_sync.change_devicemerakiconfig"):
            messages.error(request, "You do not have permission to run Meraki discovery.")
            return redirect("plugins:netbox_cisco_sync:devicemerakiconfig_list")
        try:
            result = discover_meraki_devices()
            messages.success(
                request,
                f"Meraki discovery: {result['seen']} device(s), {result['created']} created, "
                f"{result['updated']} refreshed.",
            )
        except Exception as exc:  # noqa: BLE001 - użytkownik musi zobaczyć błąd API.
            messages.error(request, f"Meraki discovery failed: {exc}")
        return redirect("plugins:netbox_cisco_sync:devicemerakiconfig_list")


class BulkMerakiSyncView(LoginRequiredMixin, View):
    """Potwierdź i zakolejkuj Apply wszystkich włączonych urządzeń Meraki."""
    template_name = "netbox_cisco_sync/bulk_sync_confirm.html"

    def get(self, request):
        if not request.user.has_perm("netbox_cisco_sync.change_devicemerakiconfig"):
            messages.error(request, "You do not have permission to run bulk Meraki sync.")
            return redirect("plugins:netbox_cisco_sync:devicemerakiconfig_list")
        count = enabled_meraki_configs().count()
        return render(request, self.template_name, {
            "device_count": count, "source_name": "Meraki",
            "cancel_url": "plugins:netbox_cisco_sync:devicemerakiconfig_list",
        })

    def post(self, request):
        if not request.user.has_perm("netbox_cisco_sync.change_devicemerakiconfig"):
            messages.error(request, "You do not have permission to run bulk Meraki sync.")
            return redirect("plugins:netbox_cisco_sync:devicemerakiconfig_list")
        count = enabled_meraki_configs().count()
        if count == 0:
            messages.warning(request, "No enabled Meraki devices match the Site and product family filters.")
            return redirect("plugins:netbox_cisco_sync:devicemerakiconfig_list")
        active_job = active_sync_job(MERAKI_BULK_JOB_NAME)
        if active_job:
            messages.warning(request, "A Meraki bulk sync is already queued or running.")
            return redirect(active_job.get_absolute_url())
        job = BulkMerakiSyncJob.enqueue(user=request.user)
        messages.success(request, f"Queued Meraki Sync and Apply for {count} device(s).")
        return redirect(job.get_absolute_url())


@register_model_view(DeviceMerakiConfig, name="sync", path="sync")
class DeviceMerakiConfigSyncView(DeviceEditRedirectView):
    model = DeviceMerakiConfig
