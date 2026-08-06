"""Wspólne klasy bazowe widoków urządzeń wszystkich platform Cisco."""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.generic import View

from netbox.object_actions import ObjectAction

from ..choices import SyncModeChoices, SyncStatusChoices, SyncTriggerChoices
from ..dto import device_from_dict
from ..engine import sync_collected_device
from ..interface_cache import has_interface_cache
from ..jobs import active_sync_job
from ..models import (
    SyncRun,
    record_changes,
    record_created_objects,
)
from ..sync.interfaces import (
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


class BulkRefreshInterfacesAction(ObjectAction):
    """Wspólny przycisk odświeżania cache zaznaczonych urządzeń."""

    name = "bulk_refresh_interfaces"
    label = "Refresh interfaces for selected devices"
    multi = True
    permissions_required = {"change"}
    template_name = "netbox_cisco_sync/buttons/bulk_refresh_interfaces.html"


class BulkInterfaceRefreshView(LoginRequiredMixin, View):
    """Zakolejkuj platformowy Refresh zaznaczonych rekordów bez Apply."""

    model = None
    filterset_class = None
    job_class = None
    job_name = ""
    permission_name = ""
    source_name = ""
    list_url_name = ""

    def post(self, request):
        if not request.user.has_perm(self.permission_name):
            messages.error(request, f"You do not have permission to refresh {self.source_name} interfaces.")
            return redirect(self.list_url_name)
        queryset = self.model.objects.all()
        if request.POST.get("_all"):
            queryset = self.filterset_class(request.GET, queryset=queryset).qs
        else:
            queryset = queryset.filter(pk__in=request.POST.getlist("pk"))
        config_ids = list(queryset.values_list("pk", flat=True))
        if not config_ids:
            messages.warning(request, f"Select at least one {self.source_name} device.")
            return redirect(self.list_url_name)
        if active_job := active_sync_job(self.job_name):
            messages.warning(request, f"A {self.source_name} interface refresh is already queued or running.")
            return redirect(active_job.get_absolute_url())
        job = self.job_class.enqueue(user=request.user, config_ids=config_ids)
        messages.success(request, f"Queued interface refresh for {len(config_ids)} {self.source_name} device(s). No Apply will be performed.")
        return redirect(job.get_absolute_url())


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
