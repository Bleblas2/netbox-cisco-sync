"""Klient tylko do odczytu dla Cisco Meraki Dashboard API v1."""

import requests

from ..base import ConnectorError
from ...request_limits import request_with_retries


class MerakiError(ConnectorError):
    """Błąd komunikacji Meraki bez ujawniania klucza API."""


class MerakiClient:
    def __init__(self, settings):
        # Klucz API trafia wyłącznie do nagłówka sesji i nie jest dołączany
        # do komunikatów błędów ani parametrów URL.
        self.base_url = settings.base_url.rstrip("/")
        self.api_key = settings.api_key
        self.timeout = settings.request_timeout
        self.retries = settings.request_retries
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "X-Cisco-Meraki-API-Key": self.api_key,
        })

    def connect(self):
        """Sprawdź klucz bez wykonywania jakichkolwiek operacji zapisujących."""
        if not self.api_key:
            raise MerakiError("Meraki API key is required.")
        self.get_organizations()
        return self

    def get_organizations(self):
        return self._get("/organizations")

    def get_networks(self, organization_id):
        return self._get(f"/organizations/{organization_id}/networks", params={"perPage": 1000})

    def get_devices(self, network_id):
        return self._get(f"/networks/{network_id}/devices", params={"perPage": 1000})

    def get_device(self, serial):
        """Pobierz szczegóły jednego urządzenia, w tym adresy LAN/WAN dla MX."""
        return self._get(f"/devices/{serial}")

    def get_appliance_uplinks_settings(self, serial):
        """Pobierz konfigurację wszystkich interfejsów WAN urządzenia MX."""
        return self._get(f"/devices/{serial}/appliance/uplinks/settings")

    def get_switch_ports(self, serial):
        """Pobierz konfigurację wszystkich portów przełącznika MS."""
        return self._get(f"/devices/{serial}/switch/ports")

    def get_switch_port_statuses(self, serial):
        """Pobierz bieżący stan i prędkość portów MS."""
        return self._get(f"/devices/{serial}/switch/ports/statuses", params={"perPage": 1000})

    def get_appliance_vlan_settings(self, network_id):
        """Sprawdź tryb LAN przed wyborem endpointów konfiguracji MX."""
        return self._get(f"/networks/{network_id}/appliance/vlans/settings")

    def get_appliance_vlans(self, network_id):
        """Pobierz interfejsy L3 sieci MX z włączonymi VLAN-ami."""
        return self._get(f"/networks/{network_id}/appliance/vlans")

    def get_appliance_single_lan(self, network_id):
        """Pobierz konfigurację pojedynczej sieci LAN urządzenia MX."""
        return self._get(f"/networks/{network_id}/appliance/singleLan")

    def get_appliance_ports(self, network_id):
        """Pobierz konfigurację wszystkich fizycznych portów LAN urządzenia MX."""
        return self._get(f"/networks/{network_id}/appliance/ports")

    def _get(self, path, params=None):
        """Wykonaj GET przez wspólną obsługę limitów i retry."""
        url = f"{self.base_url}{path}"
        try:
            response = request_with_retries(
                lambda timeout: self.session.get(url, params=params, timeout=timeout),
                self.timeout, self.retries,
            )
        except (requests.ConnectionError, requests.Timeout) as exc:
            raise MerakiError(f"Meraki request failed: {exc}") from exc
        if not response.ok:
            snippet = response.text[:300].replace("\n", " ")
            raise MerakiError(f"GET {path} failed (HTTP {response.status_code}): {snippet}")
        try:
            return response.json()
        except ValueError as exc:
            raise MerakiError(f"GET {path} did not return JSON.") from exc
