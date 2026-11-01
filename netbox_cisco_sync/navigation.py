from netbox.plugins import PluginMenu, PluginMenuItem

menu = PluginMenu(
    label="Cisco Sync",
    icon_class="mdi mdi-router-network",
    groups=(("Cisco Sync", (
        PluginMenuItem(
            link="plugins:netbox_cisco_sync:discovered_devices",
            link_text="Discovered Devices",
            permissions=("netbox_cisco_sync.view_discoveredinterface",),
        ),
        PluginMenuItem(
            link="plugins:netbox_cisco_sync:syncrun_list",
            link_text="Sync Runs",
            permissions=("netbox_cisco_sync.view_syncrun",),
        ),
        PluginMenuItem(
            link="plugins:netbox_cisco_sync:settings",
            link_text="Settings",
            permissions=("netbox_cisco_sync.change_vmanagesyncconfig",),
        ),
    )),),
)
