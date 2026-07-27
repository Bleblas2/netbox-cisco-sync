from django.urls import include, path
from utilities.urls import get_model_urls

from . import views

urlpatterns = [
    path("discovered-devices/", views.DiscoveredDevicesView.as_view(), name="discovered_devices"),
    path("devices/sync-all/", views.BulkVmanageSyncView.as_view(), name="bulk_sync"),
    path("devices/", include(get_model_urls("netbox_cisco_sync", "devicevmanageconfig", detail=False))),
    path("devices/<int:pk>/", include(get_model_urls("netbox_cisco_sync", "devicevmanageconfig"))),
    path("sync-runs/", include(get_model_urls("netbox_cisco_sync", "syncrun", detail=False))),
    path("sync-runs/<int:pk>/", include(get_model_urls("netbox_cisco_sync", "syncrun"))),
    path("discover/", views.DiscoverDevicesView.as_view(), name="discover"),
    path("settings/", views.VmanageSettingsView.as_view(), name="settings"),
    path("settings/vmanage/test/", views.VmanageTestConnectionView.as_view(), name="vmanage_test"),
    path("settings/catalyst-center/", views.CatalystCenterSettingsView.as_view(), name="catalyst_settings"),
    path("settings/catalyst-center/test/", views.CatalystCenterTestConnectionView.as_view(), name="catalyst_test"),
    path("settings/meraki/", views.MerakiSettingsView.as_view(), name="meraki_settings"),
    path("settings/meraki/test/", views.MerakiTestConnectionView.as_view(), name="meraki_test"),
    path("meraki/devices/sync-all/", views.BulkMerakiSyncView.as_view(), name="meraki_bulk_sync"),
    path("meraki/devices/", include(get_model_urls("netbox_cisco_sync", "devicemerakiconfig", detail=False))),
    path("meraki/devices/<int:pk>/", include(get_model_urls("netbox_cisco_sync", "devicemerakiconfig"))),
    path("meraki/discover/", views.DiscoverMerakiDevicesView.as_view(), name="meraki_discover"),
    path("catalyst-center/devices/sync-all/", views.BulkCatalystCenterSyncView.as_view(), name="catalyst_bulk_sync"),
    path("catalyst-center/devices/", include(get_model_urls("netbox_cisco_sync", "devicecatalystcenterconfig", detail=False))),
    path("catalyst-center/devices/<int:pk>/", include(get_model_urls("netbox_cisco_sync", "devicecatalystcenterconfig"))),
    path("catalyst-center/discover/", views.DiscoverCatalystDevicesView.as_view(), name="catalyst_discover"),
]
