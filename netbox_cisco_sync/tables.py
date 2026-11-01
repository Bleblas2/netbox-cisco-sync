import django_tables2 as tables
from netbox.tables import NetBoxTable, columns

from .models import DeviceCatalystCenterConfig, DeviceMerakiConfig, DeviceVmanageConfig, SyncRun

SYNC_BUTTON = """
<a href="{% url 'plugins:netbox_cisco_sync:devicevmanageconfig_sync' pk=record.pk %}"
   class="btn btn-sm btn-primary" title="Preview sync"><i class="mdi mdi-sync"></i></a>
"""

ENABLED_TOGGLE_TEMPLATE = """
<button type="submit"
        class="btn btn-sm {% if record.enabled %}btn-success{% else %}btn-outline-secondary{% endif %}"
        title="{% if record.enabled %}Disable sync{% else %}Enable sync{% endif %}"
        formaction="{% url 'plugins:netbox_cisco_sync:__toggle_url_name__' pk=record.pk %}"
        formmethod="post"
        formnovalidate>
  <i class="mdi {% if record.enabled %}mdi-checkbox-marked{% else %}mdi-checkbox-blank-outline{% endif %}"></i>
  {% if record.enabled %}Enabled{% else %}Disabled{% endif %}
</button>
"""


def enabled_toggle_column(url_name):
    """Zbuduj wspólny przycisk Enabled/Disabled dla wybranej platformy."""
    return tables.TemplateColumn(
        template_code=ENABLED_TOGGLE_TEMPLATE.replace("__toggle_url_name__", url_name),
        order_by=("enabled",),
        orderable=True,
    )


class DeviceVmanageConfigTable(NetBoxTable):
    hostname = tables.Column(linkify=True, verbose_name="Name")
    # Przycisk w tabeli pozwala szybko włączyć Edge bez otwierania formularza Edit.
    # Używa POST do osobnego widoku, więc zachowuje CSRF oraz kontrolę uprawnień.
    # Wyświetlana wartość pozostaje przyciskiem, ale sortowanie korzysta bezpośrednio
    # z pola BooleanField modelu: Enabled/Disabled oraz kolejność odwrotna po kliknięciu.
    enabled = enabled_toggle_column("devicevmanageconfig_toggle_enabled")
    reachability = tables.Column(verbose_name="Status")
    device_model = tables.Column(verbose_name="Type")
    vmanage_site_name = tables.Column(verbose_name="vManage Site")
    netbox_site = tables.Column(linkify=True, verbose_name="NetBox Site")
    match_method = columns.ChoiceFieldColumn()
    device = tables.Column(linkify=True)
    # Domyślny ActionsColumn próbuje dodać także Delete. Konfiguracje pochodzą z
    # discovery, dlatego pokazujemy tylko istniejący widok Edit i własny przycisk Sync.
    actions = columns.ActionsColumn(actions=("edit",), extra_buttons=SYNC_BUTTON)

    class Meta(NetBoxTable.Meta):
        model = DeviceVmanageConfig
        fields = (
            "pk", "hostname", "enabled", "reachability", "device_model",
            "vmanage_site_name", "netbox_site", "system_ip", "serial_number",
            "match_method", "device", "last_sync_status", "last_sync_at",
        )
        default_columns = (
            "hostname", "enabled", "reachability", "device_model", "vmanage_site_name",
            "netbox_site", "system_ip", "serial_number", "match_method", "actions",
        )


class SyncRunTable(NetBoxTable):
    created = columns.DateTimeColumn(linkify=True)
    config = tables.Column(linkify=True)
    catalyst_config = tables.Column(linkify=True)
    meraki_config = tables.Column(linkify=True)
    device = tables.Column(linkify=True)
    trigger = columns.ChoiceFieldColumn()
    mode = columns.ChoiceFieldColumn()
    status = columns.ChoiceFieldColumn()
    reverted = columns.BooleanColumn()
    actions = columns.ActionsColumn(actions=("delete",))

    class Meta(NetBoxTable.Meta):
        model = SyncRun
        fields = (
            "pk", "created", "config", "catalyst_config", "meraki_config", "device", "trigger", "mode", "status",
            "devices_created", "devices_updated", "interfaces_created", "interfaces_updated",
            "ips_created", "macs_created", "fhrp_groups_created", "reverted", "message",
        )
        default_columns = (
            "created", "config", "catalyst_config", "device", "mode", "status", "devices_created",
            "interfaces_created", "ips_created", "fhrp_groups_created", "reverted",
        )


CATALYST_SYNC_BUTTON = """
<a href="{% url 'plugins:netbox_cisco_sync:devicecatalystcenterconfig_sync' pk=record.pk %}"
   class="btn btn-sm btn-primary" title="Preview sync"><i class="mdi mdi-sync"></i></a>
"""

MERAKI_SYNC_BUTTON = """
<a href="{% url 'plugins:netbox_cisco_sync:devicemerakiconfig_sync' pk=record.pk %}"
   class="btn btn-sm btn-primary" title="Preview sync"><i class="mdi mdi-sync"></i></a>
"""


class DeviceCatalystCenterConfigTable(NetBoxTable):
    hostname = tables.Column(linkify=True, verbose_name="Name")
    enabled = enabled_toggle_column("devicecatalystcenterconfig_toggle_enabled")
    management_ip = tables.Column(verbose_name="Management IP")
    catalyst_site_name = tables.Column(verbose_name="Catalyst Building")
    netbox_site = tables.Column(linkify=True, verbose_name="NetBox Site")
    match_method = columns.ChoiceFieldColumn()
    device = tables.Column(linkify=True)
    actions = columns.ActionsColumn(actions=("edit",), extra_buttons=CATALYST_SYNC_BUTTON)

    class Meta(NetBoxTable.Meta):
        model = DeviceCatalystCenterConfig
        fields = (
            "pk", "hostname", "enabled", "reachability", "device_model", "catalyst_site_name",
            "catalyst_family", "catalyst_role", "netbox_site", "management_ip", "serial_number", "match_method", "device",
            "latitude", "longitude",
            "last_sync_status", "last_sync_at",
        )
        default_columns = (
            "hostname", "enabled", "reachability", "device_model", "catalyst_site_name",
            "catalyst_family", "catalyst_role", "netbox_site", "management_ip", "serial_number", "match_method", "actions",
        )


class DeviceMerakiConfigTable(NetBoxTable):
    hostname = tables.Column(linkify=True, verbose_name="Name")
    enabled = enabled_toggle_column("devicemerakiconfig_toggle_enabled")
    network_name = tables.Column(verbose_name="Meraki Network")
    netbox_site = tables.Column(linkify=True, verbose_name="NetBox Site")
    match_method = columns.ChoiceFieldColumn()
    device = tables.Column(linkify=True)
    actions = columns.ActionsColumn(actions=("edit", "delete"), extra_buttons=MERAKI_SYNC_BUTTON)

    class Meta(NetBoxTable.Meta):
        model = DeviceMerakiConfig
        fields = (
            "pk", "hostname", "enabled", "product_family", "device_model", "network_name",
            "netbox_site", "management_ip", "serial_number", "match_method", "device",
            "latitude", "longitude", "last_sync_status", "last_sync_at",
        )
        default_columns = (
            "hostname", "enabled", "product_family", "device_model", "network_name",
            "netbox_site", "management_ip", "serial_number", "match_method", "actions",
        )
