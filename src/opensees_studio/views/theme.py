"""Light and dark themes: palettes, semantic text colours and the 3D viewport style.

Qt applies a palette to every widget that does not draw its own colours, which is
most of the interface. The 3D canvas does draw its own background, so it gets a
matching :class:`~opensees_studio.views.canvas3d.style.RenderStyle`.

A widget that needs a colour the palette has no role for (a muted hint, an error
message, a warning) asks :func:`tone` for it instead of hardcoding a grey that is
readable on only one of the two themes, and :func:`set_text_tone` keeps a label's
colour in step when the user toggles the theme while it is open. Every pair of
text and background colours here meets WCAG 2.x contrast: 4.5:1 for normal text,
3:1 for disabled text (``tests/gui/test_theme_contrast.py`` checks it).

Nothing here is a second theme engine: it swaps colours and leaves the layout
alone. The choice is remembered by the caller (``QSettings``).
"""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory, QWidget

from opensees_studio.views.canvas3d.style import (
    RenderStyle,
    contrast_ratio,
    relative_luminance,
)

__all__ = [
    "DARK",
    "LIGHT",
    "TONES",
    "apply_theme",
    "contrast_ratio",
    "drawing_colour",
    "is_dark",
    "relative_luminance",
    "set_text_tone",
    "tone",
    "tone_span",
    "viewport_style",
]

#: Window, panel and text colours of the dark theme.
DARK = {
    "window": "#1f232b",
    "panel": "#262b34",
    "base": "#2b313b",
    "text": "#e6e9ef",
    "muted": "#a3acba",
    "highlight": "#2563eb",
    "light": "#3a414d",
    "mid": "#4b5563",
    "dark": "#15181e",
    "shadow": "#0b0d11",
    "link": "#8ab4ff",
    "link_visited": "#c4a7ff",
}

#: The same roles for the light theme (the Qt default is close, but pinning it
#: keeps a toggle back exact on every platform).
LIGHT = {
    "window": "#f3f4f6",
    "panel": "#ffffff",
    "base": "#ffffff",
    "text": "#1f2937",
    "muted": "#5b6472",
    "highlight": "#1d4ed8",
    "light": "#ffffff",
    "mid": "#a0a6b0",
    "dark": "#6b7280",
    "shadow": "#374151",
    "link": "#1d4ed8",
    "link_visited": "#6d28d9",
}

#: Semantic text colours, readable on the window, panel and base of their theme.
TONES = {
    False: {
        "muted": LIGHT["muted"],
        "error": "#b42318",
        "warning": "#8a4b00",
        "success": "#1e7b34",
        "accent": "#1d4ed8",
    },
    True: {
        "muted": DARK["muted"],
        "error": "#ff8a80",
        "warning": "#fbbf24",
        "success": "#4ade80",
        "accent": "#8ab4ff",
    },
}

#: Section drawings and other small previews: fill, outline and background.
DRAWING = {
    False: {"background": "#ffffff", "outline": "#1f2937", "fill": "#9fb4c8"},
    True: {"background": "#2b313b", "outline": "#e6e9ef", "fill": "#4f6d8a"},
}

_native_style: str | None = None


def is_dark(palette: QPalette | None = None) -> bool:
    """Whether ``palette`` (the application's by default) is a dark one."""
    if palette is None:
        app = QApplication.instance()
        if not isinstance(app, QApplication):
            return False
        palette = app.palette()
    return palette.color(QPalette.ColorRole.Window).lightness() < 128


def tone(name: str, dark: bool | None = None) -> str:
    """The ``#rrggbb`` of a semantic text colour: muted, error, warning, success, accent."""
    return TONES[is_dark() if dark is None else dark][name]


def drawing_colour(name: str, dark: bool | None = None) -> str:
    """Background, outline or fill of a small preview drawing, for the current theme."""
    return DRAWING[is_dark() if dark is None else dark][name]


def tone_span(text: str, name: str) -> str:
    """``text`` (already HTML-escaped) wrapped in a span of the given tone."""
    return f"<span style='color:{tone(name)}'>{text}</span>"


class _ToneKeeper(QObject):
    """Reapplies a label's tone when the application palette changes."""

    def __init__(self, widget: QWidget, name: str, extra: str) -> None:
        super().__init__(widget)
        self.name = name
        self.extra = extra
        widget.installEventFilter(self)
        self.apply(widget)

    def apply(self, widget: QWidget) -> None:
        widget.setStyleSheet(f"color: {tone(self.name)};{self.extra}")

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if event.type() == QEvent.Type.ApplicationPaletteChange and isinstance(watched, QWidget):
            self.apply(watched)
        return False


def set_text_tone(widget: QWidget, name: str, extra: str = "") -> None:
    """Colour a widget's text with a semantic tone that follows the theme.

    ``extra`` is appended to the style sheet (``" font-family: monospace;"``).
    """
    for child in widget.findChildren(_ToneKeeper):
        if child.parent() is widget:
            child.name, child.extra = name, extra
            child.apply(widget)
            return
    _ToneKeeper(widget, name, extra)


def _palette(dark: bool) -> QPalette:
    c = DARK if dark else LIGHT
    p = QPalette()
    roles = QPalette.ColorRole
    for role, key in (
        (roles.Window, "window"),
        (roles.WindowText, "text"),
        (roles.Base, "base"),
        (roles.AlternateBase, "panel"),
        (roles.Text, "text"),
        (roles.Button, "panel"),
        (roles.ButtonText, "text"),
        (roles.BrightText, "text"),
        (roles.Highlight, "highlight"),
        (roles.ToolTipBase, "panel"),
        (roles.ToolTipText, "text"),
        (roles.PlaceholderText, "muted"),
        (roles.Accent, "highlight"),
        (roles.Light, "light"),
        (roles.Midlight, "light"),
        (roles.Mid, "mid"),
        (roles.Dark, "dark"),
        (roles.Shadow, "shadow"),
        (roles.Link, "link"),
        (roles.LinkVisited, "link_visited"),
    ):
        p.setColor(role, QColor(c[key]))
    p.setColor(roles.HighlightedText, QColor("#ffffff"))
    disabled = QPalette.ColorGroup.Disabled
    for role in (roles.WindowText, roles.Text, roles.ButtonText, roles.PlaceholderText):
        p.setColor(disabled, role, QColor(c["muted"]))
    p.setColor(disabled, roles.Base, QColor(c["window"]))
    p.setColor(disabled, roles.Highlight, QColor(c["mid"]))
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
        support_xz_color="#fb923c",
        support_yz_color="#60a5fa",
        support_lock_color="#c084fc",
        load_color="#4ade80",
        mass_color="#c084fc",
    )


def apply_theme(app: QApplication, dark: bool) -> None:
    """Apply the palette (and a matching font hint) to the whole application.

    The dark theme runs on the Fusion style: the native Windows style paints
    table headers, tabs and buttons with the system's light theme whatever the
    palette says, which left light text on light headers. The light theme keeps
    the platform's own style.
    """
    global _native_style
    current = app.style().name()
    if _native_style is None:
        _native_style = current
    wanted = "fusion" if dark else _native_style
    available = {k.lower() for k in QStyleFactory.keys()}  # noqa: SIM118 (a Qt list)
    if current.lower() != wanted.lower() and wanted.lower() in available:
        app.setStyle(wanted)
    app.setPalette(_palette(dark))
    font = QFont()
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(font)
