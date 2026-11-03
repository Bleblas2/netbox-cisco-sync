# NetBox Cisco Sync

NetBox Cisco Sync is a NetBox plugin for discovering and synchronizing network
inventory from Cisco Catalyst SD-WAN (vManage), Catalyst Center (DNA) and Meraki Dashboard.

Connections to Cisco platforms are read-only. Source collection and NetBox
changes are deliberately separated through a shared workflow:

```text
Discovery → Site mapping → Enable → Refresh interfaces → Preview → Apply → Sync Run → optional Revert
```

![NetBox Cisco Sync workflow](docs/images/netbox-cisco-sync-demo.gif)

> **Current status:** version `1.0.1` supports vManage, Catalyst Center, and
> Meraki through the complete Discovery/Refresh/Preview/Apply workflow.

## Contents

- [What It Does](#what-it-does)
- [Safety Model](#safety-model)
- [Supported Platforms](#supported-platforms)
- [Site Matching](#site-matching)
- [Installation](#installation)
- [First Run](#first-run)
- [Interface Cache and Selection](#interface-cache-and-selection)
- [Screenshots](#screenshots)
- [API Access](#api-access)
- [Data Rules](#data-rules)
- [Development and Testing](#development-and-testing)
- [Acknowledgements](#acknowledgements)
- [Disclaimer](#disclaimer)

## What It Does

- Discovers devices without creating NetBox inventory automatically.
- Maps discovered devices to existing NetBox Sites.
- Lets an operator enable individual devices, enable selected devices in bulk,
  and select interfaces. Bulk actions and the per-row Enabled button preserve
  device selection when returning to the inventory list.
- Builds an exact Preview snapshot before Apply.
- Creates or updates NetBox Devices, Interfaces, IP addresses, MAC addresses,
  primary IP assignments, and FHRP/VRRP objects when supported by the source.
- Imports switch port-channels from Catalyst Center as NetBox LAG interfaces
  and assigns their physical member ports.
- Stores every Preview and Apply as a Sync Run with counters, warnings, source
  data, created objects, and field-level changes.
- Reverts only objects recorded as created by a selected Apply run.
- Supports single-device Apply, background bulk Apply, and background interface
  refresh for selected devices through NetBox workers.
- Supports background Apply for only the devices selected in each platform
  inventory list.

## Safety Model

- Cisco APIs are used only for authentication and read operations.
- Newly discovered devices are disabled by default.
- Preview never writes Device, Interface, IP, MAC, or FHRP objects to NetBox.
- Apply uses the local interface cache or the explicitly submitted Preview
  snapshot and never silently refreshes source interfaces.
- Bulk Apply fails an individual device safely when its interface cache is
  missing and continues with the remaining devices.
- Existing NetBox devices are skipped unless **Update existing** is enabled.
- Discovery and Apply never remove devices missing from a Cisco platform.
- Revert removes only objects created and recorded by the selected Sync Run.
- Passwords, API keys, session cookies, and tokens are not written to plugin
  logs or returned through the plugin API.

## Supported Platforms

Reported tested versions:

| Platform | Versions |
|---|---|
| Cisco Catalyst SD-WAN Manager (vManage) | 20.12–20.18.2.1 |
| Cisco Catalyst Center | 2.3.3–3.6.1 |
| NetBox | 4.6.1–4.6.9 |

### Cisco vManage

- Discovers cEdge/vEdge devices and ignores vManage, vSmart, and vBond
  controllers.
- Imports device identity, interfaces, IPv4/IPv6, MAC addresses, and VRRP/FHRP.
- Uses the vManage `system-ip` as the primary IPv4 fallback.

### Cisco Catalyst Center

- Discovers supported network devices and their Building membership.
- Resolves Building membership primarily by Catalyst `deviceId` through the
  paginated assigned-to-Site API, including devices assigned to a Floor; older
  Catalyst Center versions fall back to membership matching by serial number.
- Filters discovery/import by exact **Family** or **Role** values.
- Imports management information and collected interfaces made available by the
  connector.
- Matches the Catalyst `platformId` to a NetBox Device Type `part_number` and
  creates a Cisco Device Type with that `part_number` only when no match exists.
- Imports all physical switch interfaces into the single NetBox Device used for
  the logical Catalyst Center device. A reported stack remains one Device with
  the active member serial in `Device.serial`. The complete member serial list,
  including the active member, and the exact Catalyst `stackSwitchInfo` payload are stored in the `SwitchStackSerials` and
  `SwitchStackInfo` Device Custom Fields, visible only when populated.
  Stack member details are read from the Catalyst Center per-device stack API.
  The JSON stores each member's number, priority, role, serial number, and
  platform ID in a stable format.

### Cisco Meraki Dashboard

- Supports MX appliances, MS switches, and MR access points.
- Collects MX WAN interfaces and `singleLan` where available.
- Represents MX `singleLan` as a NetBox bridge named `singlelan`, assigns the
  appliance IP to that bridge, and attaches LAN ports from the matching Device
  Type templates (falling back to `Port 2` through `Port 5`) as bridge
  members. MX uplinks use Device Type Library names `Internet 1`/`Internet 2`
  with labels `WAN1`/`WAN2`.
- When `singleLan` is not active, imports every MX appliance LAN port with its
  enabled state, access/trunk mode, native/access VLAN, and allowed VLAN list.
- Reads MX uplink settings per device, including models with WAN3, and merges
  their enabled/VLAN configuration with current WAN addresses.
- On MX64/MX67, removes `Port 2` from LAN when the shared physical port is
  enabled as `Internet 2`/WAN2.
- Collects MS port configuration, enabled state, link status, and speed.
- Maps MS port speed to the corresponding NetBox interface type.
- Does not import client history, client MAC tables, L2 topology, or firmware.

## Site Matching

A manual Site override always has priority. Automatic matching then follows the
platform-specific sequence:

| Platform | Matching order |
|---|---|
| vManage | `SdwanSiteId` custom field → normalized Site name → nearest unique GPS match → primary IP in a Site-scoped Prefix |
| Catalyst Center | normalized Building/Site name → nearest unique GPS match → management IP in a Site-scoped Prefix |
| Meraki Dashboard | `MerakiSiteId` custom field → normalized Network/Site name → nearest unique GPS match → management IP in a Site-scoped Prefix |

Name matching replaces `_` and `-` with spaces, collapses whitespace, and
compares values case-insensitively. GPS matching succeeds only when the nearest
Site is unique and within the configured distance. Ambiguous devices remain
unmatched for manual review.

As the final fallback, the source primary/management IP is compared with NetBox
Prefixes scoped directly to a Site. The most specific matching Prefix wins,
including a broader Site-scoped parent when a more specific child has no Site.
Equally specific matches pointing to different Sites remain unmatched.

Meraki Discovery compares the Dashboard Network ID with `MerakiSiteId`, which
is also maintained during Apply. vManage uses `SdwanSiteId`. The identifiers
are platform-specific and must not be interchanged.

## Installation

### Requirements

- NetBox 4.6.x; see [COMPATIBILITY.md](COMPATIBILITY.md).
- Device Types from the NetBox Device Type Library.
- Python supported by the selected NetBox release;
- a NetBox worker for queued and scheduled synchronization;
- read-only API credentials for each enabled Cisco platform.

### Install from PyPI

The recommended installation method is the
[`netbox-cisco-sync`](https://pypi.org/project/netbox-cisco-sync/) package from
PyPI. Install it into the same Python environment as NetBox:

```bash
source /opt/netbox/venv/bin/activate
python -m pip install netbox-cisco-sync
```

Enable the plugin in the NetBox configuration:

```python
PLUGINS = [
    "netbox_cisco_sync",
]
```

Run migrations and restart both NetBox and its worker:

```bash
cd /opt/netbox/netbox
python manage.py migrate netbox_cisco_sync
sudo systemctl restart netbox netbox-rq
```

Earlier development builds may have a different migration history. Check that
history before upgrading; a normal package upgrade may not be sufficient.

### Upgrade

Install the selected newer version, run migrations, and restart both NetBox and
its worker:

```bash
source /opt/netbox/venv/bin/activate
python -m pip install --upgrade "netbox-cisco-sync==NEW_VERSION"
cd /opt/netbox/netbox
python manage.py migrate netbox_cisco_sync
sudo systemctl restart netbox netbox-rq
```

Review the release notes before every upgrade and back up the NetBox database.

Do not enable the former `netbox_vmanage_sync` plugin at the same time.

### Default Configuration

Defaults can be overridden through `PLUGINS_CONFIG`:

```python
PLUGINS_CONFIG = {
    "netbox_cisco_sync": {
        "preferred_vlan_group_slug": "",
        "sync_session_timeout_seconds": 300,
        "vmanage_ignored_interface_names": [
            "nvi0",
            "vmanage_system",
            "null0",
            "appnav-compress",
        ],
        "vmanage_ignored_interface_patterns": [
            r"virtualportgroup\d+",
            r"loopback655\d{2}",
            r"service-engine.*",
        ],
        "vmanage_default_platform_name": "Cisco SD-WAN",
        "vmanage_default_platform_slug": "sd-wan-cisco",
        "vmanage_site_id_field": "SdwanSiteId",
        "vmanage_controller_types": ["vmanage", "vsmart", "vbond", "vedge-vbond"],
        "vmanage_edge_types": ["vedge", "cedge"],
        "ccc_ignored_interface_names": [],
        "ccc_ignored_interface_patterns": [],
        "ccc_default_platform_name": "Cisco Catalyst Center",
        "ccc_default_platform_slug": "cisco-catalyst-center",
        "meraki_site_id_field": "MerakiSiteId",
        "meraki_speed_to_interface_type": {
            100: "100base-tx",
            1000: "1000base-t",
            2500: "2.5gbase-t",
            5000: "5gbase-t",
            10000: "10gbase-t",
            25000: "25gbase-x-sfp28",
            40000: "40gbase-x-qsfpp",
            100000: "100gbase-x-qsfp28",
        },
    },
}
```

## First Run

1. Open **Plugins → Cisco Sync → Settings**.
2. Select a platform tab, enable the integration, enter its API connection
   details, save, and use **Test connection**.
3. Open **Discovered Devices** and select the same platform tab.
4. Run **Discover from ...**.
5. Review automatic Site matches and set manual overrides where necessary.
6. Select one or more devices and use **Refresh interfaces for selected
   devices**, or refresh a single device from its Edit/Preview page.
7. Select one or more devices and choose **Enable selected**, or enable a
   single device with its Enabled/Disabled row button. The selected rows remain
   selected after the action.
8. Open a device, select interfaces, and save the selection.
9. Inspect Preview and Apply the stored snapshot.
10. Verify the resulting NetBox objects and Sync Run.
11. After validating individual devices, use **Apply all enabled devices**.

In any platform inventory, select devices and choose **Enable selected** to
turn on sync for those records. The action is safe to repeat and preserves the
selection when the list reloads. The per-row Enabled/Disabled button also keeps
the current selection.

Alternatively, select specific enabled and Site-mapped records and choose
**Apply selected devices** directly below the interface refresh action. This
uses only their existing interface cache and does not query the source platform.
Selections are retained after these bulk actions as well.

For every source, Device Types are identified by exact `part_number`, not by
their display model name. Apply reuses an existing matching type. Only when no
matching `part_number` exists does the plugin create a Cisco Device Type and
populate both its model and `part_number`.

## Interface Cache and Selection

Interface details are collected explicitly and stored in
`DiscoveredInterface`. Save, Preview, Apply, bulk Apply, and scheduled jobs use
this local cache.

The source API is queried for interface details only when:

- the operator explicitly selects **Refresh / ReSync** on one device; or
- the operator selects devices in a platform list and chooses
  **Refresh interfaces for selected devices**.

**Apply all enabled devices** never refreshes interfaces. It applies the
current cache for enabled devices with a mapped Site. Discovery refreshes only
the lightweight device inventory and Site mapping inputs; it does not replace
the interface refresh step.

Each interface is displayed with a checkbox. Rules in
`*_ignored_interface_names` and `*_ignored_interface_patterns` do not hide or
discard collected data. They only make matching interfaces unchecked by
default. An explicit operator selection takes priority.

Each platform Settings page also provides **Ignore RFC1918 IP on WAN
interfaces**. When enabled, an IPv4 address from `10.0.0.0/8`,
`172.16.0.0/12`, or `192.168.0.0/16` is not created as an IPAM `IPAddress` on
an interface named `WAN`, `WANn`, or `WAN n`. The same rule applies when the
interface label matches that pattern, including Meraki `Internet N` interfaces
labelled `WANn`. The Interface is still synchronized and the skipped address
with its prefix is appended to its description. On vManage, where collected
interfaces normally have no label, recognition uses the source `ifname`; a
transport interface such as `GigabitEthernet0/0/0` is not implicitly treated as
WAN solely because it belongs to VPN 0.

## Screenshots

The animated overview at the top of this README is generated from the original
screenshots stored in [`docs/images/`](docs/images/). Static images remain
available there for detailed inspection and future documentation updates.

## Data Rules

- Catalyst Center uses the short hostname from an FQDN, without a fixed domain.
- IPv4 netmasks returned separately are converted to CIDR prefixes.
- `0.0.0.0` and all-zero MAC addresses are not assigned to NetBox objects.
- A physical interface wins when vManage reports the same address on `Tunnel0`.
- IPv6 without an explicit prefix is reported and skipped rather than guessed.
- **Ignore disabled interfaces** skips administratively disabled interfaces and
  their dependent IP, MAC, and FHRP data.
- **Ignore RFC1918 IP on WAN interfaces** preserves the WAN Interface but skips
  its RFC1918 `IPAddress`, records the address in the Interface description,
  and excludes it from Preview counters and primary IPv4 selection.
- Device Types are reused by exact `part_number`; a new Cisco type with a
  populated `part_number` is created only when no match exists.
- The preferred primary IPv4 interface can override the platform fallback.
- The first assigned global IPv6 address becomes primary IPv6.
- VRRP data creates a NetBox FHRP group, interface assignment, priority, and VIP.
- Tags selected in Settings are added without removing existing tags.
- Apply without a mapped Site is rejected.
- Discovery does not overwrite a manual Site override.

## Development and Testing

The shared synchronization engine lives in `netbox_cisco_sync/sync/`.
Source-specific API access and normalization live in
`netbox_cisco_sync/connectors/`.

### Test Environments

The plugin was tested in sandbox environments and in production installations.
The test setup included NetBox 4.6.x, Python 3.14.4, and Docker Desktop with WSL2.

Production testing covered the following sources:

| Source | Test environments | Production inventory size |
|---|---|---|
| vManage | Sandbox and production | More than 200 devices |
| Catalyst Center | Sandbox and production | More than 1000 devices |
| Meraki Dashboard API | Production with MX and MS devices | More than 200 devices |

These figures describe the inventory in the production installations used for
testing. They do not mean that all devices were processed in one synchronization
job. Production testing does not cover every device model or configuration.

## Acknowledgements

API communication and data-collection code was adapted from:

- `netbox-vmanage-sync`;
- `netbox-meraki-sync`;
- `ciscodnacnetbox`.

These projects are not runtime dependencies. Listing them does not imply
affiliation or endorsement by their authors.

## Disclaimer

This is an independent community project and is not an official Cisco product.
Cisco, Cisco Systems, Catalyst, Meraki, vManage, and related names and marks are
the property of their respective owners. Their use identifies compatibility and
does not imply endorsement.

Development of this plugin was assisted by OpenAI Codex.
