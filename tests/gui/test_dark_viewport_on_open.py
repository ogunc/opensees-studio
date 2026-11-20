"""Opening a project keeps the dark viewport; a custom background still wins."""

from __future__ import annotations

import pytest

from opensees_studio.core.view_settings import ViewSettings
from opensees_studio.views.canvas3d import ModelCanvas
from opensees_studio.views.theme import viewport_style

pytestmark = pytest.mark.gui


def test_default_project_background_follows_the_theme(qtbot) -> None:  # type: ignore[no-untyped-def]
    canvas = ModelCanvas()
    qtbot.addWidget(canvas)
    dark = viewport_style(True)
    canvas.apply_style(dark)

    canvas.set_view_settings(ViewSettings())

    assert canvas._background_for(ViewSettings()) == (dark.background_top, dark.background_bottom)


def test_a_custom_background_is_kept(qtbot) -> None:  # type: ignore[no-untyped-def]
    canvas = ModelCanvas()
    qtbot.addWidget(canvas)
    canvas.apply_style(viewport_style(True))
    custom = ViewSettings(background_top="#112233", background_bottom="#445566")

    assert canvas._background_for(custom) == ("#112233", "#445566")
