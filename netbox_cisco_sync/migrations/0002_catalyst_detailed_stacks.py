import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("netbox_cisco_sync", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="catalystcenterconfig",
            name="stack_detailed",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "Represent every Catalyst Center switch stack member as a separate NetBox Device "
                    "in a Virtual Chassis. When disabled, preserve the stack as one Device."
                ),
                verbose_name="Detailed stack representation",
            ),
        ),
        migrations.AddField(
            model_name="discoveredinterface",
            name="stack_member_position",
            field=models.PositiveSmallIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="discoveredinterface",
            name="mode",
            field=models.CharField(blank=True, max_length=30),
        ),
        migrations.AddField(
            model_name="discoveredinterface",
            name="untagged_vlan",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="discoveredinterface",
            name="tagged_vlans",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.CreateModel(
            name="CatalystStackMember",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False)),
                ("position", models.PositiveSmallIntegerField()),
                ("serial_number", models.CharField(max_length=100)),
                ("device_model", models.CharField(max_length=100)),
                ("present", models.BooleanField(default=True)),
                (
                    "catalyst_config",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="stack_members",
                        to="netbox_cisco_sync.devicecatalystcenterconfig",
                    ),
                ),
                (
                    "device",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="catalyst_stack_members",
                        to="dcim.device",
                    ),
                ),
            ],
            options={"ordering": ("catalyst_config", "position")},
        ),
        migrations.AddConstraint(
            model_name="catalyststackmember",
            constraint=models.UniqueConstraint(
                fields=("catalyst_config", "position"),
                name="cisco_sync_unique_catalyst_stack_position",
            ),
        ),
    ]
