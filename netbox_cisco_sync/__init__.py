"""Plugin NetBox synchronizujący inventory z obsługiwanych platform Cisco."""

from netbox.plugins import PluginConfig

__version__ = "0.1.1"

DEFAULT_PLUGIN_SETTINGS = {
    # Ustawienia vManage są oddzielone od innych źródeł, aby dodanie kolejnej
    # platformy nie zmieniało niejawnie jej filtrów ani nazw obiektów NetBox.
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
    # Catalyst Center korzysta z osobnych filtrów. Puste listy oznaczają, że
    # domyślnie nie odrzucamy interfejsów na podstawie nazw właściwych SD-WAN.
    "ccc_ignored_interface_names": [],
    "ccc_ignored_interface_patterns": [],
    "ccc_default_platform_name": "Cisco Catalyst Center",
    "ccc_default_platform_slug": "cisco-catalyst-center",
    "meraki_ignored_interface_names": [],
    "meraki_ignored_interface_patterns": [],
    "meraki_default_platform_name": "Cisco Meraki",
    "meraki_default_platform_slug": "cisco-meraki",
    "meraki_site_id_field": "MerakiSiteId",
    # Dokładne mapowanie prędkości portu MS na wartości choices NetBox.
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
    "meraki_family_interface_types": {
        "MS": "1000base-t",
        "MX": "1000base-t",
        "MR": "ieee802.11ax",
        "MG": "lte",
        "MV": "other",
        "MT": "other",
    },
}


class NetBoxCiscoSyncConfig(PluginConfig):
    name = "netbox_cisco_sync"
    label = "netbox_cisco_sync"
    verbose_name = "NetBox Cisco Sync"
    description = "Synchronize Cisco platform inventory into NetBox."
    version = __version__
    author = "Lukasz Luczak"
    author_email = "bleblas@gmail.com"
    base_url = "cisco-sync"
    min_version = "4.6.0"
    max_version = "4.6.99"
    required_settings = []
    default_settings = DEFAULT_PLUGIN_SETTINGS

    def ready(self):
        super().ready()
        # Sam import rejestruje dekorowane zadania cykliczne w workerze NetBox.
        from . import jobs  # noqa: F401


# Tymczasowy alias zachowuje zgodność integracji importujących starą nazwę klasy.
NetBoxVmanageSyncConfig = NetBoxCiscoSyncConfig

config = NetBoxCiscoSyncConfig
