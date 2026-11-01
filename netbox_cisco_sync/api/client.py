"""Compatibility exports for the former vManage API client location."""

from ..connectors.vmanage.client import VmanageClient, VmanageError

__all__ = ("VmanageClient", "VmanageError")
