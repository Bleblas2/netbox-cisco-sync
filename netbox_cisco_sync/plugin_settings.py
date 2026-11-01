"""Defaults and helpers for file-based plugin configuration."""

from copy import deepcopy

from django.conf import settings

PLUGIN_NAME = "netbox_cisco_sync"

# Mapowanie służy do odczytu starszych konfiguracji plikowych. Nowe instalacje
# powinny używać wyłącznie nazw z prefiksem platformy.
LEGACY_SETTING_NAMES = {
    "vmanage_ignored_interface_names": "ignored_interface_names",
    "vmanage_ignored_interface_patterns": "ignored_interface_patterns",
    "vmanage_default_platform_name": "default_platform_name",
    "vmanage_default_platform_slug": "default_platform_slug",
    "vmanage_site_id_field": "sdwan_site_id_field",
    "vmanage_controller_types": "controller_types",
    "vmanage_edge_types": "edge_types",
}


def plugin_setting(name):
    """Zwróć ustawienie pluginu z obsługą historycznej nazwy bez prefiksu."""
    from . import DEFAULT_PLUGIN_SETTINGS

    default = deepcopy(DEFAULT_PLUGIN_SETTINGS[name])
    if not settings.configured:
        return default
    plugins_config = getattr(settings, "PLUGINS_CONFIG", {})
    configured = plugins_config.get(PLUGIN_NAME, {})
    if name in configured:
        return deepcopy(configured[name])
    legacy_name = LEGACY_SETTING_NAMES.get(name)
    if legacy_name and legacy_name in configured:
        return deepcopy(configured[legacy_name])
    return default


def platform_plugin_setting(settings_instance, name):
    """Wybierz klucz konfiguracyjny odpowiedni dla źródła synchronizacji."""
    class_name = settings_instance.__class__.__name__
    prefix = "ccc" if class_name == "CatalystCenterConfig" else "meraki" if class_name == "MerakiConfig" else "vmanage"
    return plugin_setting(f"{prefix}_{name}")
