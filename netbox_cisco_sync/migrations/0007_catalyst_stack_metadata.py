from django.db import migrations, models


def split_existing_stack_serials(apps, schema_editor):
    """Zachowaj zagregowane seriale ze starszych rekordów CCC."""
    config_model = apps.get_model(
        "netbox_cisco_sync",
        "DeviceCatalystCenterConfig",
    )
    for config in config_model.objects.iterator():
        serials = [
            value.strip()
            for value in str(config.serial_number or "").split(",")
            if value.strip()
        ]
        if len(serials) < 2:
            continue
        config.serial_number = serials[0]
        config.switch_stack_serials = serials[1:]
        config.save(update_fields=("serial_number", "switch_stack_serials"))


class Migration(migrations.Migration):

    dependencies = [
        ("netbox_cisco_sync", "0006_remove_catalyst_detailed_stacks"),
    ]

    operations = [
        migrations.AddField(
            model_name="devicecatalystcenterconfig",
            name="switch_stack_serials",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="devicecatalystcenterconfig",
            name="switch_stack_info",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.RunPython(
            split_existing_stack_serials,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
