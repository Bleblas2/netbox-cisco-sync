from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("netbox_cisco_sync", "0003_catalyst_interface_cache_mode"),
    ]

    operations = [
        migrations.AddField(
            model_name="discoveredinterface",
            name="bridge_name",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
