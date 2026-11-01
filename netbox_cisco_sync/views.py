"""Publiczny punkt importu widoków pluginu.

Klasy są podzielone według odpowiedzialności, ale pozostają eksportowane z tego
modułu dla zgodności z konfiguracją URL-i i istniejącymi rozszerzeniami.
"""

from .view_modules.catalyst_center import (
    BulkCatalystCenterApplySelectedView,
    BulkCatalystCenterInterfaceRefreshView,
    BulkCatalystCenterSyncView,
    BulkRefreshCatalystInterfaces,
    DeviceCatalystCenterConfigBulkDeleteView,
    DeviceCatalystCenterConfigDeleteView,
    DeviceCatalystCenterConfigEditView,
    DeviceCatalystCenterConfigListView,
    DeviceCatalystCenterConfigSyncView,
    DeviceCatalystCenterConfigToggleEnabledView,
    DeviceCatalystCenterConfigView,
    DiscoverCatalystDevicesView,
)
from .view_modules.common import (
    CombinedDeviceSyncEditView,
    DeviceConfigToggleEnabledView,
    DeviceEditRedirectView,
    DiscoveredDevicesView,
)
from .view_modules.meraki import (
    BulkMerakiApplySelectedView,
    BulkMerakiInterfaceRefreshView,
    BulkMerakiSyncView,
    DeviceMerakiConfigBulkDeleteView,
    DeviceMerakiConfigDeleteView,
    DeviceMerakiConfigEditView,
    DeviceMerakiConfigListView,
    DeviceMerakiConfigSyncView,
    DeviceMerakiConfigToggleEnabledView,
    DeviceMerakiConfigView,
    DiscoverMerakiDevicesView,
)
from .view_modules.settings import (
    CatalystCenterSettingsView,
    CatalystCenterTestConnectionView,
    MerakiSettingsView,
    MerakiTestConnectionView,
    VmanageSettingsView,
    VmanageTestConnectionView,
)
from .view_modules.sync_runs import (
    SyncRunBulkDeleteView,
    SyncRunDeleteView,
    SyncRunListView,
    SyncRunRevertView,
    SyncRunView,
)
from .view_modules.vmanage import (
    BulkVmanageApplySelectedView,
    BulkVmanageInterfaceRefreshView,
    BulkVmanageSyncView,
    DeviceVmanageConfigBulkDeleteView,
    DeviceVmanageConfigDeleteView,
    DeviceVmanageConfigEditView,
    DeviceVmanageConfigListView,
    DeviceVmanageConfigSyncView,
    DeviceVmanageConfigToggleEnabledView,
    DeviceVmanageConfigView,
    DiscoverDevicesView,
)
