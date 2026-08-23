from django.db import migrations, models


HELP_TEXT = (
    "Do not create RFC1918 IPv4 addresses on WAN interfaces. "
    "The interface is still synchronized and the skipped address is added to its description."
)


class Migration(migrations.Migration):

    dependencies = [
        ("netbox_cisco_sync", "0008_cisco_sync_custom_fields"),
    ]

    operations = [
        migrations.AddField(
            model_name="vmanagesyncconfig",
            name="ignore_rfc1918_wan_ips",
            field=models.BooleanField(default=False, help_text=HELP_TEXT),
        ),
        migrations.AddField(
            model_name="catalystcenterconfig",
            name="ignore_rfc1918_wan_ips",
            field=models.BooleanField(default=False, help_text=HELP_TEXT),
        ),
        migrations.AddField(
            model_name="merakiconfig",
            name="ignore_rfc1918_wan_ips",
            field=models.BooleanField(default=False, help_text=HELP_TEXT),
        ),
    ]
