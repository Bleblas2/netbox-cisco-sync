"""Deterministyczne reguły dopasowania Site z vManage do Site w NetBox."""

import ipaddress
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


def site_prefix_bindings(sites):
    """Pobierz raz prefiksy, których scope wskazuje bezpośrednio na podane Site."""
    from django.contrib.contenttypes.models import ContentType
    from dcim.models import Site
    from ipam.models import Prefix

    sites_by_id = {
        site.pk: site
        for site in sites
        if getattr(site, "pk", None) is not None
    }
    if not sites_by_id:
        return []
    site_type = ContentType.objects.get_for_model(Site)
    return [
        (str(prefix.prefix), sites_by_id[prefix.scope_id])
        for prefix in Prefix.objects.filter(
            scope_type=site_type,
            scope_id__in=sites_by_id,
        ).only("prefix", "scope_id")
    ]


def match_site_by_primary_ip(value, prefix_bindings):
    """Dopasuj Site przez najbardziej szczegółowy przypisany prefiks IP."""
    try:
        address = ipaddress.ip_address(str(value or "").split("/", 1)[0])
    except ValueError:
        return None

    candidates = []
    for prefix_value, site in prefix_bindings or ():
        try:
            network = ipaddress.ip_network(str(prefix_value), strict=False)
        except ValueError:
            continue
        if network.version == address.version and address in network:
            candidates.append((network.prefixlen, site))
    if not candidates:
        return None

    closest_prefixlen = max(prefixlen for prefixlen, _ in candidates)
    closest_sites = {
        getattr(site, "pk", None) or id(site): site
        for prefixlen, site in candidates
        if prefixlen == closest_prefixlen
    }
    return next(iter(closest_sites.values())) if len(closest_sites) == 1 else None


def match_site(
    device,
    sites,
    max_distance_km=1,
    *,
    use_custom_field=True,
    custom_field_name=None,
    prefix_bindings=(),
):
    """Zastosuj kolejno identyfikator źródła, nazwę, GPS i primary IP."""
    sites = list(sites)
    # Platforma wskazuje własne pole identyfikatora. Brak parametru zachowuje
    # dotychczasowy kontrakt vManage i zgodność ze starszymi wywołaniami.
    site_id_field = custom_field_name or plugin_setting("vmanage_site_id_field")
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

    if device.latitude is not None and device.longitude is not None:
        candidates = []
        for site in sites:
            if site.latitude is None or site.longitude is None:
                continue
            distance = distance_km(device.latitude, device.longitude, site.latitude, site.longitude)
            if distance <= float(max_distance_km):
                candidates.append((distance, site))
        candidates.sort(key=lambda item: item[0])
        # Prawie identyczne odległości uznajemy za konflikt i przechodzimy do IP.
        if candidates and not (
            len(candidates) > 1
            and abs(candidates[0][0] - candidates[1][0]) < 0.001
        ):
            return candidates[0][1], MatchMethodChoices.GPS

    site = match_site_by_primary_ip(
        getattr(device, "system_ip", ""),
        prefix_bindings,
    )
    if site is not None:
        return site, MatchMethodChoices.PRIMARY_IP
    return None, MatchMethodChoices.UNMATCHED
