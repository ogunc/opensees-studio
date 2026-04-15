"""Smoke tests — verify the package imports and exposes its version."""

from __future__ import annotations

import opensees_studio


def test_version_exposed() -> None:
    assert isinstance(opensees_studio.__version__, str)
    assert opensees_studio.__version__.count(".") >= 2


def test_app_module_importable() -> None:
    """The bootstrap module must import without instantiating QApplication."""
    from opensees_studio import app

    assert callable(app.run)
