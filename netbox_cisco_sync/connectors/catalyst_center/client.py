"""Klient REST Catalyst Center oparty na sprawdzonym przepływie tokenowym."""

import time

import requests

from ..base import ConnectorError


class CatalystCenterError(ConnectorError):
    """Kontrolowany błąd komunikacji prezentowany użytkownikowi w NetBox."""


class CatalystCenterClient:
    def __init__(self, settings):
        # Poświadczenia pozostają wyłącznie w obiekcie klienta. Treść wyjątków
        # zawiera endpoint i status HTTP, ale nigdy nazwę użytkownika ani hasło.
        self.base_url = settings.base_url.rstrip("/")
        self.username = settings.username
        self.password = settings.password
        self.timeout = settings.request_timeout
        self.retries = settings.request_retries
        self.session = requests.Session()
        self.session.verify = settings.ca_bundle or settings.verify_ssl
        self.session.headers.update({"Accept": "application/json"})

    def login(self):
        """Pobierz token i skonfiguruj jedną sesję dla dalszych odczytów."""
        if not self.base_url:
            raise CatalystCenterError("Catalyst Center base URL is required.")
        if not self.username or not self.password:
            raise CatalystCenterError("Catalyst Center username and password are required.")
        response = self._request(
            "post",
            "/dna/system/api/v1/auth/token",
            auth=(self.username, self.password),
        )
        if not response.ok:
            raise CatalystCenterError(f"Catalyst Center login failed (HTTP {response.status_code}).")
        try:
            token = response.json().get("Token") or response.json().get("token")
        except ValueError as exc:
            raise CatalystCenterError("Catalyst Center login did not return JSON.") from exc
        if not token:
            raise CatalystCenterError("Catalyst Center login response did not contain a token.")
        # Catalyst Center akceptuje token w X-Auth-Token. Zapisanie go w Session
        # gwarantuje identyczną autoryzację wszystkich kolejnych zapytań GET.
        self.session.headers.update({"X-Auth-Token": token, "Content-Type": "application/json"})
        return self

    def get_devices(self):
        return self._response("/dna/intent/api/v1/network-device")

    def get_sites(self):
        return self._response("/dna/intent/api/v1/site")

    def get_site_membership(self, site_id):
        """Spłaszcz grupowaną odpowiedź membership do listy urządzeń Building."""
        payload = self._json(f"/dna/intent/api/v1/membership/{site_id}")
        device = payload.get("device", []) if isinstance(payload, dict) else []
        rows = []
        for group in device:
            if isinstance(group, dict):
                rows.extend(group.get("response", []))
        return rows

    def get_device_interfaces(self, device_id):
        """Pobierz interfejsy raportowane dla jednego urządzenia sieciowego."""
        return self._response(
            f"/dna/intent/api/v1/interface/network-device/{device_id}"
        )

    def get_device_chassis(self, device_id):
        """Pobierz fizyczne chassis, z których CCC buduje logiczny stack."""
        return self._response(
            f"/dna/intent/api/v1/network-device/{device_id}/equipment?type=Chassis"
        )

    def _response(self, path):
        # Endpointy Intent API opakowują właściwą listę w polu ``response``.
        payload = self._json(path)
        return payload.get("response", []) if isinstance(payload, dict) else []

    def _json(self, path):
        response = self._request("get", path)
        if not response.ok:
            snippet = response.text[:300].replace("\n", " ")
            raise CatalystCenterError(f"GET {path} failed (HTTP {response.status_code}): {snippet}")
        try:
            return response.json()
        except ValueError as exc:
            raise CatalystCenterError(f"GET {path} did not return JSON.") from exc

    def _request(self, method, path, **kwargs):
        """Ponów wyłącznie przejściowe błędy transportu, nie błędy HTTP."""
        url = f"{self.base_url}{path}"
        last_error = None
        for attempt in range(self.retries + 1):
            try:
                return self.session.request(method, url, timeout=self.timeout, **kwargs)
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_error = exc
                if attempt < self.retries:
                    # Krótki wykładniczy backoff ogranicza obciążenie kontrolera,
                    # a maksymalnie pięć sekund nie blokuje długo workera NetBox.
                    time.sleep(min(2**attempt, 5))
        raise CatalystCenterError(f"Catalyst Center request failed: {last_error}") from last_error
