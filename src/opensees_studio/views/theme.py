"""Dark mode: palettes and the matching 3D viewport style.

Qt applies a palette to every widget that does not draw its own colours, which is
most of the interface. The 3D canvas does draw its own background, so it gets a
matching :class:`~opensees_studio.views.canvas3d.style.RenderStyle`.

Nothing here is a second theme engine: it swaps colours and leaves the layout
alone. The choice is remembered by the caller (``QSettings``).
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

from opensees_studio.views.canvas3d.style import RenderStyle

#: Window, panel and text colours of the dark theme.
DARK = {
    "window": "#1f232b",
    "panel": "#262b34",
    "base": "#2b313b",
    "text": "#e6e9ef",
    "muted": "#9aa3b2",
    "highlight": "#3b82f6",
}

#: The same roles for the light theme (the Qt default is close, but pinning it
#: keeps a toggle back exact on every platform).
LIGHT = {
    "window": "#f3f4f6",
    "panel": "#ffffff",
    "base": "#ffffff",
    "text": "#1f2937",
    "muted": "#6b7280",
    "highlight": "#1d4ed8",
}


def _palette(dark: bool) -> QPalette:
    c = DARK if dark else LIGHT
    p = QPalette()
    p.setColor(QPalette.ColorRole.Window, QColor(c["window"]))
    p.setColor(QPalette.ColorRole.WindowText, QColor(c["text"]))
    p.setColor(QPalette.ColorRole.Base, QColor(c["base"]))
    p.setColor(QPalette.ColorRole.AlternateBase, QColor(c["panel"]))
    p.setColor(QPalette.ColorRole.Text, QColor(c["text"]))
    p.setColor(QPalette.ColorRole.Button, QColor(c["panel"]))
    p.setColor(QPalette.ColorRole.ButtonText, QColor(c["text"]))
    p.setColor(QPalette.ColorRole.Highlight, QColor(c["highlight"]))
    p.setColor(QPalette.ColorRole.HighlightedText, QColor("#ffffff"))
    p.setColor(QPalette.ColorRole.ToolTipBase, QColor(c["panel"]))
    p.setColor(QPalette.ColorRole.ToolTipText, QColor(c["text"]))
    p.setColor(QPalette.ColorRole.PlaceholderText, QColor(c["muted"]))
    p.setColor(QPalette.ColorRole.PlaceholderText, QColor(c["muted"]))
    p.setColor(QPalette.ColorRole.Accent, QColor(c["highlight"]))
    p.setColor(QPalette.ColorRole.WindowText, QColor(c["text"]))
    for group in (QPalette.ColorGroup.Disabled,):
        p.setColor(group, QPalette.ColorRole.Text, QColor(c["muted"]))
        p.setColor(group, QPalette.ColorRole.ButtonText, QColor(c["muted"]))
    p.setColor(QPalette.ColorRole.ToolTipText, QColor(c["text"]))
    return p


def viewport_style(dark: bool) -> RenderStyle:
    """The 3D canvas style that matches the interface theme."""
    if not dark:
        return RenderStyle()
    return RenderStyle(
        background_top="#20252e",
        background_bottom="#12151b",
        node_color="#f0a500",
        node_selected_color="#38bdf8",
        frame_color="#e6e9ef",
        truss_color="#60a5fa",
        zerolength_color="#c084fc",
        selected_color="#38bdf8",
        fix_color="#f87171",
        pin_color="#f87171",
        roller_color="#fb923c",
        custom_support_color="#94a3b8",
        load_color="#4ade80",
        mass_color="#c084fc",
    )


def apply_theme(app: QApplication, dark: bool) -> None:
    """Apply the palette (and a matching font hint) to the whole application."""
    app.setPalette(_palette(dark))
    font = QFont()
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)
