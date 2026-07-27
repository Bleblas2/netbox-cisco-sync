from django import forms

from dcim.models import Site
from netbox.forms import NetBoxModelForm
from utilities.forms.fields import DynamicModelChoiceField

from .models import (
    CatalystCenterConfig,
    DeviceCatalystCenterConfig,
    DeviceVmanageConfig,
    DeviceMerakiConfig,
    MerakiConfig,
    VmanageSyncConfig,
)
from .interface_cache import cached_interface_queryset
from .sync.interfaces import selected_interface_names


class InterfaceSelectionFormMixin:
    """Dodaj dynamiczne checkboxy portów do formularza urządzenia discovery."""

    def __init__(self, *args, interface_rows=(), source_settings=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.interface_rows = list(interface_rows)
        choices = [
            (row.name, row.name)
            for row in self.interface_rows
            if row.name
        ]
        self.fields["interfaces"] = forms.MultipleChoiceField(
            choices=choices,
            required=False,
            widget=forms.CheckboxSelectMultiple,
            label="Interfaces to synchronize",
            help_text=(
                "Checked interfaces are included in Preview and Apply. "
                "Ignored name and pattern settings only define the initial unchecked state."
            ),
        )
        if not self.is_bound and self.interface_rows and source_settings is not None:
            self.initial["interfaces"] = selected_interface_names(
                self.interface_rows,
                source_settings,
                config=self.instance,
            )

    def save(self, commit=True):
        """Zapisz ręczne decyzje bez usuwania wyborów portów chwilowo nieobecnych."""
        instance = super().save(commit=False)
        selection = dict(instance.interface_selection or {})
        selected = {
            str(name).casefold()
            for name in self.cleaned_data.get("interfaces", [])
        }
        for row in self.interface_rows:
            if row.name and getattr(row, "present", True):
                selection[row.name.casefold()] = row.name.casefold() in selected
        instance.interface_selection = selection
        if commit:
            instance.save()
            # Relacyjna tabela jest źródłem wyboru dla Preview, Apply i zadań
            # cyklicznych; JSON pozostaje jedynie zgodnością ze starszymi danymi.
            for cached in cached_interface_queryset(instance, present_only=True):
                value = cached.normalized_name in selected
                if cached.selected != value:
                    cached.selected = value
                    cached.save(update_fields=("selected", "last_updated"))
            self.save_m2m()
        return instance


class DeviceVmanageConfigForm(InterfaceSelectionFormMixin, NetBoxModelForm):
    """Formularz ręcznego Site i włączenia Edge; dane z vManage są tylko do odczytu."""
    netbox_site = DynamicModelChoiceField(queryset=Site.objects.all(), required=False)

    class Meta:
        model = DeviceVmanageConfig
        fields = ("netbox_site", "manual_site_override", "enabled", "tags")

    def clean(self):
        # Ręcznej blokady nie można zapisać bez wskazania konkretnego Site.
        # NetBoxModelForm.clean() w NetBox 4.6 uzupełnia self.cleaned_data, ale
        # nie zawsze zwraca słownik. Nie wywołujemy więc .get() na jego wyniku.
        super().clean()
        cleaned = self.cleaned_data
        if cleaned.get("manual_site_override") and not cleaned.get("netbox_site"):
            self.add_error("netbox_site", "Select a NetBox Site for a manual override.")

        selected_site = cleaned.get("netbox_site")
        site_changed = "netbox_site" in self.changed_data
        manual_was_enabled = bool(self.instance.manual_site_override)

        # Zmiana Site w formularzu oznacza świadome mapowanie ręczne. Ustawiamy pola
        # na instancji podczas walidacji, a właściwy zapis pozostawiamy ObjectEditView.
        if site_changed:
            cleaned["manual_site_override"] = bool(selected_site)
            self.instance.manual_site_override = bool(selected_site)
            self.instance.match_method = "manual" if selected_site else "unmatched"
        elif cleaned.get("manual_site_override"):
            self.instance.match_method = "manual"
        elif manual_was_enabled:
            # Po zdjęciu ręcznej blokady kolejne discovery ponownie wyliczy metodę.
            self.instance.match_method = "unmatched"
        return cleaned


class VmanageSyncConfigForm(NetBoxModelForm):
    """Formularz singletonu Settings z bezpiecznym zachowaniem istniejącego hasła."""
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Leave blank to preserve the current password.",
    )

    class Meta:
        model = VmanageSyncConfig
        fields = (
            "enabled", "base_url", "username", "password", "verify_ssl", "ca_bundle",
            "request_timeout", "request_retries", "update_existing",
            "sync_interfaces", "ignore_disabled_interfaces", "sync_ipv4", "sync_ipv6", "sync_mac_addresses",
            "set_primary_ips", "preferred_primary_ipv4_interface", "sync_fhrp", "gps_max_distance_km",
            "default_device_role", "sync_interval_hours", "history_keep_days", "tags",
        )

    def clean_password(self):
        # Puste pole oznacza zachowanie hasła. Dzięki temu formularz nigdy nie musi
        # odsyłać aktualnego sekretu do przeglądarki.
        value = self.cleaned_data.get("password")
        if not value and self.instance.pk:
            return type(self.instance).objects.get(pk=self.instance.pk).password
        return value


class CatalystCenterConfigForm(NetBoxModelForm):
    password = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Leave blank to preserve the current password.",
    )

    class Meta:
        model = CatalystCenterConfig
        fields = (
            "enabled", "base_url", "username", "password", "verify_ssl", "ca_bundle",
            "request_timeout", "request_retries", "update_existing", "default_device_role",
            "sync_interfaces", "ignore_disabled_interfaces", "sync_ipv4", "sync_ipv6",
            "sync_mac_addresses",
            "preferred_primary_ipv4_interface", "import_device_roles",
            "gps_max_distance_km",
            "sync_interval_hours", "history_keep_days", "tags",
        )

    def clean_password(self):
        value = self.cleaned_data.get("password")
        if not value and self.instance.pk:
            return type(self.instance).objects.get(pk=self.instance.pk).password
        return value


class MerakiConfigForm(NetBoxModelForm):
    """Formularz Meraki zachowujący istniejący klucz API przy pustym polu."""
    api_key = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=False),
        help_text="Leave blank to preserve the current API key.",
    )

    class Meta:
        model = MerakiConfig
        fields = (
            "enabled", "base_url", "api_key", "organization_ids", "request_timeout", "request_retries",
            "update_existing", "default_device_role", "sync_interfaces", "ignore_disabled_interfaces",
            "sync_ipv4", "sync_ipv6", "sync_mac_addresses", "set_primary_ips",
            "preferred_primary_ipv4_interface", "import_device_families", "gps_max_distance_km",
            "sync_interval_hours", "history_keep_days", "tags",
        )

    def clean_api_key(self):
        value = self.cleaned_data.get("api_key")
        if not value and self.instance.pk:
            return type(self.instance).objects.get(pk=self.instance.pk).api_key
        return value


class DeviceCatalystCenterConfigForm(InterfaceSelectionFormMixin, NetBoxModelForm):
    netbox_site = DynamicModelChoiceField(queryset=Site.objects.all(), required=False)

    class Meta:
        model = DeviceCatalystCenterConfig
        fields = ("netbox_site", "manual_site_override", "enabled", "tags")

    def clean(self):
        super().clean()
        selected_site = self.cleaned_data.get("netbox_site")
        if self.cleaned_data.get("manual_site_override") and not selected_site:
            self.add_error("netbox_site", "Select a NetBox Site for a manual override.")
        if "netbox_site" in self.changed_data:
            self.cleaned_data["manual_site_override"] = bool(selected_site)
            self.instance.manual_site_override = bool(selected_site)
            self.instance.match_method = "manual" if selected_site else "unmatched"
        return self.cleaned_data


class DeviceMerakiConfigForm(InterfaceSelectionFormMixin, NetBoxModelForm):
    """Formularz ręcznego mapowania Meraki Network do NetBox Site."""
    netbox_site = DynamicModelChoiceField(queryset=Site.objects.all(), required=False)

    class Meta:
        model = DeviceMerakiConfig
        fields = ("netbox_site", "manual_site_override", "enabled", "tags")

    def clean(self):
        super().clean()
        selected_site = self.cleaned_data.get("netbox_site")
        if self.cleaned_data.get("manual_site_override") and not selected_site:
            self.add_error("netbox_site", "Select a NetBox Site for a manual override.")
        if "netbox_site" in self.changed_data:
            self.cleaned_data["manual_site_override"] = bool(selected_site)
            self.instance.manual_site_override = bool(selected_site)
            self.instance.match_method = "manual" if selected_site else "unmatched"
        return self.cleaned_data
