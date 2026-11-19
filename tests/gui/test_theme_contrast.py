"""Contrast of the light and dark themes (WCAG 2.x).

Normal text needs 4.5:1 on every background it is drawn on; disabled text and
graphics (icons, the ribbon's group titles drawn as disabled labels) need 3:1.
"""

from __future__ import annotations

import pytest
from PySide6.QtGui import QPalette
from PySide6.QtWidgets import QApplication, QLabel

from opensees_studio.views.canvas3d.style import contrast_ratio, legible
from opensees_studio.views.ribbon.icons import INK
from opensees_studio.views.theme import (
    DRAWING,
    TONES,
    _palette,
    apply_theme,
    set_text_tone,
    tone,
    viewport_style,
)

pytestmark = pytest.mark.gui

Role = QPalette.ColorRole
Group = QPalette.ColorGroup

#: (text role, background roles it is drawn on).
_PAIRS = [
    (Role.WindowText, (Role.Window, Role.Button)),
    (Role.Text, (Role.Base, Role.AlternateBase)),
    (Role.ButtonText, (Role.Button, Role.Window)),
    (Role.ToolTipText, (Role.ToolTipBase,)),
    (Role.HighlightedText, (Role.Highlight,)),
    (Role.PlaceholderText, (Role.Base,)),
    (Role.Link, (Role.Base, Role.Window)),
    (Role.LinkVisited, (Role.Base, Role.Window)),
]


def _hex(palette: QPalette, group: QPalette.ColorGroup, role: QPalette.ColorRole) -> str:
    return palette.color(group, role).name()


@pytest.mark.parametrize("dark", [False, True], ids=["light", "dark"])
@pytest.mark.parametrize("group", [Group.Active, Group.Inactive], ids=["active", "inactive"])
def test_palette_text_meets_aa(qtbot: object, dark: bool, group: QPalette.ColorGroup) -> None:
    p = _palette(dark)
    for text, backgrounds in _PAIRS:
        for background in backgrounds:
            ratio = contrast_ratio(_hex(p, group, text), _hex(p, group, background))
            minimum = 3.0 if text == Role.PlaceholderText else 4.5
            assert ratio >= minimum, (text.name, background.name, round(ratio, 2))


@pytest.mark.parametrize("dark", [False, True], ids=["light", "dark"])
def test_disabled_text_is_readable(qtbot: object, dark: bool) -> None:
    """Disabled fields (E, G and γ of a section linked to a material) and labels."""
    p = _palette(dark)
    for text in (Role.WindowText, Role.Text, Role.ButtonText):
        for background in (Role.Window, Role.Base, Role.Button):
            for bg_group in (Group.Disabled, Group.Active):
                ratio = contrast_ratio(_hex(p, Group.Disabled, text), _hex(p, bg_group, background))
                assert ratio >= 3.0, (text.name, background.name, round(ratio, 2))


@pytest.mark.parametrize("dark", [False, True], ids=["light", "dark"])
def test_semantic_tones_meet_aa(qtbot: object, dark: bool) -> None:
    p = _palette(dark)
    for name, colour in TONES[dark].items():
        for background in (Role.Window, Role.Base, Role.Button, Role.AlternateBase):
            ratio = contrast_ratio(colour, _hex(p, Group.Active, background))
            assert ratio >= 4.5, (name, background.name, round(ratio, 2))


@pytest.mark.parametrize("dark", [False, True], ids=["light", "dark"])
def test_drawings_and_icons(qtbot: object, dark: bool) -> None:
    d = DRAWING[dark]
    assert contrast_ratio(d["outline"], d["background"]) >= 4.5
    assert contrast_ratio(d["fill"], d["background"]) >= 1.5
    p = _palette(dark)
    for background in (Role.Window, Role.Button, Role.Base):
        assert contrast_ratio(INK, _hex(p, Group.Active, background)) >= 3.0


@pytest.mark.parametrize("dark", [False, True], ids=["light", "dark"])
def test_viewport_labels(dark: bool) -> None:
    style = viewport_style(dark)
    assert style.is_dark is dark
    for end in (style.background_top, style.background_bottom):
        assert contrast_ratio(style.label_ink, end) >= 4.5
    # Data colours of the legends are lifted to 3:1 on the worst end.
    for colour in ("#000000", "#636363", "#8c564b", "#ffffff", "#bcbd22"):
        assert contrast_ratio(legible(colour, style.background), style.background) >= 3.0


def test_tone_follows_a_theme_toggle(qtbot: object) -> None:
    app = QApplication.instance()
    assert isinstance(app, QApplication)
    original = app.palette()
    label = QLabel("hint")
    qtbot.addWidget(label)  # type: ignore[attr-defined]
    try:
        apply_theme(app, False)
        set_text_tone(label, "muted")
        assert tone("muted", False) in label.styleSheet()
        apply_theme(app, True)
        QApplication.processEvents()
        assert tone("muted", True) in label.styleSheet()
    finally:
        apply_theme(app, False)
        app.setPalette(original)
