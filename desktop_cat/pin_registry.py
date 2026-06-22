"""Tiny process-global handle to the live PinManager.

The window-pin engine (PinManager) is created in main.py's run scope, but
the Library-Hub QWebChannel bridge — which exposes pinning to the React
Settings UI — is constructed inside LibraryHubWindow and has no direct
reference to it.  Rather than thread the object through several layers,
main.py registers the instance here and the bridge reads it back.

Same process, single GUI thread, so this is just a shared reference — no
locking needed.
"""
from __future__ import annotations

from typing import Any

_PIN_MANAGER: Any = None
_OVERLAY: Any = None


def set_pin_manager(pm: Any) -> None:
    global _PIN_MANAGER
    _PIN_MANAGER = pm


def get_pin_manager() -> Any:
    return _PIN_MANAGER


def set_overlay(o: Any) -> None:
    """Register the CatOverlay so the hub bridge can reach it (e.g. to
    highlight a flower when the user hovers its to-do)."""
    global _OVERLAY
    _OVERLAY = o


def get_overlay() -> Any:
    return _OVERLAY
