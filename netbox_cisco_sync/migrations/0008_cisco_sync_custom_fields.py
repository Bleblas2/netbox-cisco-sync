from django.db import migrations


def configure_cisco_sync_custom_fields(apps, schema_editor):
    """Utwórz pola stacka i pogrupuj wszystkie standardowe pola pluginu."""
    content_type_model = apps.get_model("contenttypes", "ContentType")
    custom_field_model = apps.get_model("extras", "CustomField")
    device_type = content_type_model.objects.get(app_label="dcim", model="device")
    site_type = content_type_model.objects.get(app_label="dcim", model="site")

    definitions = (
        (
            "SwitchStackSerials",
            device_type,
            {
                "type": "text",
                "label": "Switch Stack Serials",
                "description": "",
                "validation_regex": r"^[A-Z0-9.*/-]+(?:,[A-Z0-9.*/-]+)*$",
                "search_weight": 300,
            },
        ),
        (
            "SwitchStackInfo",
            device_type,
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
        (
            "SdwanSiteId",
            site_type,
            {
                "type": "text",
                "label": "SD-WAN Site ID",
                "description": "Cisco vManage Site ID synchronized during Apply.",
            },
        ),
        (
            "MerakiSiteId",
            site_type,
            {
                "type": "text",
                "label": "Meraki Site Id",
                "description": "Meraki Dashboard Network ID synchronized during Apply.",
            },
        ),
    )
    common = {
        "required": False,
        "weight": 100,
        "group_name": "Cisco Sync",
        "ui_visible": "if-set",
        "ui_editable": "yes",
        "is_cloneable": False,
    }
    for name, object_type, specific in definitions:
        custom_field, _ = custom_field_model.objects.update_or_create(
            name=name,
            defaults={**common, **specific},
        )
        custom_field.object_types.add(object_type)


class Migration(migrations.Migration):

    dependencies = [
        ("netbox_cisco_sync", "0007_catalyst_stack_metadata"),
    ]

    operations = [
        migrations.RunPython(
            configure_cisco_sync_custom_fields,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
