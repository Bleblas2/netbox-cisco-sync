"""Deterministyczne reguły dopasowania Site z vManage do Site w NetBox."""

import math
import re

from .choices import MatchMethodChoices
from .plugin_settings import plugin_setting


def normalize_site_name(value):
    """Ujednolić separatory, wielkość liter i nadmiarowe spacje w nazwie Site."""
    return " ".join(re.sub(r"[-_]", " ", value or "").casefold().split())


def distance_km(lat1, lon1, lat2, lon2):
    """Policz odległość po powierzchni Ziemi bez dodatkowych bibliotek geograficznych."""
    radius = 6371.0088
    phi1, phi2 = math.radians(float(lat1)), math.radians(float(lat2))
    dphi = math.radians(float(lat2) - float(lat1))
    dlambda = math.radians(float(lon2) - float(lon1))
    value = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(value), math.sqrt(1 - value))


def match_site(device, sites, max_distance_km=1, *, use_custom_field=True):
    """Zastosuj kolejno SdwanSiteId, nazwę i GPS; wynik musi być jednoznaczny."""
    sites = list(sites)
    site_id_field = plugin_setting("vmanage_site_id_field")
    # Puste ID nie może dopasować Site z pustym custom field, bo zablokowałoby
    # poprawne przejście do dopasowania po nazwie albo GPS.
    by_id = [
        site for site in sites
        if use_custom_field
        and device.site_id
        and str((site.custom_field_data or {}).get(site_id_field) or "") == device.site_id
    ]
    if len(by_id) == 1:
        return by_id[0], MatchMethodChoices.CUSTOM_FIELD

    wanted_name = normalize_site_name(device.site_name)
    by_name = [site for site in sites if wanted_name and normalize_site_name(site.name) == wanted_name]
    if len(by_name) == 1:
        return by_name[0], MatchMethodChoices.NAME

    # GPS jest ostatnią automatyczną metodą i działa tylko dla kompletu współrzędnych.
    if device.latitude is None or device.longitude is None:
        return None, MatchMethodChoices.UNMATCHED
    candidates = []
    for site in sites:
        if site.latitude is None or site.longitude is None:
            continue
        distance = distance_km(device.latitude, device.longitude, site.latitude, site.longitude)
        if distance <= float(max_distance_km):
            candidates.append((distance, site))
    candidates.sort(key=lambda item: item[0])
    if not candidates:
        return None, MatchMethodChoices.UNMATCHED
    # Prawie identyczne odległości uznajemy za konflikt, zamiast wybierać rekord
    # przypadkowo według kolejności zwróconej przez bazę.
    if len(candidates) > 1 and abs(candidates[0][0] - candidates[1][0]) < 0.001:
        return None, MatchMethodChoices.UNMATCHED
    return candidates[0][1], MatchMethodChoices.GPS
