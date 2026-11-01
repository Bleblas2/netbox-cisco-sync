"""Router REST API pluginu zgodny z automatycznym ładowaniem przez NetBox."""

from netbox.api.routers import NetBoxRouter

from .views import (
    CatalystCenterConfigViewSet,
    DeviceCatalystCenterConfigViewSet,
    DeviceMerakiConfigViewSet,
    DeviceVmanageConfigViewSet,
    DiscoveredInterfaceViewSet,
    SyncRunViewSet,
    VmanageSyncConfigViewSet,
    MerakiConfigViewSet,
)

router = NetBoxRouter()
router.register("device-vmanage-configs", DeviceVmanageConfigViewSet)
router.register("device-catalyst-center-configs", DeviceCatalystCenterConfigViewSet)
router.register("device-meraki-configs", DeviceMerakiConfigViewSet)
router.register("discovered-interfaces", DiscoveredInterfaceViewSet)
router.register("sync-runs", SyncRunViewSet)
router.register("settings", VmanageSyncConfigViewSet)
router.register("catalyst-center-settings", CatalystCenterConfigViewSet)
router.register("meraki-settings", MerakiConfigViewSet)

urlpatterns = router.urls
