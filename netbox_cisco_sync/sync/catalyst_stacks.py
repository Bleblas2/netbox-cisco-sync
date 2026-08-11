"""Szczegółowa reprezentacja stacków Catalyst Center w NetBox."""

import re
from dataclasses import replace

from ..models import CatalystStackMember, DeviceCatalystCenterConfig
from .addresses import candidate_ip_rows, sync_addresses
from .interfaces import sync_interfaces, syncable_interface_rows, valid_mac
from .orchestrator import ensure_device_prerequisites
from .result import SyncResult, record_synced_object, update_fields
from .tags import tag_synced_objects

STACK_PORT_NAMES = ("StackPort1/1", "StackPort1/2")
STACKWISE_INTERFACE_TYPE = "cisco-stackwise"
VC_PRIORITIES = (15, 14, 13, 12)


def is_detailed_catalyst_stack(config, data, settings):
    """Rozpoznaj stack CCC objęty szczegółową reprezentacją."""
    return (
        isinstance(config, DeviceCatalystCenterConfig)
        and getattr(settings, "stack_detailed", False) is True
        and len(data.stack_members) > 1
    )


def sync_detailed_catalyst_stack(config, data, settings, *, apply=False):
    """Porównaj albo zapisz członków, Virtual Chassis i pierścień StackWise."""
    from dcim.models import Device, VirtualChassis

    result = SyncResult()
    if not config.enabled:
        result.skipped = True
        result.warnings.append("Device is disabled in Catalyst Center Config")
        return result, None
    if not config.netbox_site_id:
        result.skipped = True
        result.warnings.append("No NetBox Site mapping")
        return result, None

    members = _validated_members(data)
    target_names = [f"{data.hostname}-{member.position}" for member in members]
    existing_members = {
        row.position: row
        for row in config.stack_members.filter(present=True).select_related("device")
    }
    devices = []
    for member, name in zip(members, target_names):
        mapping = existing_members.get(member.position)
        device = mapping.device if mapping and mapping.device_id else None
        name_match = Device.objects.filter(
            site=config.netbox_site, name__iexact=name
        ).first()
        serial_match = Device.objects.filter(serial=member.serial_number).first()
        if name_match and serial_match and name_match.pk != serial_match.pk:
            raise ValueError(
                f"Detailed stack member {member.position} has conflicting name and serial matches."
            )
        device = device or name_match or serial_match
        if device and device.site_id != config.netbox_site_id:
            raise ValueError(
                f"Serial number {member.serial_number} belongs to a Device in another Site."
            )
        devices.append(device)

    if config.device_id and config.device not in devices:
        raise ValueError(
            "The Catalyst record is already linked to a compact NetBox Device. "
            "Remove or migrate that representation before enabling detailed stacks."
        )
    if any(device is not None for device in devices) and not settings.update_existing:
        result.skipped = True
        result.warnings.append("Skipped: update existing disabled")
        return result, next((device for device in devices if device is not None), None)

    selected_rows = [
        row
        for row in syncable_interface_rows(data.interfaces, settings, config=config)
        if not re.fullmatch(r"StackPort\d+/\d+", row.name, re.IGNORECASE)
    ]
    result.devices_created = sum(device is None for device in devices)
    result.devices_updated = len(devices) - result.devices_created
    result.warnings.append(
        f"Detailed stack: {len(members)} members in Virtual Chassis {data.hostname}"
    )
    if not apply:
        result.interfaces_created = (
            len([row for row in selected_rows if row.name])
            + (2 * len(members))
        )
        result.ips_created = len(candidate_ip_rows(selected_rows))
        result.macs_created = len({
            row.mac_address.lower()
            for row in selected_rows
            if valid_mac(row.mac_address)
        })
        return result, devices[0] if devices else None

    virtual_chassis = VirtualChassis.objects.filter(name=data.hostname).first()
    if virtual_chassis is None:
        virtual_chassis = VirtualChassis.objects.create(name=data.hostname)
        result.created_objects.append(virtual_chassis)
    elif any(
        device and device.virtual_chassis_id not in (None, virtual_chassis.pk)
        for device in devices
    ):
        raise ValueError("A stack member already belongs to a different Virtual Chassis.")
    known_device_ids = {device.pk for device in devices if device is not None}
    if virtual_chassis.members.exclude(pk__in=known_device_ids).exists():
        raise ValueError(
            f"Virtual Chassis {data.hostname} already contains devices outside this Catalyst stack."
        )
    record_synced_object(result, virtual_chassis)

    saved_devices = []
    for index, (member, name, device) in enumerate(
        zip(members, target_names, devices), start=1
    ):
        _, device_type, role, platform = ensure_device_prerequisites(
            member.model,
            data.role_name or settings.default_device_role,
            result,
            platform_name=data.platform_name,
            platform_slug=data.platform_slug,
            part_number=member.model,
            require_existing_device_type=True,
        )
        values = {
            "name": name,
            "serial": member.serial_number,
            "device_type": device_type,
            "role": role,
            "platform": platform,
            "site": config.netbox_site,
            "status": data.status or "active",
            "virtual_chassis": virtual_chassis,
            "vc_position": member.position,
            "vc_priority": VC_PRIORITIES[index - 1] if index <= len(VC_PRIORITIES) else None,
        }
        if device is None:
            device = Device.objects.create(**values)
            result.created_objects.append(device)
        else:
            update_fields(device, values, result)
        record_synced_object(result, device)
        saved_devices.append(device)
        CatalystStackMember.objects.update_or_create(
            catalyst_config=config,
            position=member.position,
            defaults={
                "serial_number": member.serial_number,
                "device_model": member.model,
                "device": device,
                "present": True,
            },
        )

    master = saved_devices[0]
    if virtual_chassis.master_id != master.pk:
        virtual_chassis.master = master
        virtual_chassis.save(update_fields=("master",))

    interfaces_by_position = {}
    for member, device in zip(members, saved_devices):
        rows = [
            row for row in selected_rows
            if row.stack_member_position == member.position
            or (member.position == 1 and row.stack_member_position is None)
        ]
        member_data = replace(data, interfaces=rows)
        interfaces = sync_interfaces(device, rows, settings, result, config=config)
        sync_addresses(device, interfaces, member_data, settings, result)
        interfaces_by_position[member.position] = interfaces

    _configure_stack_ring(saved_devices, interfaces_by_position, result)
    tag_synced_objects(
        [*result.created_objects, *result.synced_objects],
        settings.tags.all(),
    )
    config.device = master
    return result, master


def _validated_members(data):
    members = sorted(data.stack_members, key=lambda member: member.position)
    positions = [member.position for member in members]
    if positions != list(range(1, len(members) + 1)):
        raise ValueError("Catalyst stack member positions must be consecutive and start at 1.")
    if any(not member.serial_number or not member.model for member in members):
        raise ValueError("Every Catalyst stack member requires an individual serial and model.")
    if len({member.serial_number for member in members}) != len(members):
        raise ValueError("Catalyst stack member serial numbers must be unique.")
    return members


def _stack_ports(device, known_interfaces, result):
    """Zwróć lub utworzyć dwa standardowe porty StackWise członka."""
    from dcim.models import Interface

    ports = {}
    for name in STACK_PORT_NAMES:
        interface = known_interfaces.get(name) or device.interfaces.filter(name=name).first()
        if interface is None:
            interface = Interface.objects.create(
                device=device,
                name=name,
                type=STACKWISE_INTERFACE_TYPE,
            )
            result.interfaces_created += 1
            result.created_objects.append(interface)
        elif interface.type != STACKWISE_INTERFACE_TYPE:
            raise ValueError(
                f"{device.name} {name} must use the Cisco StackWise interface type."
            )
        ports[name] = interface
        record_synced_object(result, interface)
    return ports


def _configure_stack_ring(devices, interfaces_by_position, result):
    """Połącz StackPort1/1 z StackPort1/2 następnego członka w pierścień."""
    from dcim.models import Cable

    ports = {
        position: _stack_ports(device, interfaces_by_position[position], result)
        for position, device in enumerate(devices, start=1)
    }
    for position, device in enumerate(devices, start=1):
        next_position = position + 1 if position < len(devices) else 1
        first = ports[position]["StackPort1/1"]
        second = ports[next_position]["StackPort1/2"]
        first_cable = first.cable
        second_cable = second.cable
        if first_cable or second_cable:
            if first_cable and second_cable and first_cable.pk == second_cable.pk:
                continue
            raise ValueError(
                f"Cannot connect {device.name} {first.name}: a StackWise port already has another cable."
            )
        cable = Cable(
            a_terminations=[first],
            b_terminations=[second],
            status="connected",
            label=f"StackWise {first.device.name} to {second.device.name}"[:100],
        )
        cable.full_clean()
        cable.save()
        result.created_objects.append(cable)
        record_synced_object(result, cable)
