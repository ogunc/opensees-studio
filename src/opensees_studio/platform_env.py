"""Session-level choices that must be made before Qt loads a platform plugin.

Kept Qt-free on purpose: this is read by the bootstrap *and* by tests that must
not pull Qt into the headless unit suite.
"""

from __future__ import annotations

import os
from collections.abc import MutableMapping


def prefer_xwayland_on_wayland(env: MutableMapping[str, str] | None = None) -> bool:
    """Choose XWayland for the 3D canvas when the session is Wayland.

    The canvas is a VTK render widget (PyVistaQt's ``QtInteractor``) — a native
    child window. Under a native Wayland session the compositor does not route
    pointer events into that child, so the canvas never sees a press: no
    orbiting, no selection, and no drawing, silently, because the event never
    arrives. XWayland, which every Wayland desktop ships, delivers them.

    An explicit ``QT_QPA_PLATFORM`` always wins, so a session that works, or a
    user who wants to test it, keeps their choice. Returns True when this
    function set the variable.
    """
    env = os.environ if env is None else env
    if env.get("QT_QPA_PLATFORM"):
        return False
    if not env.get("WAYLAND_DISPLAY") or env.get("DISPLAY") is None:
        # Not a Wayland session, or no X server to fall back to.
        return False
    env["QT_QPA_PLATFORM"] = "xcb"
    return True
