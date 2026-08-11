from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("netbox_cisco_sync", "0004_discovered_interface_bridge"),
    ]

    operations = [
        migrations.AddField(
            model_name="discoveredinterface",
            name="label",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
