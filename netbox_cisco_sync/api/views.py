"""ViewSety modeli pluginu dla REST API NetBoxa."""

from netbox.api.viewsets import NetBoxModelViewSet

from .. import filtersets
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
from .serializers import (
    CatalystCenterConfigSerializer,
    DeviceCatalystCenterConfigSerializer,
    DeviceMerakiConfigSerializer,
    DeviceVmanageConfigSerializer,
    DiscoveredInterfaceSerializer,
    SyncRunSerializer,
    VmanageSyncConfigSerializer,
    MerakiConfigSerializer,
)


class DeviceVmanageConfigViewSet(NetBoxModelViewSet):
    queryset = DeviceVmanageConfig.objects.select_related("netbox_site", "device")
    serializer_class = DeviceVmanageConfigSerializer
    filterset_class = filtersets.DeviceVmanageConfigFilterSet


class DeviceCatalystCenterConfigViewSet(NetBoxModelViewSet):
    queryset = DeviceCatalystCenterConfig.objects.select_related("netbox_site", "device")
    serializer_class = DeviceCatalystCenterConfigSerializer
    filterset_class = filtersets.DeviceCatalystCenterConfigFilterSet


class DeviceMerakiConfigViewSet(NetBoxModelViewSet):
    queryset = DeviceMerakiConfig.objects.select_related("netbox_site", "device")
    serializer_class = DeviceMerakiConfigSerializer
    filterset_class = filtersets.DeviceMerakiConfigFilterSet


class DiscoveredInterfaceViewSet(NetBoxModelViewSet):
    queryset = DiscoveredInterface.objects.all()
    serializer_class = DiscoveredInterfaceSerializer


class SyncRunViewSet(NetBoxModelViewSet):
    queryset = SyncRun.objects.select_related("config", "device")
    serializer_class = SyncRunSerializer
    filterset_class = filtersets.SyncRunFilterSet


class VmanageSyncConfigViewSet(NetBoxModelViewSet):
    # Model jest singletonem, ale rejestracja ViewSetu jest potrzebna, aby NetBox
    # potrafił znaleźć jego serializer podczas tworzenia change logu.
    queryset = VmanageSyncConfig.objects.all()
    serializer_class = VmanageSyncConfigSerializer


class CatalystCenterConfigViewSet(NetBoxModelViewSet):
    queryset = CatalystCenterConfig.objects.all()
    serializer_class = CatalystCenterConfigSerializer


class MerakiConfigViewSet(NetBoxModelViewSet):
    queryset = MerakiConfig.objects.all()
    serializer_class = MerakiConfigSerializer
