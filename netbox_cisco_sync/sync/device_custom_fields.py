"""Custom Fields urządzenia zarządzane przez Cisco Sync."""

from .result import record_synced_object, update_fields

STACK_SERIALS_FIELD = "SwitchStackSerials"
STACK_INFO_FIELD = "SwitchStackInfo"


def sync_switch_stack_fields(device, data, result):
    """Zapisz pozostałe seriale i pełny stackSwitchInfo na Device."""
    from django.contrib.contenttypes.models import ContentType
    from dcim.models import Device
    from extras.models import CustomField

    definitions = (
        (
            STACK_SERIALS_FIELD,
            {
                "type": "text",
                "label": "Switch Stack Serials",
                "description": "",
                "validation_regex": r"^[A-Z0-9.*/-]+(?:,[A-Z0-9.*/-]+)*$",
                "search_weight": 300,
            },
        ),
        (
            STACK_INFO_FIELD,
            {
                "type": "json",
                "label": "Switch Stack info",
                "description": (
                    "Switch stack membership in the Cisco Catalyst Center "
                    "stackSwitchInfo format."
                ),
                "validation_regex": "",
                "search_weight": 0,
            },
        ),
    )
    device_content_type = ContentType.objects.get_for_model(Device)
    for name, specific in definitions:
        defaults = {
            **specific,
            "required": False,
            "weight": 100,
            "group_name": "Cisco Sync",
            "ui_visible": "if-set",
            "ui_editable": "yes",
            "filter_logic": "loose",
            "is_cloneable": False,
        }
        custom_field, _ = CustomField.objects.get_or_create(name=name, defaults=defaults)
        changed = []
        for field, value in defaults.items():
            if getattr(custom_field, field) != value:
                setattr(custom_field, field, value)
                changed.append(field)
        if changed:
            custom_field.save(update_fields=changed)
        if not custom_field.object_types.filter(pk=device_content_type.pk).exists():
            custom_field.object_types.add(device_content_type)

    stack_info = list(data.switch_stack_info or [])
    stack_serials = ",".join(data.switch_stack_serials or [])
    values = dict(device.custom_field_data or {})
    if stack_serials:
        values[STACK_SERIALS_FIELD] = stack_serials
    else:
        values.pop(STACK_SERIALS_FIELD, None)
    if stack_serials and stack_info:
        values[STACK_INFO_FIELD] = stack_info
    else:
        values.pop(STACK_INFO_FIELD, None)
    update_fields(device, {"custom_field_data": values}, result)
    record_synced_object(result, device)
