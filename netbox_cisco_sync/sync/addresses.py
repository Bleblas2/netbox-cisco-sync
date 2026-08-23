"""Synchronizacja adresów IP, primary IP i integralności przypisań NetBox."""

import ipaddress

from django.contrib.contenttypes.models import ContentType

from .result import record_synced_object
from .wan import ignored_rfc1918_wan_cidr


def sync_addresses(device, interfaces, data, settings, result):
    """Zapisz adresy z prefiksami, zachowując pojedyncze przypisanie IP."""
    from ipam.models import IPAddress

    ip_by_text = {}
    used = set()
    # Port fizyczny lub subinterfejs ma pierwszeństwo przed Tunnel, ponieważ
    # vManage potrafi zwrócić identyczny adres na obu obiektach.
    ordered = sorted(
        data.interfaces,
        key=lambda row: (row.name.lower().startswith("tunnel"), row.name),
    )
    for row in ordered:
        interface = interfaces.get(row.name)
        if interface is None:
            continue
        addresses = []
        if settings.sync_ipv4:
            cidr = ipv4_cidr(row.ipv4_address, row.ipv4_mask)
            if cidr and cidr != ignored_rfc1918_wan_cidr(row, settings):
                addresses.append(cidr)
        if settings.sync_ipv6:
            # Nie zgadujemy prefiksu IPv6. Adres bez /prefix zostaje pominięty.
            addresses.extend(value for value in row.ipv6_addresses if "/" in value)
            if any(value and "/" not in value for value in row.ipv6_addresses):
                result.warnings.append(f"Skipped IPv6 without prefix on {row.name}")
        for cidr in addresses:
            bare = str(ipaddress.ip_interface(cidr).ip)
            if bare in used:
                result.warnings.append(f"Skipped duplicate IP {bare} on {row.name}")
                continue
            used.add(bare)
            ip_obj = IPAddress.objects.filter(address=cidr).first()
            if ip_obj is None:
                ip_obj = IPAddress(address=cidr, status="active")
                save_ip_assignment(ip_obj, interface)
                result.ips_created += 1
                result.created_objects.append(ip_obj)
            elif ip_is_unassigned(ip_obj) and settings.update_existing:
                save_ip_assignment(ip_obj, interface)
            elif ip_has_incomplete_assignment(ip_obj):
                # Nie zgadujemy brakującej połowy GenericForeignKey.
                result.warnings.append(
                    f"IP {cidr} has an incomplete object assignment; skipped"
                )
            elif ip_obj.assigned_object_id and ip_obj.assigned_object != interface:
                result.warnings.append(f"IP {cidr} is already assigned to another object")
            if not ip_has_incomplete_assignment(ip_obj) and ip_obj.assigned_object == interface:
                record_synced_object(result, ip_obj)
            ip_by_text[bare] = ip_obj

    if settings.set_primary_ips:
        set_primary_ips(device, interfaces, data, settings, ip_by_text, result)
    return ip_by_text


def set_primary_ips(device, interfaces, data, settings, ip_by_text, result):
    """Wybierz preferowany primary IPv4 i pierwszy użyteczny globalny IPv6."""
    preferred_name = (settings.preferred_primary_ipv4_interface or "").strip()
    preferred_row = (
        next(
            (row for row in data.interfaces if row.name.casefold() == preferred_name.casefold()),
            None,
        )
        if preferred_name
        else None
    )

    primary = None
    if preferred_row:
        preferred_cidr = ipv4_cidr(preferred_row.ipv4_address, preferred_row.ipv4_mask)
        if preferred_cidr:
            preferred_ip = str(ipaddress.ip_interface(preferred_cidr).ip)
            candidate = ip_by_text.get(preferred_ip)
            preferred_interface = interfaces.get(preferred_row.name)
            if candidate and candidate.assigned_object == preferred_interface:
                primary = candidate
        if primary is None:
            result.warnings.append(
                f"Preferred primary IPv4 interface {preferred_name} has no usable assigned IPv4; "
                "falling back to system-ip"
            )
    elif preferred_name:
        result.warnings.append(
            f"Preferred primary IPv4 interface {preferred_name} was not returned by vManage; "
            "falling back to system-ip"
        )

    primary = primary or ip_by_text.get(data.system_ip)
    if primary and primary.assigned_object in interfaces.values():
        if device.primary_ip4_id != primary.pk:
            device.primary_ip4 = primary
            device.save(update_fields=("primary_ip4",))

    ipv6_primary = next(
        (
            ip_obj
            for bare, ip_obj in ip_by_text.items()
            if ipaddress.ip_address(bare).version == 6
            and ipaddress.ip_address(bare).is_global
            and ip_obj.assigned_object in interfaces.values()
        ),
        None,
    )
    if ipv6_primary and device.primary_ip6_id != ipv6_primary.pk:
        device.primary_ip6 = ipv6_primary
        device.save(update_fields=("primary_ip6",))


def save_ip_assignment(ip_obj, assigned_object):
    """Zapisz obie części GenericForeignKey i przerwij transakcję przy niespójności."""
    expected_type = ContentType.objects.get_for_model(assigned_object)
    ip_obj.assigned_object = assigned_object
    if (
        ip_obj.assigned_object_type_id != expected_type.pk
        or ip_obj.assigned_object_id != assigned_object.pk
    ):
        raise RuntimeError(f"Could not prepare a complete assignment for IP {ip_obj.address}")

    if ip_obj.pk is None:
        ip_obj.save()
    else:
        ip_obj.save(update_fields=("assigned_object_type", "assigned_object_id"))

    # Apply działa w transaction.atomic(), więc niespójność wycofa cały zestaw.
    if (
        ip_obj.assigned_object_type_id != expected_type.pk
        or ip_obj.assigned_object_id != assigned_object.pk
    ):
        raise RuntimeError(f"IP {ip_obj.address} was saved with an incomplete object assignment")


def ip_is_unassigned(ip_obj):
    """Prawidłowo nieprzypisany IP ma puste oba pola GenericForeignKey."""
    return ip_obj.assigned_object_type_id is None and ip_obj.assigned_object_id is None


def ip_has_incomplete_assignment(ip_obj):
    """Wykryj stan type bez ID albo ID bez type, który psuje tabele NetBox."""
    return (ip_obj.assigned_object_type_id is None) != (ip_obj.assigned_object_id is None)


def candidate_ip_rows(rows, settings=None):
    """Policz unikalne adresy, które mogą pojawić się w preview."""
    values = set()
    for row in rows:
        cidr = ipv4_cidr(row.ipv4_address, row.ipv4_mask)
        if cidr and not (
            settings is not None
            and cidr == ignored_rfc1918_wan_cidr(row, settings)
        ):
            values.add(str(ipaddress.ip_interface(cidr).ip))
        values.update(value for value in row.ipv6_addresses if "/" in value)
    return values


def ipv4_cidr(address, mask):
    """Przelicz maskę dziesiętną vManage na zapis CIDR wymagany przez NetBox."""
    if not address or address in {"0.0.0.0", "-"} or not mask or mask == "0.0.0.0":
        return None
    try:
        prefix = ipaddress.IPv4Network(f"0.0.0.0/{mask}").prefixlen
        return f"{address}/{prefix}"
    except (ipaddress.AddressValueError, ipaddress.NetmaskValueError):
        return None
