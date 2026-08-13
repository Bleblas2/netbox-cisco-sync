"""Serializery REST API wymagane również przez change log NetBoxa."""

from dcim.api.serializers import DeviceSerializer, SiteSerializer
from netbox.api.serializers import NetBoxModelSerializer

from ..models import (
    CatalystCenterConfig,
    DeviceCatalystCenterConfig,
    DeviceMerakiConfig,
    DeviceVmanageConfig,
    DiscoveredInterface,
    SyncRun,
    VmanageSyncConfig,
    MerakiConfig,
)


class DeviceVmanageConfigSerializer(NetBoxModelSerializer):
    """Reprezentacja wykrytego urządzenia i jego mapowania do NetBoxa."""

    netbox_site = SiteSerializer(nested=True, allow_null=True)
    device = DeviceSerializer(nested=True, allow_null=True)

    class Meta:
        model = DeviceVmanageConfig
        fields = (
            "id", "url", "display", "system_ip", "vmanage_uuid", "hostname",
            "serial_number", "device_model", "vmanage_site_id", "vmanage_site_name",
            "latitude", "longitude", "device_groups", "reachability", "netbox_site",
            "device", "match_method", "manual_site_override", "enabled",
            "interface_selection", "interfaces_last_refreshed", "last_discovered",
            "last_sync_at", "last_sync_status", "last_sync_message", "tags", "custom_fields",
            "created", "last_updated",
        )
        brief_fields = ("id", "url", "display", "system_ip", "hostname", "device")


class DeviceCatalystCenterConfigSerializer(NetBoxModelSerializer):
    """Reprezentacja urządzenia wykrytego przez Catalyst Center."""

    netbox_site = SiteSerializer(nested=True, allow_null=True)
    device = DeviceSerializer(nested=True, allow_null=True)

    class Meta:
        model = DeviceCatalystCenterConfig
        fields = (
            "id", "url", "display", "catalyst_id", "management_ip", "hostname",
            "serial_number", "switch_stack_serials", "switch_stack_info", "device_model",
            "catalyst_site_id", "catalyst_site_name",
            "latitude", "longitude", "reachability", "catalyst_role", "catalyst_family", "netbox_site", "device",
            "match_method", "manual_site_override", "enabled",
            "interface_selection", "interfaces_last_refreshed", "last_discovered",
            "last_sync_at", "last_sync_status", "last_sync_message", "tags", "custom_fields",
            "created", "last_updated",
        )
        brief_fields = ("id", "url", "display", "management_ip", "hostname", "device")


class DeviceMerakiConfigSerializer(NetBoxModelSerializer):
    """Reprezentacja urządzenia wykrytego przez Meraki Dashboard."""
    netbox_site = SiteSerializer(nested=True, allow_null=True)
    device = DeviceSerializer(nested=True, allow_null=True)

    class Meta:
        model = DeviceMerakiConfig
        fields = (
            "id", "url", "display", "serial_number", "hostname", "device_model",
            "product_family", "firmware", "network_id", "network_name", "management_ip",
            "latitude", "longitude", "netbox_site", "device", "match_method",
            "manual_site_override", "enabled", "interface_selection", "interfaces_last_refreshed",
            "last_discovered", "last_sync_at",
            "last_sync_status", "last_sync_message", "tags", "custom_fields", "created", "last_updated",
        )
        brief_fields = ("id", "url", "display", "serial_number", "hostname", "device")


class DiscoveredInterfaceSerializer(NetBoxModelSerializer):
    """Reprezentacja relacyjnego cache interfejsów platform źródłowych."""

    class Meta:
        model = DiscoveredInterface
        fields = (
            "id", "url", "display", "vmanage_config", "catalyst_config",
            "meraki_config", "name", "normalized_name", "description", "label",
            "interface_type", "admin_up", "oper_up", "mac_address",
            "ipv4_address", "ipv4_mask", "ipv6_addresses", "mtu",
            "speed_mbps", "vpn_id", "selected", "present", "last_seen",
            "mode", "untagged_vlan", "tagged_vlans",
            "bridge_name",
            "tags", "custom_fields", "created", "last_updated",
        )
        brief_fields = ("id", "url", "display", "name", "selected", "present")


class SyncRunSerializer(NetBoxModelSerializer):
    """Historia Compare/Apply serializowana m.in. przed usunięciem rekordu."""

    config = DeviceVmanageConfigSerializer(nested=True, allow_null=True)
    catalyst_config = DeviceCatalystCenterConfigSerializer(nested=True, allow_null=True)
    meraki_config = DeviceMerakiConfigSerializer(nested=True, allow_null=True)
    device = DeviceSerializer(nested=True, allow_null=True)

    class Meta:
        model = SyncRun
        fields = (
            "id", "url", "display", "config", "catalyst_config", "meraki_config", "device", "trigger", "mode", "status",
            "devices_created", "devices_updated", "interfaces_created", "interfaces_updated",
            "ips_created", "macs_created", "fhrp_groups_created", "message",
            "source_data",
            "reverted", "tags", "custom_fields", "created", "last_updated",
        )
        brief_fields = ("id", "url", "display", "config", "catalyst_config", "meraki_config", "device", "mode", "status")


class VmanageSyncConfigSerializer(NetBoxModelSerializer):
    """Globalne ustawienia; hasło może być zapisane, ale nigdy zwrócone przez API."""

    class Meta:
        model = VmanageSyncConfig
        fields = (
            "id", "url", "display", "base_url", "username", "password", "verify_ssl",
            "ca_bundle", "request_timeout", "request_retries", "update_existing",
            "sync_interfaces", "ignore_disabled_interfaces", "sync_ipv4", "sync_ipv6",
            "sync_mac_addresses", "set_primary_ips", "preferred_primary_ipv4_interface",
            "sync_fhrp", "gps_max_distance_km", "default_device_role", "sync_interval_hours",
            "history_keep_days", "tags", "custom_fields", "created", "last_updated",
        )
        brief_fields = ("id", "url", "display", "base_url", "username")
        # Sekret jest akceptowany przy zapisie, ale nie może pojawić się w odpowiedzi
        # API ani w serializowanym change logu NetBoxa.
        extra_kwargs = {"password": {"write_only": True}}


class CatalystCenterConfigSerializer(NetBoxModelSerializer):
    """Ustawienia Catalyst Center z sekretem wyłącznie do zapisu."""

    class Meta:
        model = CatalystCenterConfig
        fields = (
            "id", "url", "display", "base_url", "username", "password", "verify_ssl",
            "ca_bundle", "request_timeout", "request_retries", "enabled", "update_existing",
            "sync_interfaces", "ignore_disabled_interfaces", "sync_ipv4", "sync_ipv6",
            "sync_mac_addresses", "set_primary_ips", "preferred_primary_ipv4_interface",
            "import_device_roles", "sync_fhrp", "default_device_role", "sync_interval_hours",
            "gps_max_distance_km", "history_keep_days", "tags", "custom_fields", "created", "last_updated",
        )
        brief_fields = ("id", "url", "display", "base_url", "username", "enabled")
        extra_kwargs = {"password": {"write_only": True}}


class MerakiConfigSerializer(NetBoxModelSerializer):
    """Ustawienia Meraki z kluczem API dostępnym wyłącznie przy zapisie."""
    class Meta:
        model = MerakiConfig
        fields = (
            "id", "url", "display", "enabled", "base_url", "api_key", "organization_ids",
            "request_timeout", "request_retries", "update_existing", "sync_interfaces",
            "ignore_disabled_interfaces", "sync_ipv4", "sync_ipv6", "sync_mac_addresses",
            "set_primary_ips", "preferred_primary_ipv4_interface", "import_device_families",
            "gps_max_distance_km", "default_device_role", "sync_interval_hours",
            "history_keep_days", "tags", "custom_fields", "created", "last_updated",
        )
        brief_fields = ("id", "url", "display", "enabled", "base_url")
        extra_kwargs = {"api_key": {"write_only": True}}
