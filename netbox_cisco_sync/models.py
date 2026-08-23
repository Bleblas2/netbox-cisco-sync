"""Trwałe mapowania discovery, globalne ustawienia i historia synchronizacji."""

from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models.deletion import ProtectedError, RestrictedError
from django.urls import reverse

from netbox.models import NetBoxModel

from .choices import MatchMethodChoices, SyncModeChoices, SyncStatusChoices, SyncTriggerChoices

# Revert wykonuje kolejność odwrotną do tworzenia zależności. IP, w tym VIP,
# musi zniknąć przed grupą FHRP, a wszystkie obiekty interfejsowe przed Device.
REVERT_DELETE_PRIORITY = {
    "ipaddress": 0,
    "fhrpgroupassignment": 1,
    "fhrpgroup": 2,
    "macaddress": 3,
    "cable": 4,
    "interface": 5,
    "device": 6,
    "virtualchassis": 7,
    "devicetype": 8,
    "devicerole": 9,
    "manufacturer": 10,
}


class DeviceVmanageConfig(NetBoxModel):
    """Edge wykryty w vManage oraz jawnie lub automatycznie dopasowany Site NetBox."""

    system_ip = models.GenericIPAddressField(unique=True, protocol="both")
    vmanage_uuid = models.CharField(max_length=100, blank=True)
    hostname = models.CharField(max_length=100)
    serial_number = models.CharField(max_length=100, blank=True)
    device_model = models.CharField(max_length=100, blank=True)
    vmanage_site_id = models.CharField(max_length=50, blank=True, db_index=True)
    vmanage_site_name = models.CharField(max_length=100, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    device_groups = models.JSONField(default=list, blank=True)
    reachability = models.CharField(max_length=30, blank=True)
    netbox_site = models.ForeignKey(
        to="dcim.Site", on_delete=models.SET_NULL, null=True, blank=True, related_name="vmanage_device_configs"
    )
    device = models.ForeignKey(
        to="dcim.Device", on_delete=models.SET_NULL, null=True, blank=True, related_name="vmanage_configs"
    )
    match_method = models.CharField(
        max_length=20, choices=MatchMethodChoices, default=MatchMethodChoices.UNMATCHED
    )
    # Flaga chroni ręczną decyzję administratora przed kolejnym automatycznym discovery.
    manual_site_override = models.BooleanField(
        default=False, help_text="Do not replace the selected NetBox Site during discovery."
    )
    # Nowe urządzenia są wyłączone, aby hub lub błędnie sklasyfikowany Edge nie został
    # automatycznie utworzony w NetBox.
    enabled = models.BooleanField(
        default=False,
        help_text="Edge devices are discovered disabled so hubs cannot be imported without an explicit decision.",
    )
    interface_selection = models.JSONField(
        default=dict,
        blank=True,
        help_text="Per-interface synchronization choices keyed by normalized interface name.",
    )
    interfaces_last_refreshed = models.DateTimeField(null=True, blank=True)
    cached_vrrp_groups = models.JSONField(default=list, blank=True)
    last_discovered = models.DateTimeField(null=True, blank=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_sync_status = models.CharField(max_length=20, choices=SyncStatusChoices, blank=True)
    last_sync_message = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ("hostname", "system_ip")
        verbose_name = "Cisco SD-WAN Edge configuration"
        verbose_name_plural = "Cisco SD-WAN Edge configurations"

    def __str__(self):
        return f"{self.hostname} ({self.system_ip})"

    def get_absolute_url(self):
        return reverse("plugins:netbox_cisco_sync:devicevmanageconfig_edit", args=[self.pk])


class VmanageSyncConfig(NetBoxModel):
    """Singleton z połączeniem vManage i globalnym zachowaniem synchronizacji."""

    base_url = models.URLField(
        default="",
        help_text="Base URL of the vManage instance, for example https://vmanage.example.com.",
    )
    username = models.CharField(max_length=150, blank=True)
    password = models.CharField(max_length=255, blank=True)
    verify_ssl = models.BooleanField(default=True)
    ca_bundle = models.CharField(max_length=500, blank=True)
    request_timeout = models.PositiveIntegerField(default=30)
    request_retries = models.PositiveSmallIntegerField(default=2)
    enabled = models.BooleanField(
        default=True,
        help_text="Enable the vManage integration, discovery, and scheduled synchronization.",
    )
    update_existing = models.BooleanField(default=False)
    sync_interfaces = models.BooleanField(default=True)
    ignore_disabled_interfaces = models.BooleanField(
        default=False,
        help_text=(
            "Do not synchronize interfaces whose vManage Admin Status is down. "
            "Their IP addresses, MAC addresses, and FHRP memberships are also skipped."
        ),
    )
    sync_ipv4 = models.BooleanField(default=True)
    ignore_rfc1918_wan_ips = models.BooleanField(
        default=False,
        help_text=(
            "Do not create RFC1918 IPv4 addresses on WAN interfaces. "
            "The interface is still synchronized and the skipped address is added to its description."
        ),
    )
    sync_ipv6 = models.BooleanField(default=True)
    sync_mac_addresses = models.BooleanField(default=True)
    set_primary_ips = models.BooleanField(default=True)
    preferred_primary_ipv4_interface = models.CharField(
        max_length=100,
        blank=True,
        default="",
        help_text=(
            "Optional exact interface name whose IPv4 address should be primary, for example Loopback1000. "
            "If missing or empty, the vManage system-ip is used."
        ),
    )
    sync_fhrp = models.BooleanField(default=True)
    gps_max_distance_km = models.DecimalField(max_digits=5, decimal_places=2, default=1)
    default_device_role = models.CharField(max_length=100, default="SD-WAN Edge")
    sync_interval_hours = models.PositiveIntegerField(default=0)
    history_keep_days = models.PositiveIntegerField(default=90)

    class Meta:
        verbose_name = "vManage Sync settings"
        verbose_name_plural = "vManage Sync settings"

    def __str__(self):
        return "vManage Sync settings"

    def get_absolute_url(self):
        return reverse("plugins:netbox_cisco_sync:settings")

    @classmethod
    def get(cls):
        # Pierwsze wejście do Settings tworzy rekord z bezpiecznymi wartościami domyślnymi.
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def save(self, *args, **kwargs):
        # Stały klucz wymusza jeden edytowalny rekord Settings bez zależności od silnika bazy.
        self.pk = 1
        return super().save(*args, **kwargs)


class CatalystCenterConfig(NetBoxModel):
    """Singleton połączenia i reguł synchronizacji Catalyst Center."""

    base_url = models.URLField(
        default="",
        help_text="Base URL, for example https://catalyst.example.com.",
    )
    username = models.CharField(max_length=150, blank=True)
    password = models.CharField(max_length=255, blank=True)
    verify_ssl = models.BooleanField(default=True)
    ca_bundle = models.CharField(max_length=500, blank=True)
    request_timeout = models.PositiveIntegerField(default=30)
    request_retries = models.PositiveSmallIntegerField(default=2)
    enabled = models.BooleanField(
        default=False,
        help_text="Enable the Catalyst Center integration, discovery, and scheduled synchronization.",
    )
    update_existing = models.BooleanField(default=False)
    sync_interfaces = models.BooleanField(default=True)
    ignore_disabled_interfaces = models.BooleanField(
        default=False,
        help_text=(
            "Do not synchronize interfaces reported as administratively disabled by Catalyst Center. "
            "Their IP addresses, MAC addresses, and FHRP memberships are also skipped."
        ),
    )
    sync_ipv4 = models.BooleanField(default=True)
    ignore_rfc1918_wan_ips = models.BooleanField(
        default=False,
        help_text=(
            "Do not create RFC1918 IPv4 addresses on WAN interfaces. "
            "The interface is still synchronized and the skipped address is added to its description."
        ),
    )
    sync_ipv6 = models.BooleanField(default=False)
    sync_mac_addresses = models.BooleanField(default=False)
    set_primary_ips = models.BooleanField(default=True)
    preferred_primary_ipv4_interface = models.CharField(
        max_length=100,
        blank=True,
        default="Management",
        help_text=(
            "Optional exact interface name whose IPv4 address should be primary. "
            "Catalyst Center management addresses use the virtual Management interface."
        ),
    )
    import_device_roles = models.CharField(
        "Import only these Catalyst Center Families or Roles",
        max_length=500,
        blank=True,
        default="",
        help_text=(
            "Optional comma-separated filter. Each value is matched against either the exact Catalyst Center "
            "Family (for example Switches and Hubs, Routers) or the exact Role (for example ACCESS, CORE), "
            "case-insensitively. A device is imported when any value matches. Leave blank to import all "
            "supported devices."
        ),
    )
    sync_fhrp = models.BooleanField(default=False)
    gps_max_distance_km = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=1,
        help_text="Maximum distance between a Catalyst Center Building and a NetBox Site for GPS matching.",
    )
    default_device_role = models.CharField(max_length=100, default="Branches Access Switches")
    sync_interval_hours = models.PositiveIntegerField(default=0)
    history_keep_days = models.PositiveIntegerField(default=90)

    class Meta:
        verbose_name = "Catalyst Center settings"
        verbose_name_plural = "Catalyst Center settings"

    def __str__(self):
        return "Catalyst Center settings"

    def get_absolute_url(self):
        return reverse("plugins:netbox_cisco_sync:catalyst_settings")

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def save(self, *args, **kwargs):
        self.pk = 1
        return super().save(*args, **kwargs)


class DeviceCatalystCenterConfig(NetBoxModel):
    """Urządzenie CCC wykryte i dopasowane do istniejącego Site NetBox."""

    catalyst_id = models.CharField(max_length=100, unique=True)
    management_ip = models.GenericIPAddressField(null=True, blank=True, protocol="both")
    hostname = models.CharField(max_length=100)
    serial_number = models.CharField(max_length=100, blank=True)
    switch_stack_serials = models.JSONField(default=list, blank=True)
    switch_stack_info = models.JSONField(default=list, blank=True)
    device_model = models.CharField(max_length=100, blank=True)
    catalyst_site_id = models.CharField(max_length=100, blank=True, db_index=True)
    catalyst_site_name = models.CharField(max_length=200, blank=True)
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    reachability = models.CharField(max_length=30, blank=True)
    catalyst_role = models.CharField(max_length=100, blank=True)
    catalyst_family = models.CharField(max_length=100, blank=True)
    netbox_site = models.ForeignKey(
        to="dcim.Site", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="catalyst_center_device_configs",
    )
    device = models.ForeignKey(
        to="dcim.Device", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="catalyst_center_configs",
    )
    match_method = models.CharField(
        max_length=20, choices=MatchMethodChoices, default=MatchMethodChoices.UNMATCHED,
    )
    manual_site_override = models.BooleanField(default=False)
    enabled = models.BooleanField(default=False)
    interface_selection = models.JSONField(
        default=dict,
        blank=True,
        help_text="Per-interface synchronization choices keyed by normalized interface name.",
    )
    interfaces_last_refreshed = models.DateTimeField(null=True, blank=True)
    cached_vrrp_groups = models.JSONField(default=list, blank=True)
    last_discovered = models.DateTimeField(null=True, blank=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_sync_status = models.CharField(max_length=20, choices=SyncStatusChoices, blank=True)
    last_sync_message = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ("hostname", "management_ip")
        verbose_name = "Catalyst Center device configuration"
        verbose_name_plural = "Catalyst Center device configurations"

    @property
    def system_ip(self):
        return self.management_ip

    def __str__(self):
        return f"{self.hostname} ({self.management_ip or 'no management IP'})"

    def get_absolute_url(self):
        return reverse(
            "plugins:netbox_cisco_sync:devicecatalystcenterconfig_edit",
            args=[self.pk],
        )

class MerakiConfig(NetBoxModel):
    """Ustawienia połączenia i synchronizacji Cisco Meraki Dashboard."""

    enabled = models.BooleanField(
        default=False,
        help_text="Enable the Meraki integration, discovery, and scheduled synchronization.",
    )
    base_url = models.URLField(default="https://api.meraki.com/api/v1")
    api_key = models.CharField(max_length=255, blank=True)
    organization_ids = models.CharField(
        max_length=1000,
        blank=True,
        help_text="Optional comma-separated organization IDs. Leave blank to use all accessible organizations.",
    )
    request_timeout = models.PositiveIntegerField(default=30)
    request_retries = models.PositiveSmallIntegerField(default=2)
    update_existing = models.BooleanField(default=False)
    sync_interfaces = models.BooleanField(default=True)
    ignore_disabled_interfaces = models.BooleanField(default=False)
    sync_ipv4 = models.BooleanField(default=True)
    ignore_rfc1918_wan_ips = models.BooleanField(
        default=False,
        help_text=(
            "Do not create RFC1918 IPv4 addresses on WAN interfaces. "
            "The interface is still synchronized and the skipped address is added to its description."
        ),
    )
    sync_ipv6 = models.BooleanField(default=False)
    sync_mac_addresses = models.BooleanField(default=False)
    set_primary_ips = models.BooleanField(default=True)
    preferred_primary_ipv4_interface = models.CharField(max_length=100, blank=True, default="Management")
    import_device_families = models.CharField(
        "Import only these Meraki product families",
        max_length=500,
        blank=True,
        default="",
        help_text=(
            "Optional comma-separated filter matched against the exact Meraki product family, for example "
            "MS, MX, MR, MG, MV, MT. Matching is case-insensitive. Leave blank to import all devices."
        ),
    )
    gps_max_distance_km = models.DecimalField(max_digits=5, decimal_places=2, default=1)
    default_device_role = models.CharField(max_length=100, default="Branches Access Switches")
    sync_interval_hours = models.PositiveIntegerField(default=0)
    history_keep_days = models.PositiveIntegerField(default=90)

    class Meta:
        verbose_name = "Meraki settings"
        verbose_name_plural = "Meraki settings"

    def __str__(self):
        return "Meraki settings"

    def get_absolute_url(self):
        return reverse("plugins:netbox_cisco_sync:meraki_settings")

    @classmethod
    def get(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj

    def save(self, *args, **kwargs):
        self.pk = 1
        return super().save(*args, **kwargs)


class DeviceMerakiConfig(NetBoxModel):
    """Urządzenie wykryte w Meraki wraz z mapowaniem Network do NetBox Site."""

    serial_number = models.CharField(max_length=100, unique=True)
    hostname = models.CharField(max_length=100)
    device_model = models.CharField(max_length=100, blank=True)
    product_family = models.CharField(max_length=20, blank=True)
    firmware = models.CharField(max_length=100, blank=True)
    network_id = models.CharField(max_length=100, blank=True, db_index=True)
    network_name = models.CharField(max_length=200, blank=True)
    management_ip = models.GenericIPAddressField(null=True, blank=True, protocol="both")
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=10, decimal_places=6, null=True, blank=True)
    netbox_site = models.ForeignKey(
        to="dcim.Site", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="meraki_device_configs",
    )
    device = models.ForeignKey(
        to="dcim.Device", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="meraki_configs",
    )
    match_method = models.CharField(max_length=20, choices=MatchMethodChoices, default=MatchMethodChoices.UNMATCHED)
    manual_site_override = models.BooleanField(default=False)
    enabled = models.BooleanField(default=False)
    interface_selection = models.JSONField(
        default=dict,
        blank=True,
        help_text="Per-interface synchronization choices keyed by normalized interface name.",
    )
    interfaces_last_refreshed = models.DateTimeField(null=True, blank=True)
    cached_vrrp_groups = models.JSONField(default=list, blank=True)
    last_discovered = models.DateTimeField(null=True, blank=True)
    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_sync_status = models.CharField(max_length=20, choices=SyncStatusChoices, blank=True)
    last_sync_message = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ("hostname", "serial_number")
        verbose_name = "Meraki device configuration"
        verbose_name_plural = "Meraki device configurations"

    def __str__(self):
        return f"{self.hostname} ({self.serial_number})"

    def get_absolute_url(self):
        return reverse("plugins:netbox_cisco_sync:devicemerakiconfig_edit", args=[self.pk])


class DiscoveredInterface(NetBoxModel):
    """Cache interfejsu pobranego z jednej z obsługiwanych platform."""

    vmanage_config = models.ForeignKey(
        DeviceVmanageConfig,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="cached_interfaces",
    )
    catalyst_config = models.ForeignKey(
        DeviceCatalystCenterConfig,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="cached_interfaces",
    )
    meraki_config = models.ForeignKey(
        DeviceMerakiConfig,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="cached_interfaces",
    )
    name = models.CharField(max_length=255)
    normalized_name = models.CharField(max_length=255)
    description = models.CharField(max_length=500, blank=True)
    label = models.CharField(max_length=255, blank=True)
    interface_type = models.CharField(max_length=50, blank=True)
    admin_up = models.BooleanField(default=True)
    oper_up = models.BooleanField(default=False)
    mac_address = models.CharField(max_length=64, blank=True)
    ipv4_address = models.CharField(max_length=64, blank=True)
    ipv4_mask = models.CharField(max_length=64, blank=True)
    ipv6_addresses = models.JSONField(default=list, blank=True)
    mtu = models.PositiveIntegerField(null=True, blank=True)
    speed_mbps = models.FloatField(null=True, blank=True)
    vpn_id = models.CharField(max_length=100, blank=True)
    mode = models.CharField(max_length=30, blank=True)
    untagged_vlan = models.PositiveIntegerField(null=True, blank=True)
    tagged_vlans = models.JSONField(default=list, blank=True)
    bridge_name = models.CharField(max_length=255, blank=True)
    selected = models.BooleanField(default=True)
    present = models.BooleanField(default=True)
    last_seen = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("name",)
        constraints = (
            models.CheckConstraint(
                condition=(
                    (
                        models.Q(vmanage_config__isnull=False)
                        & models.Q(catalyst_config__isnull=True)
                        & models.Q(meraki_config__isnull=True)
                    )
                    | (
                        models.Q(vmanage_config__isnull=True)
                        & models.Q(catalyst_config__isnull=False)
                        & models.Q(meraki_config__isnull=True)
                    )
                    | (
                        models.Q(vmanage_config__isnull=True)
                        & models.Q(catalyst_config__isnull=True)
                        & models.Q(meraki_config__isnull=False)
                    )
                ),
                name="cisco_sync_interface_exactly_one_config",
            ),
            models.UniqueConstraint(
                fields=("vmanage_config", "normalized_name"),
                condition=models.Q(vmanage_config__isnull=False),
                name="cisco_sync_unique_vmanage_interface",
            ),
            models.UniqueConstraint(
                fields=("catalyst_config", "normalized_name"),
                condition=models.Q(catalyst_config__isnull=False),
                name="cisco_sync_unique_catalyst_interface",
            ),
            models.UniqueConstraint(
                fields=("meraki_config", "normalized_name"),
                condition=models.Q(meraki_config__isnull=False),
                name="cisco_sync_unique_meraki_interface",
            ),
        )

    def __str__(self):
        config = (
            self.vmanage_config
            or self.catalyst_config
            or self.meraki_config
        )
        return f"{config} · {self.name}"


class SyncRun(NetBoxModel):
    """Pojedynczy compare/apply wraz z licznikami, danymi źródłowymi i wynikiem."""

    config = models.ForeignKey(
        DeviceVmanageConfig, on_delete=models.SET_NULL, null=True, blank=True, related_name="sync_runs"
    )
    catalyst_config = models.ForeignKey(
        DeviceCatalystCenterConfig,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sync_runs",
    )
    meraki_config = models.ForeignKey(
        DeviceMerakiConfig, on_delete=models.SET_NULL, null=True, blank=True, related_name="sync_runs"
    )
    device = models.ForeignKey(
        to="dcim.Device", on_delete=models.SET_NULL, null=True, blank=True, related_name="vmanage_sync_runs"
    )
    trigger = models.CharField(max_length=20, choices=SyncTriggerChoices, default=SyncTriggerChoices.MANUAL)
    mode = models.CharField(max_length=20, choices=SyncModeChoices, default=SyncModeChoices.COMPARE)
    status = models.CharField(max_length=20, choices=SyncStatusChoices, default=SyncStatusChoices.OK)
    devices_created = models.PositiveIntegerField(default=0)
    devices_updated = models.PositiveIntegerField(default=0)
    interfaces_created = models.PositiveIntegerField(default=0)
    interfaces_updated = models.PositiveIntegerField(default=0)
    ips_created = models.PositiveIntegerField(default=0)
    macs_created = models.PositiveIntegerField(default=0)
    fhrp_groups_created = models.PositiveIntegerField(default=0)
    message = models.TextField(blank=True)
    # Nie nazywamy pola ``snapshot``: NetBoxModel udostępnia metodę snapshot(),
    # wywoływaną m.in. przed usunięciem obiektu na potrzeby change logu.
    source_data = models.JSONField(default=dict, blank=True)
    reverted = models.BooleanField(default=False)

    class Meta:
        ordering = ("-created",)

    def __str__(self):
        return f"{self.config or self.catalyst_config or self.meraki_config or self.device or 'Cisco'} · {self.mode} · {self.status}"

    def get_absolute_url(self):
        return reverse("plugins:netbox_cisco_sync:syncrun", args=[self.pk])

    @property
    def can_revert(self):
        return not self.reverted and self.created_objects.exists()

    def revert(self):
        """Usuń tylko obiekty utworzone przez run; nigdy nie cofaj wcześniejszych danych."""
        # Kolejność usuwa najpierw obiekty zależne. Dzięki temu IP nie blokuje FHRP,
        # a interfejs nie blokuje usunięcia nowo utworzonego Device.
        pending = []
        for row in sorted(
            self.created_objects.all(),
            key=lambda item: REVERT_DELETE_PRIORITY.get(item.object_type.model, 99),
        ):
            model = row.object_type.model_class()
            instance = model.objects.filter(pk=row.object_id).first() if model else None
            if instance is not None:
                pending.append(instance)

        deleted = 0
        progress = True
        # Kilka przebiegów obsługuje relacje RESTRICT, np. subinterfejs musi zostać
        # usunięty przed interfejsem nadrzędnym niezależnie od kolejności zapisu.
        while pending and progress:
            progress = False
            blocked = []
            for instance in pending:
                try:
                    instance.delete()
                    deleted += 1
                    progress = True
                except (ProtectedError, RestrictedError):
                    blocked.append(instance)
            pending = blocked
        self.reverted = True
        self.save(update_fields=("reverted", "last_updated"))
        return deleted


class SyncRunObject(models.Model):
    run = models.ForeignKey(SyncRun, on_delete=models.CASCADE, related_name="created_objects")
    # Nie potrzebujemy relacji ContentType -> SyncRunObject. Jej wyłączenie zapobiega
    # kolizji z identycznie nazwanym modelem SyncRunObject w pluginie netbox-snmp-sync.
    object_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, related_name="+")
    object_id = models.PositiveBigIntegerField()
    object_repr = models.CharField(max_length=200, blank=True)


class SyncRunChange(models.Model):
    run = models.ForeignKey(SyncRun, on_delete=models.CASCADE, related_name="changes")
    action = models.CharField(max_length=20)
    object_type = models.CharField(max_length=50)
    object_repr = models.CharField(max_length=200)
    field = models.CharField(max_length=80, blank=True)
    old_value = models.TextField(blank=True)
    new_value = models.TextField(blank=True)
    message = models.TextField(blank=True)


def record_created_objects(run, objects):
    """Zapisz referencje do obiektów, które wolno później bezpiecznie usunąć przez revert."""
    for obj in objects:
        SyncRunObject.objects.create(
            run=run,
            object_type=ContentType.objects.get_for_model(type(obj)),
            object_id=obj.pk,
            object_repr=str(obj)[:200],
        )


def record_changes(run, changes):
    """Zapisz różnice pól do audytu; aktualizacje nie są automatycznie cofane."""
    for change in changes:
        SyncRunChange.objects.create(run=run, **change)
