# NetBox Cisco Sync

NetBox Cisco Sync is a NetBox plugin for discovering and synchronizing network
inventory from Cisco vManage, Cisco Catalyst Center, and Cisco Meraki
Dashboard. NetBox 4.6 is the minimum migration baseline; current validation is
performed on NetBox 6.0.6.

Connections to Cisco platforms are read-only. Source collection and NetBox
changes are deliberately separated through a shared workflow:

```text
Discovery → Site mapping → Enable → Refresh interfaces → Preview → Apply → Sync Run → optional Revert
```

![NetBox Cisco Sync workflow](docs/images/netbox-cisco-sync-demo.gif)

> **Current status:** version `0.1.0` supports vManage, Catalyst Center, and
> Meraki through the complete Discovery/Refresh/Preview/Apply workflow. It has
> been validated on the local demo environment and the `netbox-prod-test`
> production copy. Treat it as a pre-release build until it is published.

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
- Lets an operator enable individual devices and select interfaces.
- Builds an exact Preview snapshot before Apply.
- Creates or updates NetBox Devices, Interfaces, IP addresses, MAC addresses,
  primary IP assignments, and FHRP/VRRP objects when supported by the source.
- Stores every Preview and Apply as a Sync Run with counters, warnings, source
  data, created objects, and field-level changes.
- Reverts only objects recorded as created by a selected Apply run.
- Supports single-device Apply, background bulk Apply, and background interface
  refresh for selected devices through NetBox workers.

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

### Cisco vManage

- Discovers cEdge/vEdge devices and ignores vManage, vSmart, and vBond
  controllers.
- Imports device identity, interfaces, IPv4/IPv6, MAC addresses, and VRRP/FHRP.
- Uses the vManage `system-ip` as the primary IPv4 fallback.

### Cisco Catalyst Center

- Discovers supported network devices and their Building membership.
- Filters discovery/import by exact **Family** or **Role** values.
- Imports management information and collected interfaces made available by the
  connector.
- Matches the Catalyst `platformId` to a NetBox Device Type `part_number`.
- Imports all physical switch interfaces into the single NetBox Device used for
  the logical Catalyst Center device. A reported stack remains one Device with
  its combined serial limited to the NetBox field length.

### Cisco Meraki Dashboard

- Supports MX appliances, MS switches, and MR access points.
- Collects MX WAN interfaces and `singleLan` where available.
- Represents MX `singleLan` as a NetBox bridge named `singlelan`, assigns the
  appliance IP to that bridge, and attaches `Port 2` through `Port 5` as bridge
  members. MX uplinks use Device Type Library names `Internet 1`/`Internet 2`
  with labels `WAN1`/`WAN2`.
- Collects MS port configuration, enabled state, link status, and speed.
- Maps MS port speed to the corresponding NetBox interface type.
- Does not import client history, client MAC tables, L2 topology, or firmware.

## Site Matching

A manual Site override always has priority. Automatic matching then follows the
platform-specific sequence:

| Platform | Matching order |
|---|---|
| vManage | `SdwanSiteId` custom field → normalized Site name → nearest unique GPS match |
| Catalyst Center | normalized Building/Site name → nearest unique GPS match |
| Meraki Dashboard | `MerakiSiteId` custom field → normalized Network/Site name → nearest unique GPS match |

Name matching replaces `_` and `-` with spaces, collapses whitespace, and
compares values case-insensitively. GPS matching succeeds only when the nearest
Site is unique and within the configured distance. Ambiguous devices remain
unmatched for manual review.

Meraki Discovery compares the Dashboard Network ID with `MerakiSiteId`, which
is also maintained during Apply. vManage uses `SdwanSiteId`. The identifiers
are platform-specific and must not be interchanged.

## Installation

### Requirements

- NetBox 4.6 or a later compatible release (currently validated on 6.0.6);
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

For reproducible deployments, pin the exact version:

```bash
python -m pip install "netbox-cisco-sync==0.1.0"
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

Installations created from an earlier development build must apply all newer
plugin migrations during upgrade.

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

### Private pre-release testing

Before a release is available on PyPI, install a wheel built from the repository:

```bash
python -m pip install /path/to/netbox_cisco_sync-0.1.0-py3-none-any.whl
```

Alternatively, install from a private Git repository. Pin an exact tag or commit
instead of a moving branch:

```bash
python -m pip install \
  "netbox-cisco-sync @ git+ssh://git@github.com/ORG/REPOSITORY.git@COMMIT_SHA"
```

### Docker

Install the package while building the NetBox image; do not install it manually
inside an already running container. Add a pinned PyPI package to the image
requirements file:

```text
netbox-cisco-sync==0.1.0
```

Enable it in `configuration/plugins.py`, rebuild the image, run migrations, and
restart the NetBox and worker services.

Example plugin configuration:

```python
PLUGINS = [
    "netbox_cisco_sync",
]
```

Do not enable the former `netbox_vmanage_sync` plugin at the same time.

### Default Configuration

Defaults can be overridden through `PLUGINS_CONFIG`:

```python
PLUGINS_CONFIG = {
    "netbox_cisco_sync": {
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
7. Open the device, select interfaces, save the selection, and enable it.
8. Inspect Preview and Apply the stored snapshot.
9. Verify the resulting NetBox objects and Sync Run.
10. After validating individual devices, use **Apply all enabled devices**.

For Catalyst Center, create NetBox Device Types whose `part_number` matches the
source `platformId` before Apply.

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

## Screenshots

The animated overview at the top of this README is generated from the original
screenshots stored in [`docs/images/`](docs/images/). Static images remain
available there for detailed inspection and future documentation updates.

## API Access

The plugin uses read-only API flows including:

### vManage

- `POST /j_security_check`
- `GET /dataservice/client/token`
- `GET /dataservice/device`
- `GET /dataservice/device/interface?deviceId=<system-ip>`
- `GET /dataservice/device/vrrp?deviceId=<system-ip>`

### Catalyst Center

- `POST /dna/system/api/v1/auth/token`
- `GET /dna/intent/api/v1/network-device`
- `GET /dna/intent/api/v1/site`
- `GET /dna/intent/api/v1/membership/<site-id>`
- `GET /dna/intent/api/v1/interface/network-device/<device-id>`
- `GET /dna/intent/api/v1/network-device/<device-id>/equipment?type=Chassis`

### Meraki Dashboard

- `GET /organizations`
- `GET /organizations/<organization-id>/networks`
- `GET /networks/<network-id>/devices`
- `GET /devices/<serial>`
- `GET /devices/<serial>/switch/ports`
- `GET /devices/<serial>/switch/ports/statuses`
- `GET /networks/<network-id>/appliance/singleLan`

## Data Rules

- IPv4 netmasks returned separately are converted to CIDR prefixes.
- `0.0.0.0` and all-zero MAC addresses are not assigned to NetBox objects.
- A physical interface wins when vManage reports the same address on `Tunnel0`.
- IPv6 without an explicit prefix is reported and skipped rather than guessed.
- **Ignore disabled interfaces** skips administratively disabled interfaces and
  their dependent IP, MAC, and FHRP data.
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

Important modules:

- `sync/orchestrator.py` — Preview and Apply coordination;
- `sync/interfaces.py` — interfaces, selection, status, speed, and MAC handling;
- `sync/addresses.py` — IP assignment and primary IP selection;
- `sync/fhrp.py` — VRRP/FHRP objects;
- `sync/sites.py` — platform-specific Site identifiers;
- `interface_cache.py` — relational source-interface cache;
- `jobs.py` — bulk and scheduled work;
- `models.py` — Settings, discovery inventory, cache, and audit history;
- `views.py` — stable public exports used by URL configuration;
- `view_modules/` — shared, platform, Settings, and Sync Run views split by
  responsibility.

### Tested with

- NetBox `6.0.6` on `netbox-prod-test` (with migrations pinned for minimum
  compatibility with NetBox 4.6);
- Python `3.14.4`;
- Docker Desktop with WSL2;
- Cisco vManage sandbox;
- Cisco Catalyst Center sandbox;
- Cisco Meraki Dashboard API with MX and MS devices.

Validation covered clean plugin installation, migrations, connection tests,
Discovery, Site matching, interface cache and selection, Preview, Apply, Revert,
Sync Runs, permissions, bulk actions, and all plugin pages.

## Acknowledgements

NetBox Cisco Sync was inspired by earlier community integrations for Cisco
platforms. Parts of the initial implementation were based on or adapted selected
API communication and data-collection patterns from:

- `netbox-vmanage-sync`;
- `netbox-meraki-sync`;
- `ciscodnacnetbox`.

NetBox Cisco Sync combines these ideas within its own multi-platform data model,
interface cache, Site-matching rules, Preview/Apply workflow, audit history, and
NetBox synchronization engine. The projects listed above are not runtime
dependencies of this plugin, and acknowledgement does not imply affiliation or
endorsement by their authors.

## Disclaimer

This is an independent community project and is not an official Cisco product.
Cisco, Cisco Systems, Catalyst, Meraki, vManage, and related names and marks are
the property of their respective owners. Their use identifies compatibility and
does not imply endorsement.

Development of this plugin was assisted by OpenAI Codex.
