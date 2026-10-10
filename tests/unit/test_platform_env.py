"""Which Qt platform plugin the app asks for, and why.

A Wayland session plus a VTK canvas is a combination that silently swallows
mouse input: the canvas is a native child window and the compositor does not
route pointer events into it, so nothing orbits, nothing selects and nothing is
drawn — with no error to show for it. XWayland delivers the events.
"""

from __future__ import annotations

from opensees_studio.platform_env import prefer_xwayland_on_wayland


def test_a_wayland_session_with_xwayland_available_gets_xcb() -> None:
    env = {"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0"}
    assert prefer_xwayland_on_wayland(env) is True
    assert env["QT_QPA_PLATFORM"] == "xcb"


def test_an_explicit_choice_always_wins() -> None:
    env = {"WAYLAND_DISPLAY": "wayland-0", "DISPLAY": ":0", "QT_QPA_PLATFORM": "wayland"}
    assert prefer_xwayland_on_wayland(env) is False
    assert env["QT_QPA_PLATFORM"] == "wayland"


def test_a_wayland_session_without_xwayland_is_left_alone() -> None:
    """Nothing to fall back to: forcing xcb would not start at all."""
    env = {"WAYLAND_DISPLAY": "wayland-0"}
    assert prefer_xwayland_on_wayland(env) is False
    assert "QT_QPA_PLATFORM" not in env


def test_an_x11_session_is_left_alone() -> None:
    env = {"DISPLAY": ":0"}
    assert prefer_xwayland_on_wayland(env) is False
    assert "QT_QPA_PLATFORM" not in env


def test_a_headless_session_is_left_alone() -> None:
    """No display at all: the offscreen platform is the caller's business."""
    env: dict[str, str] = {}
    assert prefer_xwayland_on_wayland(env) is False
    assert env == {}
