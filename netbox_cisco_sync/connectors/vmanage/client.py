"""Klient vManage wykorzystujący sprawdzony mechanizm sesji JSESSIONID i token XSRF."""

import time

import requests

from ..base import ConnectorError


class VmanageError(ConnectorError):
    """Kontrolowany błąd komunikacji prezentowany użytkownikowi w interfejsie NetBox."""

    pass


class VmanageClient:
    def __init__(self, settings):
        # Dane dostępowe pochodzą wyłącznie z singletonu Settings. Nie zapisujemy ich
        # w nagłówkach diagnostycznych ani w treści wyjątków.
        self.base_url = settings.base_url.rstrip("/")
        self.username = settings.username
        self.password = settings.password
        self.timeout = settings.request_timeout
        self.retries = settings.request_retries
        # Jedna sesja jest konieczna, ponieważ cookie otrzymane podczas logowania musi
        # zostać automatycznie użyte przy pobieraniu tokena i kolejnych zapytaniach.
        self.session = requests.Session()
        # Podanie ścieżki CA ma pierwszeństwo przed prostym przełącznikiem verify_ssl.
        self.session.verify = settings.ca_bundle or settings.verify_ssl
        self.session.headers.update({"Accept": "application/json"})

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
        """Wykonaj request z krótkim retry tylko dla timeoutów i błędów połączenia."""
        url = f"{self.base_url}{path}"
        last_error = None
        for attempt in range(self.retries + 1):
            try:
                return self.session.request(method, url, timeout=self.timeout, **kwargs)
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_error = exc
                if attempt < self.retries:
                    # Krótki backoff chroni vManage przed gwałtowną serią ponowień,
                    # ale nie blokuje workera na długi czas.
                    time.sleep(min(2**attempt, 5))
        raise VmanageError(f"vManage request failed: {last_error}") from last_error
