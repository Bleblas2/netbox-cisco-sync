"""Klient REST Catalyst Center oparty na sprawdzonym przepływie tokenowym."""

import requests

from ..base import ConnectorError, init_controller_client
from ...request_limits import request_with_retries


class CatalystCenterError(ConnectorError):
    """Kontrolowany błąd komunikacji prezentowany użytkownikowi w NetBox."""


class CatalystCenterClient:
    def __init__(self, settings):
        init_controller_client(self, settings)

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

    def get_site_assigned_devices(self, site_id):
        """Pobierz stronicowaną listę urządzeń Building wraz z jego Floor."""
        path = "/dna/intent/api/v1/networkDevices/assignedToSite"
        offset = 1
        limit = 500
        rows = []
        while True:
            response = self._request(
                "get",
                path,
                params={"siteId": site_id, "offset": offset, "limit": limit},
            )
            # Starsze wersje CCC nie mają tego endpointu. Connector przejdzie
            # wtedy do historycznego membership mapowanego po serialu.
            if response.status_code in {404, 405, 501}:
                return None
            if response.status_code == 204:
                return rows
            if not response.ok:
                snippet = response.text[:300].replace("\n", " ")
                raise CatalystCenterError(
                    f"GET {path} failed (HTTP {response.status_code}): {snippet}"
                )
            try:
                payload = response.json()
            except ValueError as exc:
                raise CatalystCenterError(f"GET {path} did not return JSON.") from exc
            page = payload.get("response", []) if isinstance(payload, dict) else []
            if not isinstance(page, list):
                page = []
            rows.extend(row for row in page if isinstance(row, dict))
            if len(page) < limit:
                return rows
            offset += len(page)

    def get_device_interfaces(self, device_id):
        """Pobierz interfejsy raportowane dla jednego urządzenia sieciowego."""
        return self._response(
            f"/dna/intent/api/v1/interface/network-device/{device_id}"
        )

    def get_port_channel(self, device_id, interface_id):
        """Odczytaj członków LAG po identyfikatorze z listy interfejsów CCC."""
        payload = self._json(
            f"/dna/intent/api/v1/networkDevices/{device_id}/portChannels/{interface_id}"
        )
        value = payload.get("response") if isinstance(payload, dict) else None
        if not isinstance(value, dict) or "interfaces" not in value:
            raise CatalystCenterError("Port channel response did not contain membership data.")
        return value

    def get_device_stack(self, device_id):
        """Pobierz szczegóły członków stacka dla jednego urządzenia."""
        paths = (
            f"/dna/intent/api/v1/network-device/{device_id}/stack",
            f"/api/v1/network-device/{device_id}/stack",
        )
        for index, path in enumerate(paths):
            response = self._request("get", path)
            if response.status_code in {204, 404} and index < len(paths) - 1:
                continue
            if response.status_code in {204, 404}:
                return {}
            if not response.ok:
                snippet = response.text[:300].replace("\n", " ")
                raise CatalystCenterError(
                    f"GET {path} failed (HTTP {response.status_code}): {snippet}"
                )
            try:
                payload = response.json()
            except ValueError as exc:
                raise CatalystCenterError(f"GET {path} did not return JSON.") from exc
            result = payload.get("response", {}) if isinstance(payload, dict) else {}
            return result if isinstance(result, dict) else {}
        return {}

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
        """Wykonaj żądanie przez wspólną obsługę limitów i retry."""
        url = f"{self.base_url}{path}"
        try:
            return request_with_retries(
                lambda timeout: self.session.request(method, url, timeout=timeout, **kwargs),
                self.timeout, self.retries,
            )
        except (requests.ConnectionError, requests.Timeout) as exc:
            raise CatalystCenterError(f"Catalyst Center request failed: {exc}") from exc
