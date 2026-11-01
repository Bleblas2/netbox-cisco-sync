from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("netbox_cisco_sync", "0009_ignore_rfc1918_wan_ips")]

    operations = [
        migrations.AddField(
            model_name="discoveredinterface",
            name="lag_name",
            field=models.CharField(max_length=255, blank=True),
        ),
    ]
