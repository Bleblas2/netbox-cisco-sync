"""Wynik synchronizacji i wspólne operacje rejestrowania zmian."""

from dataclasses import dataclass, field


@dataclass
class SyncResult:
    """Liczniki, ostrzeżenia i obiekty potrzebne do historii oraz revertu."""

    devices_created: int = 0
    devices_updated: int = 0
    interfaces_created: int = 0
    interfaces_updated: int = 0
    ips_created: int = 0
    macs_created: int = 0
    fhrp_groups_created: int = 0
    created_objects: list = field(default_factory=list)
    synced_objects: list = field(default_factory=list)
    changes: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    skipped: bool = False

    @property
    def message(self):
        # Jednoliniowe podsumowanie jest używane w UI i historii Sync Runs.
        counts = (
            f"devices +{self.devices_created}/~{self.devices_updated}, "
            f"interfaces +{self.interfaces_created}/~{self.interfaces_updated}, "
            f"IPs +{self.ips_created}, MACs +{self.macs_created}, "
            f"FHRP +{self.fhrp_groups_created}"
        )
        return counts + (("; " + "; ".join(self.warnings)) if self.warnings else "")


def record_synced_object(result, obj):
    """Zapamiętaj obiekt objęty Apply bez wielokrotnego tagowania tej samej instancji."""
    if obj not in result.synced_objects:
        result.synced_objects.append(obj)


def update_fields(instance, values, result):
    """Zapisz tylko rzeczywiste różnice i zarejestruj je do SyncRunChange."""
    changed_fields = []
    for field_name, new_value in values.items():
        old_value = getattr(instance, field_name)
        if old_value != new_value:
            result.changes.append({
                "action": "update",
                "object_type": instance._meta.model_name,
                "object_repr": str(instance)[:200],
                "field": field_name,
                "old_value": str(old_value),
                "new_value": str(new_value),
                "message": "",
            })
            setattr(instance, field_name, new_value)
            changed_fields.append(field_name)
    if changed_fields:
        instance.save(update_fields=changed_fields)
