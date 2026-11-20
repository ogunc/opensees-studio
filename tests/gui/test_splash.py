"""Start-up splash: shown before the heavy imports, gone once the window shows."""

from __future__ import annotations

import subprocess
import sys

import pytest
from PySide6.QtWidgets import QMainWindow

from opensees_studio.views import i18n
from opensees_studio.views import splash as splash_module
from opensees_studio.views.splash import LOGO, STAGES, show_splash

pytestmark = pytest.mark.gui


def test_the_logo_ships_with_the_package() -> None:
    assert LOGO.is_file()


def test_the_splash_closes_when_the_window_shows(qtbot) -> None:  # type: ignore[no-untyped-def]
    splash = show_splash()
    qtbot.addWidget(splash)
    assert splash.isVisible()
    assert splash.stage == STAGES[0]

    splash.advance(STAGES[1], 0.7)
    assert splash.stage == STAGES[1]

    window = QMainWindow()
    qtbot.addWidget(window)
    window.show()
    splash.finish_on(window)
    qtbot.waitUntil(lambda: not splash.isVisible(), timeout=5000)


def test_the_stages_are_translated(qtbot, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(splash_module, "stored_language", lambda: "es")
    splash = show_splash()
    qtbot.addWidget(splash)
    assert splash.stage == "Cargando el motor gráfico…"
    splash.close()


def test_the_app_module_imports_without_the_graphics_stack() -> None:
    """``opensees_studio.app`` must load fast so the splash can show first."""
    script = (
        "import sys, opensees_studio.app\n"
        "heavy = [m for m in ('vtkmodules', 'pyvista', 'matplotlib', 'pyqtgraph', 'ezdxf',"
        " 'opensees_studio.views.main_window') if m in sys.modules]\n"
        "print(','.join(heavy))\n"
    )
    out = subprocess.run(
        [sys.executable, "-c", script], capture_output=True, text=True, check=True, timeout=120
    ).stdout.strip()
    assert out == ""


def test_the_splash_key_is_the_language_setting() -> None:
    assert splash_module.LANGUAGE_KEY == i18n.SETTINGS_KEY
