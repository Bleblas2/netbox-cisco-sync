"""Przypisanie istniejących VLAN-ów z globalnej listy NetBox do portów."""

from .result import update_fields


def resolve_vlan(vid, result, interface_name):
    """Wybierz VLAN po VID, preferując branches, a potem najmniejsze ID."""
    from ipam.models import VLAN

    queryset = VLAN.objects.filter(vid=vid).order_by("pk")
    matches = list(queryset[:2])
    if len(matches) > 1:
        preferred = queryset.filter(group__slug="branches").first()
        return preferred or matches[0]
    if matches:
        return matches[0]
    result.warnings.append(f"Interface {interface_name}: VLAN {vid} not found in NetBox.")
    return None


def sync_interface_vlans(interface, row, result):
    """Zapisz VLAN access/native bez tworzenia VLAN-ów."""
    if row.mode not in {"access", "trunk", "tagged-all"}:
        return
    if row.untagged_vlan is not None:
        vlan = resolve_vlan(row.untagged_vlan, result, row.name)
        if vlan is not None:
            update_fields(interface, {"untagged_vlan": vlan}, result)
