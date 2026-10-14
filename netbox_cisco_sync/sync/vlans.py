"""Przypisanie istniejących VLAN-ów z Site urządzenia do portów."""

from django.contrib.contenttypes.models import ContentType
from django.db.models import Q

from .result import update_fields


def resolve_site_vlan(site, vid, result, interface_name):
    """Wybierz dokładnie jeden VLAN lokalny; konflikt nie może wybierać losowo."""
    from dcim.models import Site
    from ipam.models import VLAN

    site_type = ContentType.objects.get_for_model(Site)
    matches = list(VLAN.objects.filter(vid=vid).filter(
        Q(site=site)
        | Q(site__isnull=True, group__scope_type=site_type, group__scope_id=site.pk)
    ).distinct()[:2])
    if len(matches) == 1:
        return matches[0]
    reason = "not found" if not matches else "ambiguous"
    result.warnings.append(
        f"Interface {interface_name}: VLAN {vid} {reason} in Site {site}."
    )
    return None


def sync_interface_vlans(interface, row, site, result):
    """Zapisz VLAN access/native bez tworzenia VLAN-ów."""
    if row.mode not in {"access", "trunk", "tagged-all"}:
        return
    if row.untagged_vlan is not None:
        vlan = resolve_site_vlan(site, row.untagged_vlan, result, row.name)
        if vlan is not None:
            update_fields(interface, {"untagged_vlan": vlan}, result)
