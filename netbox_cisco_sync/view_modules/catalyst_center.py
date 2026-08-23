"""Widoki inventory, cache interfejsów i synchronizacji Catalyst Center."""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect, render
from django.views.generic import View

from netbox.object_actions import BulkDelete, BulkExport, ObjectAction
from netbox.views import generic
from utilities.views import register_model_view

from .. import filtersets, forms, tables
from ..catalyst_services import collect_catalyst_config, discover_catalyst_devices
from ..jobs import (
    CATALYST_BULK_JOB_NAME,
    CATALYST_INTERFACE_REFRESH_JOB_NAME,
    BulkCatalystCenterSyncJob,
    BulkCatalystCenterInterfaceRefreshJob,
    active_sync_job,
    enabled_catalyst_configs,
)
from ..models import CatalystCenterConfig, DeviceCatalystCenterConfig

from .common import (
    BulkApplySelectedAction,
    BulkApplySelectedView,
    CombinedDeviceSyncEditView,
    DeviceConfigToggleEnabledView,
    DeviceEditRedirectView,
)


class BulkRefreshCatalystInterfaces(ObjectAction):
    """Akcja tabeli odświeżająca cache portów zaznaczonych urządzeń CCC."""

    name = "bulk_refresh_interfaces"
    label = "Refresh interfaces for selected devices"
    multi = True
    permissions_required = {"change"}
    template_name = "netbox_cisco_sync/buttons/bulk_refresh_interfaces.html"


@register_model_view(DeviceCatalystCenterConfig, name="list", path="", detail=False)
class DeviceCatalystCenterConfigListView(generic.ObjectListView):
    queryset = DeviceCatalystCenterConfig.objects.select_related("netbox_site", "device")
    table = tables.DeviceCatalystCenterConfigTable
    filterset = filtersets.DeviceCatalystCenterConfigFilterSet
    template_name = "netbox_cisco_sync/devicecatalystcenterconfig_list.html"
    extra_context = {"discovered_source": "catalyst_center"}
    # Inventory powstaje wyłącznie przez discovery. Lista udostępnia osobne
    # odświeżenie cache, eksport i usuwanie zaznaczonych rekordów pluginu.
    actions = (
        BulkRefreshCatalystInterfaces,
        BulkApplySelectedAction,
        BulkExport,
        BulkDelete,
    )


class BulkCatalystCenterSyncView(LoginRequiredMixin, View):
    template_name = "netbox_cisco_sync/bulk_sync_confirm.html"

    def get(self, request):
        if not request.user.has_perm("netbox_cisco_sync.change_devicecatalystcenterconfig"):
            messages.error(request, "You do not have permission to run bulk Catalyst Center sync.")
            return redirect("plugins:netbox_cisco_sync:devicecatalystcenterconfig_list")
        count = enabled_catalyst_configs().count()
        return render(request, self.template_name, {
            "device_count": count,
            "source_name": "Catalyst Center",
            "cancel_url": "plugins:netbox_cisco_sync:devicecatalystcenterconfig_list",
        })

    def post(self, request):
        if not request.user.has_perm("netbox_cisco_sync.change_devicecatalystcenterconfig"):
            messages.error(request, "You do not have permission to run bulk Catalyst Center sync.")
            return redirect("plugins:netbox_cisco_sync:devicecatalystcenterconfig_list")
        count = enabled_catalyst_configs().count()
        if count == 0:
            messages.warning(request, "No enabled Catalyst Center devices match the Site and role filters.")
            return redirect("plugins:netbox_cisco_sync:devicecatalystcenterconfig_list")
        active_job = active_sync_job(CATALYST_BULK_JOB_NAME)
        if active_job:
            messages.warning(request, "A Catalyst Center bulk sync is already queued or running.")
            return redirect(active_job.get_absolute_url())
        job = BulkCatalystCenterSyncJob.enqueue(user=request.user)
        messages.success(request, f"Queued Catalyst Center Sync and Apply for {count} device(s).")
        return redirect(job.get_absolute_url())


@register_model_view(
    DeviceCatalystCenterConfig,
    name="bulk_refresh_interfaces",
    path="refresh-interfaces",
    detail=False,
)
class BulkCatalystCenterInterfaceRefreshView(LoginRequiredMixin, View):
    """Zakolejkuj odczyt interfejsów wybranych rekordów bez uruchamiania Apply."""

    permission_name = "netbox_cisco_sync.change_devicecatalystcenterconfig"
    list_url_name = "plugins:netbox_cisco_sync:devicecatalystcenterconfig_list"

    def post(self, request):
        if not request.user.has_perm(self.permission_name):
            messages.error(
                request,
                "You do not have permission to refresh Catalyst Center interfaces.",
            )
            return redirect(self.list_url_name)

        queryset = DeviceCatalystCenterConfig.objects.all()
        if request.POST.get("_all"):
            queryset = filtersets.DeviceCatalystCenterConfigFilterSet(
                request.GET,
                queryset=queryset,
            ).qs
        else:
            queryset = queryset.filter(pk__in=request.POST.getlist("pk"))
        config_ids = list(queryset.values_list("pk", flat=True))
        if not config_ids:
            messages.warning(request, "Select at least one Catalyst Center device.")
            return redirect(self.list_url_name)

        active_job = active_sync_job(CATALYST_INTERFACE_REFRESH_JOB_NAME)
        if active_job:
            messages.warning(
                request,
                "A Catalyst Center interface refresh is already queued or running.",
            )
            return redirect(active_job.get_absolute_url())

        job = BulkCatalystCenterInterfaceRefreshJob.enqueue(
            user=request.user,
            config_ids=config_ids,
        )
        messages.success(
            request,
            f"Queued interface refresh for {len(config_ids)} Catalyst Center device(s). "
            "No Apply will be performed.",
        )
        return redirect(job.get_absolute_url())


@register_model_view(DeviceCatalystCenterConfig, name="bulk_apply_selected", path="apply-selected", detail=False)
class BulkCatalystCenterApplySelectedView(BulkApplySelectedView):
    model = DeviceCatalystCenterConfig
    filterset_class = filtersets.DeviceCatalystCenterConfigFilterSet
    eligible_queryset = staticmethod(enabled_catalyst_configs)
    job_class = BulkCatalystCenterSyncJob
    job_name = CATALYST_BULK_JOB_NAME
    permission_name = "netbox_cisco_sync.change_devicecatalystcenterconfig"
    source_name = "Catalyst Center"
    list_url_name = "plugins:netbox_cisco_sync:devicecatalystcenterconfig_list"


@register_model_view(DeviceCatalystCenterConfig)
class DeviceCatalystCenterConfigView(DeviceEditRedirectView):
    model = DeviceCatalystCenterConfig


@register_model_view(DeviceCatalystCenterConfig, name="edit")
class DeviceCatalystCenterConfigEditView(CombinedDeviceSyncEditView):
    model = DeviceCatalystCenterConfig
    form_class = forms.DeviceCatalystCenterConfigForm
    settings_model = CatalystCenterConfig
    permission_name = "netbox_cisco_sync.change_devicecatalystcenterconfig"
    run_field = "catalyst_config"
    source_name = "Catalyst Center"
    source_key = "catalyst_center"
    list_url_name = (
        "plugins:netbox_cisco_sync:devicecatalystcenterconfig_list"
    )
    delete_url_name = (
        "plugins:netbox_cisco_sync:devicecatalystcenterconfig_delete"
    )

    def collect_full_data(self, config, settings, *, force_refresh=False):
        return collect_catalyst_config(
            config,
            settings=settings,
            include_unselected=True,
            force_refresh=force_refresh,
        )

    def source_context(self, config):
        return {
            "source_site_label": "Catalyst Building",
            "source_site_name": config.catalyst_site_name,
            "source_identifier_label": "Building ID",
            "source_identifier": config.catalyst_site_id,
            "source_management_ip": config.management_ip,
        }


@register_model_view(DeviceCatalystCenterConfig, name="delete")
class DeviceCatalystCenterConfigDeleteView(generic.ObjectDeleteView):
    """Usuń wyłącznie rekord discovery pluginu, nie powiązane urządzenie NetBox."""
    queryset = DeviceCatalystCenterConfig.objects.all()


@register_model_view(DeviceCatalystCenterConfig, name="bulk_delete", detail=False)
class DeviceCatalystCenterConfigBulkDeleteView(generic.BulkDeleteView):
    """Zbiorczo usuń zaznaczone rekordy inventory Catalyst Center."""
    queryset = DeviceCatalystCenterConfig.objects.all()
    table = tables.DeviceCatalystCenterConfigTable


@register_model_view(DeviceCatalystCenterConfig, name="toggle_enabled", path="toggle-enabled")
class DeviceCatalystCenterConfigToggleEnabledView(DeviceConfigToggleEnabledView):
    model = DeviceCatalystCenterConfig
    permission_name = "netbox_cisco_sync.change_devicecatalystcenterconfig"
    source_name = "Catalyst Center"
    list_url_name = "plugins:netbox_cisco_sync:devicecatalystcenterconfig_list"


class DiscoverCatalystDevicesView(LoginRequiredMixin, View):
    def get(self, request):
        return self.post(request)

    def post(self, request):
        if not request.user.has_perm("netbox_cisco_sync.change_devicecatalystcenterconfig"):
            messages.error(request, "You do not have permission to run Catalyst Center discovery.")
            return redirect("plugins:netbox_cisco_sync:devicecatalystcenterconfig_list")
        try:
            result = discover_catalyst_devices()
            messages.success(
                request,
                f"Catalyst Center discovery: {result['seen']} supported device(s), "
                f"{result['created']} created, {result['updated']} refreshed.",
            )
        except Exception as exc:  # noqa: BLE001
            messages.error(request, f"Catalyst Center discovery failed: {exc}")
        return redirect("plugins:netbox_cisco_sync:devicecatalystcenterconfig_list")


@register_model_view(DeviceCatalystCenterConfig, name="sync", path="sync")
class DeviceCatalystCenterConfigSyncView(DeviceEditRedirectView):
    model = DeviceCatalystCenterConfig
