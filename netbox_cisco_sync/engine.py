"""Publiczna fasada modułowego silnika synchronizacji.

Widoki i zadania zachowują dotychczasowy import z ``engine``. Implementacja jest
podzielona domenowo w pakiecie ``netbox_cisco_sync.sync``.
"""

from .sync import SyncResult, sync_collected_device

__all__ = ("SyncResult", "sync_collected_device")
