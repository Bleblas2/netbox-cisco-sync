"""Wspólna obsługa budżetu czasu i ograniczeń Cisco API."""

from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import math
import time

from rq.timeouts import JobTimeoutException

_deadline = ContextVar("cisco_sync_deadline", default=None)


@contextmanager
def session_time_budget(seconds):
    """Udostępnij klientom API pozostały czas jednej sesji synchronizacji."""
    token = _deadline.set(time.monotonic() + seconds)
    try:
        yield
    finally:
        _deadline.reset(token)


def request_timeout(configured):
    """Ogranicz pojedyncze żądanie pozostałym czasem sesji."""
    deadline = _deadline.get()
    if deadline is None:
        return configured
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise JobTimeoutException("Synchronization time budget exhausted.")
    return min(configured, remaining)


def retry_delay(response, fallback=1):
    """Odczytaj Retry-After jako liczbę sekund albo datę HTTP."""
    value = str(response.headers.get("Retry-After", "")).strip()
    try:
        delay = float(value)
        if math.isfinite(delay) and delay >= 0:
            return delay
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return max(0, (when - datetime.now(timezone.utc)).total_seconds())
    except (ValueError, TypeError, OverflowError):
        return fallback


def wait_before_retry(delay):
    """Nie skracaj opóźnienia serwera; zakończ sesję, jeśli brakuje czasu."""
    deadline = _deadline.get()
    if deadline is not None and time.monotonic() + delay >= deadline:
        raise JobTimeoutException("Retry-After exceeds the remaining synchronization time budget.")
    time.sleep(delay)


def request_with_retries(send, timeout, retries):
    """Ponawiaj błędy transportu i HTTP 429 wspólnie dla trzech platform."""
    import requests

    for attempt in range(retries + 1):
        try:
            response = send(request_timeout(timeout))
        except (requests.ConnectionError, requests.Timeout):
            if attempt >= retries:
                raise
            wait_before_retry(min(2**attempt, 5))
            continue
        if response.status_code == 429 and attempt < retries:
            wait_before_retry(retry_delay(response, min(2**attempt, 5)))
            continue
        return response
