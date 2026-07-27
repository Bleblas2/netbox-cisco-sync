"""Synchronizacja VRRP do grup, członkostw i adresów VIP NetBox."""

from django.contrib.contenttypes.models import ContentType
from django.utils.text import slugify

from .addresses import (
    ip_has_incomplete_assignment,
    ip_is_unassigned,
    ipv4_cidr,
    save_ip_assignment,
)
from .result import record_synced_object

# Wartość zapisywana w bazie dla etykiety „VRRP” z IPAddressRoleChoices NetBoxa.
VRRP_IP_ROLE = "vrrp"


def sync_fhrp(interfaces, data, ip_by_text, settings, result):
    """Odwzoruj VRRP na FHRPGroup, assignment interfejsu i VIP."""
    from ipam.models import FHRPGroup, FHRPGroupAssignment, IPAddress

    for row in data.vrrp_groups:
        interface = interfaces.get(row.interface_name)
        if interface is None or not row.virtual_ip:
            result.warnings.append(
                f"Skipped VRRP group {row.group_id}: interface not found"
            )
            continue
        protocol = "vrrp3" if "3" in row.version else "vrrp2"
        # Nazwa zawierająca Site i interfejs zapobiega połączeniu niezależnych
        # domen, ale łączy parę routerów używających tej samej grupy w Site.
        group_name = slugify(
            f"{interface.device.site.slug}-{row.interface_name}-{row.group_id}"
        )[:100]
        group = FHRPGroup.objects.filter(
            protocol=protocol,
            group_id=row.group_id,
            name=group_name,
        ).first()
        if group is None:
            group = FHRPGroup.objects.create(
                protocol=protocol,
                group_id=row.group_id,
                name=group_name,
            )
            result.fhrp_groups_created += 1
            result.created_objects.append(group)
        record_synced_object(result, group)

        interface_type = ContentType.objects.get_for_model(interface)
        assignment = FHRPGroupAssignment.objects.filter(
            group=group,
            interface_type=interface_type,
            interface_id=interface.pk,
        ).first()
        if assignment is None:
            assignment = FHRPGroupAssignment.objects.create(
                group=group,
                interface_type=interface_type,
                interface_id=interface.pk,
                priority=row.priority if row.priority is not None else 100,
            )
            result.created_objects.append(assignment)
        elif settings.update_existing and assignment.priority != row.priority:
            assignment.priority = row.priority
            assignment.save(update_fields=("priority",))
        record_synced_object(result, assignment)

        # Endpoint VRRP nie podaje prefiksu VIP. Dziedziczymy go z adresu
        # członkowskiego interfejsu, na którym działa grupa.
        cidr = vrrp_cidr(row, data.interfaces)
        if not cidr:
            continue
        vip = IPAddress.objects.filter(address=cidr).first()
        if vip is None:
            vip = IPAddress(address=cidr, status="active", role=VRRP_IP_ROLE)
            save_ip_assignment(vip, group)
            result.ips_created += 1
            result.created_objects.append(vip)
        elif ip_is_unassigned(vip) and settings.update_existing:
            save_ip_assignment(vip, group)
        elif ip_has_incomplete_assignment(vip):
            result.warnings.append(
                f"VIP {cidr} has an incomplete object assignment; skipped"
            )
        elif vip.assigned_object != group:
            result.warnings.append(f"VIP {cidr} is already assigned to another object")

        if vip.assigned_object == group:
            # Przy Update existing poprawiamy również historyczne adresy zapisane
            # z ogólną rolą VIP na precyzyjną rolę VRRP.
            if settings.update_existing and vip.role != VRRP_IP_ROLE:
                vip.role = VRRP_IP_ROLE
                vip.save(update_fields=("role",))
            record_synced_object(result, vip)
            ip_by_text[row.virtual_ip] = vip


def vrrp_cidr(vrrp, interface_rows):
    """Nadaj VIP taki sam prefiks, jaki ma adres członkowski interfejsu VRRP."""
    source = next(
        (row for row in interface_rows if row.name == vrrp.interface_name),
        None,
    )
    if source is None:
        return None
    base = ipv4_cidr(source.ipv4_address, source.ipv4_mask)
    return f"{vrrp.virtual_ip}/{base.rsplit('/', 1)[1]}" if base else None
