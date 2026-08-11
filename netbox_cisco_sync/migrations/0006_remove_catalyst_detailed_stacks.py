from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("netbox_cisco_sync", "0005_discovered_interface_label"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="catalystcenterconfig",
            name="stack_detailed",
        ),
        migrations.RemoveField(
            model_name="devicecatalystcenterconfig",
            name="interfaces_stack_detailed",
        ),
        migrations.RemoveField(
            model_name="discoveredinterface",
            name="stack_member_position",
        ),
        migrations.DeleteModel(
            name="CatalystStackMember",
        ),
    ]
