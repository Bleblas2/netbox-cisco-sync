"""Widoki ustawień platform oraz bezpiecznych testów połączeń."""

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.generic import View

from netbox.views import generic

from .. import forms
from ..connectors.catalyst_center import CatalystCenterConnector
from ..connectors.meraki import MerakiConnector
from ..connectors.vmanage import VmanageConnector
from ..models import (
    CatalystCenterConfig,
    MerakiConfig,
    VmanageSyncConfig,
)


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
