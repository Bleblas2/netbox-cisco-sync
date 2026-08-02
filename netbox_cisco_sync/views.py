from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.generic import View

from netbox.object_actions import BulkDelete, BulkExport, DeleteObject
from netbox.views import generic
from utilities.views import register_model_view

from . import filtersets, forms, tables
from .choices import SyncModeChoices, SyncStatusChoices, SyncTriggerChoices
from .catalyst_services import collect_catalyst_config, discover_catalyst_devices
from .connectors.catalyst_center import CatalystCenterConnector
from .connectors.meraki import MerakiConnector
from .connectors.vmanage import VmanageConnector
from .dto import device_from_dict
from .engine import sync_collected_device
from .interface_cache import has_interface_cache
from .jobs import (
    BULK_JOB_NAME,
    CATALYST_BULK_JOB_NAME,
    MERAKI_BULK_JOB_NAME,
    SCHEDULED_JOB_NAME,
    SCHEDULED_JOB_BLOCKING_STATUSES,
    BulkVmanageSyncJob,
    BulkCatalystCenterSyncJob,
    BulkMerakiSyncJob,
    active_sync_job,
    enabled_configs,
    enabled_catalyst_configs,
    enabled_meraki_configs,
)
from .models import (
    CatalystCenterConfig, DeviceCatalystCenterConfig, DeviceMerakiConfig, DeviceVmanageConfig, MerakiConfig,
    SyncRun, VmanageSyncConfig, record_changes, record_created_objects,
)
from .services import collect_config_details, discover_devices
from .meraki_services import collect_meraki_config, discover_meraki_devices
from .sync.interfaces import (
    filter_collected_data,
    interface_type,
    nominal_interface_speed_mbps,
    selected_interface_names,
)


class CombinedDeviceSyncEditView(LoginRequiredMixin, View):
    """Wspólny formularz mapowania, wyboru portów, Preview i Apply."""

    model = None
    form_class = None
    settings_model = None
    permission_name = ""
    run_field = ""
    source_name = ""
    source_key = ""
    list_url_name = ""
    delete_url_name = ""

    def collect_full_data(self, config, settings, *, force_refresh=False):
        raise NotImplementedError

    def config_run_filter(self, config):
        return {self.run_field: config}

    def source_context(self, config):
        return {}

    def get_config(self, pk):
        return get_object_or_404(
            self.model.objects.select_related("netbox_site", "device"),
            pk=pk,
        )

    def check_permission(self, request):
        return request.user.has_perm(self.permission_name)

    def selected_data(self, data, settings, config, selected):
        """Odtwórz kopię pełnego snapshotu i pozostaw zaznaczone interfejsy."""
        filtered = device_from_dict(data.to_dict())
        return filter_collected_data(
            filtered,
            settings,
            config=config,
            selected_names=selected,
        )

    def create_compare_run(self, config, data, selected, result, device):
        """Zapisz pełną odpowiedź i dokładny wybór checkboxów jako Preview."""
        return SyncRun.objects.create(
            **self.config_run_filter(config),
            device=device,
            trigger=SyncTriggerChoices.MANUAL,
            mode=SyncModeChoices.COMPARE,
            status=(
                SyncStatusChoices.SKIPPED
                if result.skipped
                else SyncStatusChoices.OK
            ),
            devices_created=result.devices_created,
            devices_updated=result.devices_updated,
            interfaces_created=result.interfaces_created,
            interfaces_updated=result.interfaces_updated,
            ips_created=result.ips_created,
            macs_created=result.macs_created,
            fhrp_groups_created=result.fhrp_groups_created,
            message=result.message,
            source_data=data.to_dict(),
        )

    def render_page(
        self,
        request,
        config,
        settings,
        data,
        selected,
        result,
        run,
        form,
        *,
        status=200,
    ):
        # Preview pokazuje wynik interpretacji silnika NetBox, a nie tylko surowe
        # pole speed, którego Meraki często nie zwraca dla rozłączonego portu.
        for row in data.interfaces:
            row.netbox_type = interface_type(row, settings)
            row.effective_speed_mbps = (
                row.speed_mbps
                or nominal_interface_speed_mbps(row.netbox_type)
            )

        context = {
            "object": config,
            "form": form,
            "settings": settings,
            "data": data,
            "selected_names": set(selected),
            "result": result,
            "run": run,
            "source_name": self.source_name,
            "discovered_source": self.source_key,
            "list_url_name": self.list_url_name,
            "delete_url_name": self.delete_url_name,
            "interfaces_last_refreshed": config.interfaces_last_refreshed,
            **self.source_context(config),
        }
        return render(
            request,
            "netbox_cisco_sync/device_sync_edit.html",
            context,
            status=status,
        )

    def get(self, request, pk):
        config = self.get_config(pk)
        if not self.check_permission(request):
            messages.error(
                request,
                f"You do not have permission to edit {self.source_name} devices.",
            )
            return redirect(self.list_url_name)
        settings = self.settings_model.get()
        if not has_interface_cache(config):
            # Pierwsze wejście renderujemy natychmiast. Przeglądarka uruchomi
            # jawny Refresh, dzięki czemu użytkownik widzi stan ładowania.
            return render(
                request,
                "netbox_cisco_sync/device_interface_loading.html",
                {
                    "object": config,
                    "source_name": self.source_name,
                    "discovered_source": self.source_key,
                    "list_url_name": self.list_url_name,
                },
            )
        try:
            data = self.collect_full_data(config, settings)
            selected = selected_interface_names(
                data.interfaces,
                settings,
                config=config,
            )
            preview_data = self.selected_data(
                data,
                settings,
                config,
                selected,
            )
            result, device = sync_collected_device(
                config,
                preview_data,
                settings,
                apply=False,
            )
            run = self.create_compare_run(
                config,
                data,
                selected,
                result,
                device,
            )
        except Exception as exc:  # noqa: BLE001 - błąd źródła pokazujemy w UI.
            messages.error(
                request,
                f"{self.source_name} collection failed: {exc}",
            )
            return redirect(self.list_url_name)
        form = self.form_class(
            instance=config,
            interface_rows=data.interfaces,
            source_settings=settings,
        )
        return self.render_page(
            request,
            config,
            settings,
            data,
            selected,
            result,
            run,
            form,
        )

    def post(self, request, pk):
        config = self.get_config(pk)
        if not self.check_permission(request):
            messages.error(
                request,
                f"You do not have permission to edit {self.source_name} devices.",
            )
            return redirect(self.list_url_name)
        settings = self.settings_model.get()
        if request.POST.get("action") == "refresh":
            try:
                self.collect_full_data(config, settings, force_refresh=True)
            except Exception as exc:  # noqa: BLE001 - błąd źródła pokazujemy w UI.
                messages.error(request, f"{self.source_name} refresh failed: {exc}")
                if not has_interface_cache(config):
                    return redirect(self.list_url_name)
            else:
                messages.success(
                    request,
                    f"{self.source_name} interface cache refreshed.",
                )
            return redirect(config.get_absolute_url())

        preview = get_object_or_404(
            SyncRun,
            pk=request.POST.get("run"),
            mode=SyncModeChoices.COMPARE,
            **self.config_run_filter(config),
        )
        data = device_from_dict(preview.source_data)
        form = self.form_class(
            request.POST,
            instance=config,
            interface_rows=data.interfaces,
            source_settings=settings,
        )
        posted_selected = request.POST.getlist("interfaces")
        preview_data = self.selected_data(
            data,
            settings,
            config,
            posted_selected,
        )
        result, device = sync_collected_device(
            config,
            preview_data,
            settings,
            apply=False,
        )
        if not form.is_valid():
            return self.render_page(
                request,
                config,
                settings,
                data,
                posted_selected,
                result,
                preview,
                form,
                status=400,
            )

        config = form.save()
        selected = list(form.cleaned_data.get("interfaces", []))
        if request.POST.get("action") != "apply":
            messages.success(
                request,
                f"{self.source_name} device settings and interface selection saved.",
            )
            return redirect(config.get_absolute_url())

        apply_data = self.selected_data(
            data,
            settings,
            config,
            selected,
        )
        try:
            with transaction.atomic():
                result, device = sync_collected_device(
                    config,
                    apply_data,
                    settings,
                    apply=True,
                )
                run = SyncRun.objects.create(
                    **self.config_run_filter(config),
                    device=device,
                    trigger=SyncTriggerChoices.MANUAL,
                    mode=SyncModeChoices.APPLY,
                    status=(
                        SyncStatusChoices.SKIPPED
                        if result.skipped
                        else SyncStatusChoices.OK
                    ),
                    devices_created=result.devices_created,
                    devices_updated=result.devices_updated,
                    interfaces_created=result.interfaces_created,
                    interfaces_updated=result.interfaces_updated,
                    ips_created=result.ips_created,
                    macs_created=result.macs_created,
                    fhrp_groups_created=result.fhrp_groups_created,
                    message=result.message,
                    source_data=apply_data.to_dict(),
                )
                record_created_objects(run, result.created_objects)
                record_changes(run, result.changes)
                config.device = device
                config.last_sync_at = timezone.now()
                config.last_sync_status = run.status
                config.last_sync_message = result.message[:255]
                config.save(
                    update_fields=(
                        "device",
                        "last_sync_at",
                        "last_sync_status",
                        "last_sync_message",
                    )
                )
        except Exception as exc:  # noqa: BLE001 - błąd musi trafić do historii.
            SyncRun.objects.create(
                **self.config_run_filter(config),
                trigger=SyncTriggerChoices.MANUAL,
                mode=SyncModeChoices.APPLY,
                status=SyncStatusChoices.FAILED,
                message=str(exc),
                source_data=apply_data.to_dict(),
            )
            messages.error(request, f"{self.source_name} sync failed: {exc}")
            return redirect(config.get_absolute_url())
        messages.success(request, result.message)
        return redirect(run.get_absolute_url())


class DeviceEditRedirectView(LoginRequiredMixin, View):
    """Przekieruj historyczny Detail i Preview do połączonego widoku Edit."""

    model = None

    def get(self, request, pk):
        config = get_object_or_404(self.model, pk=pk)
        return redirect(config.get_absolute_url())

    def post(self, request, pk):
        config = get_object_or_404(self.model, pk=pk)
        messages.info(
            request,
            "Preview and interface selection are now available on the edit page.",
        )
        return redirect(config.get_absolute_url())


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
    actions = (BulkExport, BulkDelete)


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


class DeviceConfigToggleEnabledView(LoginRequiredMixin, View):
    """Wspólna akcja przełączająca synchronizację urządzenia z listy."""

    model = None
    permission_name = ""
    source_name = ""
    list_url_name = ""

    def post(self, request, pk):
        config = get_object_or_404(self.model, pk=pk)
        if not request.user.has_perm(self.permission_name):
            messages.error(request, f"You do not have permission to change {self.source_name} sync configuration.")
            return redirect(self.list_url_name)

        config.enabled = not config.enabled
        config.save(update_fields=("enabled", "last_updated"))
        state = "enabled" if config.enabled else "disabled"
        messages.success(request, f"{self.source_name} sync for {config.hostname} is now {state}.")

        # Powrót do Referer zachowuje wyszukiwanie, filtry i numer strony listy.
        return_url = request.META.get("HTTP_REFERER", "")
        if return_url and url_has_allowed_host_and_scheme(return_url, allowed_hosts={request.get_host()}):
            return redirect(return_url)
        return redirect(self.list_url_name)


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


@register_model_view(SyncRun, name="list", path="", detail=False)
class SyncRunListView(generic.ObjectListView):
    """Historia compare/apply z filtrowaniem po urządzeniu, statusie i trybie."""
    queryset = SyncRun.objects.select_related("config", "device")
    table = tables.SyncRunTable
    filterset = filtersets.SyncRunFilterSet
    # SyncRun jest rekordem audytowym tworzonym wyłącznie przez compare/apply.
    # Pusta lista akcji usuwa z nagłówka niepotrzebny przycisk "+ Add".
    actions = ()


@register_model_view(SyncRun)
class SyncRunView(generic.ObjectView):
    queryset = SyncRun.objects.all()
    # SyncRun jest niezmiennym wpisem audytowym. NetBox domyślnie pokazuje tutaj
    # Clone, Edit i Delete, mimo że dla tego modelu nie istnieje widok edycji.
    actions = (DeleteObject,)


@register_model_view(SyncRun, name="delete")
class SyncRunDeleteView(generic.ObjectDeleteView):
    queryset = SyncRun.objects.all()


@register_model_view(SyncRun, name="bulk_delete", detail=False)
class SyncRunBulkDeleteView(generic.BulkDeleteView):
    queryset = SyncRun.objects.all()
    table = tables.SyncRunTable


@register_model_view(SyncRun, name="revert")
class SyncRunRevertView(LoginRequiredMixin, View):
    """Potwierdzony ręcznie revert tylko obiektów z tabeli SyncRunObject."""
    def get(self, request, pk):
        return render(request, "netbox_cisco_sync/syncrun_revert.html", {"object": get_object_or_404(SyncRun, pk=pk)})

    def post(self, request, pk):
        run = get_object_or_404(SyncRun, pk=pk)
        if not request.user.has_perm("netbox_cisco_sync.change_syncrun"):
            messages.error(request, "You do not have permission to revert this run.")
        elif not run.can_revert:
            messages.warning(request, "Nothing to revert.")
        else:
            messages.success(request, f"Reverted {run.revert()} object(s) created by run #{run.pk}.")
        return redirect(run.get_absolute_url())


class VmanageSettingsView(generic.ObjectEditView):
    """Edycja pojedynczego rekordu połączenia i globalnego zachowania pluginu."""
    queryset = VmanageSyncConfig.objects.all()
    form = forms.VmanageSyncConfigForm
    template_name = "netbox_cisco_sync/settings.html"
    extra_context = {"active_tab": "vmanage"}

    def get_object(self, **kwargs):
        return VmanageSyncConfig.get()


class CatalystCenterSettingsView(generic.ObjectEditView):
    queryset = CatalystCenterConfig.objects.all()
    form = forms.CatalystCenterConfigForm
    template_name = "netbox_cisco_sync/settings.html"
    extra_context = {"active_tab": "catalyst_center"}

    def get_object(self, **kwargs):
        return CatalystCenterConfig.get()


class MerakiSettingsView(generic.ObjectEditView):
    """Edycja singletonu ustawień Cisco Meraki Dashboard."""
    queryset = MerakiConfig.objects.all()
    form = forms.MerakiConfigForm
    template_name = "netbox_cisco_sync/settings.html"
    extra_context = {"active_tab": "meraki"}

    def get_object(self, **kwargs):
        return MerakiConfig.get()


class VmanageTestConnectionView(LoginRequiredMixin, View):
    def post(self, request):
        if not request.user.has_perm("netbox_cisco_sync.change_vmanagesyncconfig"):
            messages.error(request, "You do not have permission to test vManage settings.")
            return redirect("plugins:netbox_cisco_sync:settings")
        try:
            connector = VmanageConnector(VmanageSyncConfig.get()).connect()
            count = len(connector.collect_inventory())
            messages.success(request, f"vManage connection succeeded; API returned {count} Edge device(s).")
        except Exception as exc:  # noqa: BLE001
            messages.error(request, f"vManage connection failed: {exc}")
        return redirect("plugins:netbox_cisco_sync:settings")


class CatalystCenterTestConnectionView(LoginRequiredMixin, View):
    def post(self, request):
        if not request.user.has_perm("netbox_cisco_sync.change_catalystcenterconfig"):
            messages.error(request, "You do not have permission to test Catalyst Center settings.")
            return redirect("plugins:netbox_cisco_sync:catalyst_settings")
        try:
            connector = CatalystCenterConnector(CatalystCenterConfig.get()).connect()
            count = len(connector.client.get_devices())
            messages.success(request, f"Catalyst Center connection succeeded; API returned {count} device(s).")
        except Exception as exc:  # noqa: BLE001
            messages.error(request, f"Catalyst Center connection failed: {exc}")
        return redirect("plugins:netbox_cisco_sync:catalyst_settings")


class MerakiTestConnectionView(LoginRequiredMixin, View):
    """Sprawdź klucz API i policz organizacje dostępne dla użytkownika."""
    def post(self, request):
        if not request.user.has_perm("netbox_cisco_sync.change_merakiconfig"):
            messages.error(request, "You do not have permission to test Meraki settings.")
            return redirect("plugins:netbox_cisco_sync:meraki_settings")
        try:
            connector = MerakiConnector(MerakiConfig.get()).connect()
            count = len(connector.client.get_organizations())
            messages.success(request, f"Meraki connection succeeded; API returned {count} organization(s).")
        except Exception as exc:  # noqa: BLE001 - błąd musi być widoczny w formularzu.
            messages.error(request, f"Meraki connection failed: {exc}")
        return redirect("plugins:netbox_cisco_sync:meraki_settings")


@register_model_view(DeviceMerakiConfig, name="list", path="", detail=False)
class DeviceMerakiConfigListView(generic.ObjectListView):
    """Lista urządzeń wykrytych w organizacjach i sieciach Meraki."""
    queryset = DeviceMerakiConfig.objects.select_related("netbox_site", "device")
    table = tables.DeviceMerakiConfigTable
    filterset = filtersets.DeviceMerakiConfigFilterSet
    template_name = "netbox_cisco_sync/devicemerakiconfig_list.html"
    extra_context = {"discovered_source": "meraki"}
    actions = (BulkExport, BulkDelete)


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


@register_model_view(DeviceCatalystCenterConfig, name="list", path="", detail=False)
class DeviceCatalystCenterConfigListView(generic.ObjectListView):
    queryset = DeviceCatalystCenterConfig.objects.select_related("netbox_site", "device")
    table = tables.DeviceCatalystCenterConfigTable
    filterset = filtersets.DeviceCatalystCenterConfigFilterSet
    template_name = "netbox_cisco_sync/devicecatalystcenterconfig_list.html"
    extra_context = {"discovered_source": "catalyst_center"}
    # Inventory powstaje wyłącznie przez discovery. Pozostawiamy eksport oraz
    # sprawdzone usuwanie zaznaczonych rekordów pluginu.
    actions = (BulkExport, BulkDelete)


class DiscoveredDevicesView(LoginRequiredMixin, View):
    """Przekieruj do pierwszej listy źródła dostępnej dla użytkownika."""
    access_permission = "netbox_cisco_sync.view_discoveredinterface"
    source_routes = (
        ("netbox_cisco_sync.view_devicevmanageconfig", "plugins:netbox_cisco_sync:devicevmanageconfig_list"),
        (
            "netbox_cisco_sync.view_devicecatalystcenterconfig",
            "plugins:netbox_cisco_sync:devicecatalystcenterconfig_list",
        ),
        ("netbox_cisco_sync.view_devicemerakiconfig", "plugins:netbox_cisco_sync:devicemerakiconfig_list"),
    )

    def get(self, request):
        # Wspólne uprawnienie steruje widocznością i dostępem do całej sekcji,
        # a uprawnienia modeli ograniczają dostęp do poszczególnych platform.
        if not request.user.has_perm(self.access_permission):
            raise PermissionDenied("You do not have permission to view discovered Cisco devices.")
        for permission, route in self.source_routes:
            if request.user.has_perm(permission):
                return redirect(route)
        raise PermissionDenied("You do not have permission to view discovered Cisco devices.")


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
