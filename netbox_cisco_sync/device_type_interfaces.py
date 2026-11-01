"""Odczyt szablonów interfejsów wspólny dla connectorów."""

from dcim.models import DeviceType


def interface_templates_for_part_number(part_number):
    """Zwróć szablony typu o dokładnym numerze katalogowym, bez zapisu do bazy."""
    if not part_number:
        return []
    matches = list(DeviceType.objects.filter(part_number=part_number)[:2])
    if len(matches) > 1:
        raise ValueError(f"Multiple Device Types use part number {part_number}.")
    if not matches:
        return []
    return list(matches[0].interfacetemplates.values_list("name", "type"))
