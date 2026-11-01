"""Klient vManage wykorzystujący sprawdzony mechanizm sesji JSESSIONID i token XSRF."""

import requests

from ..base import ConnectorError, init_controller_client
from ...request_limits import request_with_retries


class VmanageError(ConnectorError):
    """Kontrolowany błąd komunikacji prezentowany użytkownikowi w interfejsie NetBox."""

    pass


class VmanageClient:
    def __init__(self, settings):
        init_controller_client(self, settings)

    def login(self):
        """Zaloguj sesję w dwóch krokach i przygotuj ją do zapytań dataservice."""
        if not self.base_url:
            raise VmanageError("vManage base URL is required in Settings.")
        if not self.username or not self.password:
            raise VmanageError("vManage username and password are required in Settings.")
        # vManage oczekuje formularza, a nie JSON. Poprawna odpowiedź powinna ustawić
        # cookie JSESSIONID w obiekcie Session.
        response = self._request(
            "post",
            "/j_security_check",
            data={"j_username": self.username, "j_password": self.password},
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if not response.ok or not self.session.cookies.get("JSESSIONID"):
            raise VmanageError(f"vManage login failed (HTTP {response.status_code}).")
        # Token XSRF jest pobierany już z cookie JSESSIONID. Zachowujemy go w sesji,
        # dzięki czemu wszystkie dalsze metody korzystają z identycznej autoryzacji.
        token = self._request("get", "/dataservice/client/token")
        if not token.ok or not token.text.strip():
            raise VmanageError(f"Could not obtain vManage XSRF token (HTTP {token.status_code}).")
        self.session.headers.update({"X-XSRF-TOKEN": token.text.strip(), "Content-Type": "application/json"})
        return self

    def get_devices(self):
        """Pobierz wspólną listę kontrolerów i urządzeń Edge; filtracja jest w collectorze."""
        return self._json("/dataservice/device").get("data", [])

    def get_interfaces(self, system_ip):
        """Pobierz interfejsy jednego Edge wskazanego przez jego system-ip."""
        return self._json("/dataservice/device/interface", params={"deviceId": system_ip}).get("data", [])

    def get_vrrp(self, system_ip):
        """Pobierz operacyjne grupy VRRP potrzebne do utworzenia obiektów FHRP."""
        return self._json("/dataservice/device/vrrp", params={"deviceId": system_ip}).get("data", [])

    def _json(self, path, **kwargs):
        # Ograniczamy fragment błędnej odpowiedzi, aby duża strona HTML z proxy lub
        # load balancera nie trafiła w całości do komunikatu NetBox.
        response = self._request("get", path, **kwargs)
        if not response.ok:
            snippet = response.text[:300].replace("\n", " ")
            raise VmanageError(f"GET {path} failed (HTTP {response.status_code}): {snippet}")
        try:
            return response.json()
        except ValueError as exc:
            raise VmanageError(f"GET {path} did not return JSON.") from exc

    def _request(self, method, path, **kwargs):
        """Wykonaj żądanie przez wspólną obsługę limitów i retry."""
        url = f"{self.base_url}{path}"
        try:
            return request_with_retries(
                lambda timeout: self.session.request(method, url, timeout=timeout, **kwargs),
                self.timeout, self.retries,
            )
        except (requests.ConnectionError, requests.Timeout) as exc:
            raise VmanageError(f"vManage request failed: {exc}") from exc
