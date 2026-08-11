from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("netbox_cisco_sync", "0002_catalyst_detailed_stacks"),
    ]

    operations = [
        migrations.AddField(
            model_name="devicecatalystcenterconfig",
            name="interfaces_stack_detailed",
            field=models.BooleanField(default=False),
        ),
    ]
