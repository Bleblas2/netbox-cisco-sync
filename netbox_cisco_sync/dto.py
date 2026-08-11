"""Obiekty transportowe oddzielające format API od silnika zapisującego do NetBox."""

from dataclasses import asdict, dataclass, field


@dataclass
class CollectedInterface:
    """Znormalizowany interfejs niezależny od różnic między platformami vManage."""
    name: str
    description: str = ""
    label: str = ""
    interface_type: str = ""
    admin_up: bool = True
    oper_up: bool = False
    mac_address: str = ""
    ipv4_address: str = ""
    ipv4_mask: str = ""
    ipv6_addresses: list[str] = field(default_factory=list)
    mtu: int | None = None
    speed_mbps: float | None = None
    vpn_id: str = ""
    mode: str = ""
    untagged_vlan: int | None = None
    tagged_vlans: list[int] = field(default_factory=list)
    bridge_name: str = ""
    # None oznacza brak zapisanej decyzji i użycie domyślnych reguł platformy.
    selected: bool | None = None
    present: bool = True
    last_seen: str = ""
    netbox_type: str = ""
    effective_speed_mbps: float | None = None


@dataclass
class CollectedVrrp:
    """Minimalny zestaw danych potrzebny do FHRPGroup i FHRPGroupAssignment."""
    interface_name: str
    group_id: int
    version: str
    virtual_ip: str
    master_ip: str = ""
    virtual_mac: str = ""
    priority: int | None = None


@dataclass
class CollectedDevice:
    """Kompletny snapshot jednego Edge używany przez preview i apply."""
    system_ip: str
    hostname: str
    uuid: str = ""
    serial_number: str = ""
    model: str = ""
    site_id: str = ""
    site_name: str = ""
    latitude: float | None = None
    longitude: float | None = None
    device_groups: list[str] = field(default_factory=list)
    reachability: str = ""
    interfaces: list[CollectedInterface] = field(default_factory=list)
    vrrp_groups: list[CollectedVrrp] = field(default_factory=list)
    role_name: str = ""
    platform_name: str = ""
    platform_slug: str = ""
    device_type_part_number: str = ""
    require_existing_device_type: bool = False
    status: str = "active"
    source_role: str = ""
    source_family: str = ""

    def to_dict(self):
        # Snapshot zawiera wyłącznie proste typy JSON, więc może być bezpiecznie zapisany
        # w SyncRun i później użyty przez apply bez ponownego odpytywania vManage.
        return asdict(self)


def device_from_dict(value):
    """Odtwórz DTO z zaufanego snapshotu zapisanego wcześniej w SyncRun."""
    payload = dict(value)
    payload["interfaces"] = [CollectedInterface(**row) for row in payload.get("interfaces", [])]
    payload["vrrp_groups"] = [CollectedVrrp(**row) for row in payload.get("vrrp_groups", [])]
    return CollectedDevice(**payload)
