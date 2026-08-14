"""Aktualizacja danych Site wynikających z zaakceptowanego Apply."""

from ..plugin_settings import plugin_setting
from .result import record_synced_object, update_fields

SDWAN_SITE_ID_FIELD = plugin_setting("vmanage_site_id_field")
MERAKI_SITE_ID_FIELD = plugin_setting("meraki_site_id_field")


def sync_site_sdwan_id(config, settings, result):
    """Zapewnij Custom Field i zsynchronizuj vManage Site ID na Site."""
    _sync_site_source_id(
        site=config.netbox_site,
        source_id=config.vmanage_site_id,
        field_name=plugin_setting("vmanage_site_id_field"),
        field_label="SD-WAN Site ID",
        field_description="Cisco vManage Site ID synchronized during Apply.",
        update_existing=settings.update_existing,
        result=result,
    )


def sync_site_meraki_id(config, settings, result):
    """Zapewnij Custom Field i zsynchronizuj Meraki Network ID na Site."""
    _sync_site_source_id(
        site=config.netbox_site,
        source_id=config.network_id,
        field_name=plugin_setting("meraki_site_id_field"),
        field_label="Meraki Site Id",
        field_description="Meraki Dashboard Network ID synchronized during Apply.",
        update_existing=settings.update_existing,
        result=result,
    )


def _sync_site_source_id(
    *,
    site,
    source_id,
    field_name,
    field_label,
    field_description,
    update_existing,
    result,
):
    """Utwórz pole Site i zapisz identyfikator źródła z ochroną istniejącej wartości."""
    from django.contrib.contenttypes.models import ContentType
    from dcim.models import Site
    from extras.models import CustomField

    site_id = str(source_id or "").strip()
    # Apply bez Site jest zatrzymywany wcześniej. Pustego ID nie zapisujemy, aby
    # nie kasować poprawnej wartości, która może już istnieć w NetBox.
    if site is None or not site_id:
        return

    custom_field, _ = CustomField.objects.get_or_create(
        name=field_name,
        defaults={
            "label": field_label,
            "description": field_description,
            "type": "text",
            "required": False,
            "group_name": "Cisco Sync",
            "ui_visible": "if-set",
        },
    )
    custom_field_updates = []
    for field, value in {
        "group_name": "Cisco Sync",
        "ui_visible": "if-set",
    }.items():
        if getattr(custom_field, field) != value:
            setattr(custom_field, field, value)
            custom_field_updates.append(field)
    if custom_field_updates:
        custom_field.save(update_fields=custom_field_updates)
    site_content_type = ContentType.objects.get_for_model(Site)
    if not custom_field.object_types.filter(pk=site_content_type.pk).exists():
        custom_field.object_types.add(site_content_type)

    # Bez Update existing wartość ręczna lub pochodząca z innego procesu jest
    # chroniona. Po włączeniu tej opcji źródłem prawdy staje się dana platforma.
    if not should_update_site_id(site, update_existing, field_name=field_name):
        return

    values = {
        **(site.custom_field_data or {}),
        field_name: site_id,
    }
    # update_fields zapisuje tylko realną zmianę i dodaje ją do audytu Sync Run.
    update_fields(site, {"custom_field_data": values}, result)
    record_synced_object(result, site)


def site_has_source_id(site, field_name):
    """Zwróć True, jeśli Site ma już niepustą wartość wskazanego pola."""
    value = (site.custom_field_data or {}).get(field_name)
    return value is not None and bool(str(value).strip())


def site_has_sdwan_id(site):
    """Zwróć True, jeśli Site ma już niepustą wartość SdwanSiteId."""
    return site_has_source_id(site, plugin_setting("vmanage_site_id_field"))


def should_update_site_id(site, update_existing, field_name=None):
    """Uzupełnij brak albo nadpisz wartość, gdy zezwala na to Settings."""
    selected_field = field_name or plugin_setting("vmanage_site_id_field")
    return bool(update_existing) or not site_has_source_id(site, selected_field)
