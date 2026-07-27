import django_filters
from django.db.models import Q
from netbox.filtersets import NetBoxModelFilterSet

from .models import DeviceCatalystCenterConfig, DeviceMerakiConfig, DeviceVmanageConfig, SyncRun


class DeviceVmanageConfigFilterSet(NetBoxModelFilterSet):
    # NetBox generuje link Related Objects w postaci ``?netbox_site_id=<pk>``.
    # Jawny alias sprawia, że kliknięcie relacji na Site ogranicza listę pluginu.
    netbox_site_id = django_filters.NumberFilter(field_name="netbox_site_id")

    class Meta:
        model = DeviceVmanageConfig
        fields = ("id", "enabled", "netbox_site", "match_method", "reachability", "vmanage_site_id")

    def search(self, queryset, name, value):
        return queryset.filter(Q(hostname__icontains=value) | Q(system_ip__icontains=value))


class SyncRunFilterSet(NetBoxModelFilterSet):
    class Meta:
        model = SyncRun
        fields = ("id", "config", "catalyst_config", "meraki_config", "device", "trigger", "mode", "status", "reverted")

    def search(self, queryset, name, value):
        return queryset.filter(
            Q(message__icontains=value)
            | Q(config__hostname__icontains=value)
            | Q(catalyst_config__hostname__icontains=value)
            | Q(meraki_config__hostname__icontains=value)
        )


class DeviceCatalystCenterConfigFilterSet(NetBoxModelFilterSet):
    netbox_site_id = django_filters.NumberFilter(field_name="netbox_site_id")

    class Meta:
        model = DeviceCatalystCenterConfig
        fields = ("id", "enabled", "netbox_site", "match_method", "reachability", "catalyst_site_id")

    def search(self, queryset, name, value):
        return queryset.filter(
            Q(hostname__icontains=value)
            | Q(management_ip__icontains=value)
            | Q(serial_number__icontains=value)
        )


class DeviceMerakiConfigFilterSet(NetBoxModelFilterSet):
    netbox_site_id = django_filters.NumberFilter(field_name="netbox_site_id")

    class Meta:
        model = DeviceMerakiConfig
        fields = ("id", "enabled", "product_family", "netbox_site", "match_method", "network_id")

    def search(self, queryset, name, value):
        return queryset.filter(
            Q(hostname__icontains=value) | Q(management_ip__icontains=value)
            | Q(serial_number__icontains=value) | Q(network_name__icontains=value)
        )
