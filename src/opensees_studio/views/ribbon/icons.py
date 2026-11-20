"""Command icons: one SVG per command in ``opensees_studio/data/icons``.

A command's icon is named after its action (``_act_run`` → ``run.svg``), a
submenu shown as a drop-down button after its title (``menu_import.svg``), so
the ribbon, the menus and the tool palette show the **same** picture for the
same command. The SVGs draw in ``currentColor``; :func:`icon_for` paints it in
the colour asked for and keeps an accent blue for the badges.

Edit an icon in any SVG editor (24 × 24 viewBox, strokes in ``currentColor``);
``tests/gui/test_ribbon.py`` checks that every command has one and that no two
commands share a picture.
"""

from __future__ import annotations

from functools import cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QRect, QRectF, QSize, Qt
from PySide6.QtGui import QIcon, QIconEngine, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

#: Where the SVGs live.
ICON_DIR = Path(__file__).resolve().parents[2] / "data" / "icons"

#: The default ink: mid slate, at least 3:1 (WCAG, graphics) on the window and
#: panel colours of both themes, so the icons need no repaint on a theme toggle.
INK = "#707f95"

#: Pixel sizes rendered into each icon (small buttons, large buttons, HiDPI).
_SIZES = (16, 24, 32, 48, 64)


def icon_path(name: str) -> Path:
    return ICON_DIR / f"{name}.svg"


@cache
def _shipped() -> frozenset[str]:
    """Names of every SVG, listed once instead of one ``stat`` per command."""
    return frozenset(icon_names())


def has_icon(name: str) -> bool:
    return name in _shipped()


def _render(path: Path, color: str) -> QIcon:
    """``path`` painted in ``color`` at every size of :data:`_SIZES`."""
    data = path.read_text(encoding="utf-8").replace("currentColor", color)
    renderer = QSvgRenderer(QByteArray(data.encode("utf-8")))
    icon = QIcon()
    for size in _SIZES:
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        renderer.render(painter, QRectF(0, 0, size, size))
        painter.end()
        icon.addPixmap(pixmap)
    return icon


class _LazySvgEngine(QIconEngine):
    """Reads and paints the SVG the first time Qt asks for a pixmap.

    The window gives about 400 actions and buttons an icon while it builds,
    most of them in menus and ribbon tabs nobody has opened yet; rendering them
    all up front cost most of a second of start-up. The pixmaps are the same
    as before, only made when first shown.
    """

    def __init__(self, path: Path, color: str) -> None:
        super().__init__()
        self._path = path
        self._color = color
        self._icon: QIcon | None = None

    def _real(self) -> QIcon:
        if self._icon is None:
            self._icon = _render(self._path, self._color)
        return self._icon

    def pixmap(self, size: QSize, mode: QIcon.Mode, state: QIcon.State) -> QPixmap:
        return self._real().pixmap(size, mode, state)

    def paint(self, painter: QPainter, rect: QRect, mode: QIcon.Mode, state: QIcon.State) -> None:
        self._real().paint(painter, rect, Qt.AlignmentFlag.AlignCenter, mode, state)

    def actualSize(self, size: QSize, mode: QIcon.Mode, state: QIcon.State) -> QSize:
        side = min(size.width(), size.height(), max(_SIZES))
        return QSize(side, side)

    def availableSizes(self, mode: QIcon.Mode, state: QIcon.State) -> list[QSize]:
        return [QSize(s, s) for s in _SIZES]

    def isNull(self) -> bool:
        return False

    def clone(self) -> QIconEngine:
        twin = _LazySvgEngine(self._path, self._color)
        twin._icon = self._icon
        return twin


@cache
def icon_for(name: str, color: str = INK) -> QIcon:
    """The cached icon ``name`` in ``color``; the **More** dots when unknown.

    The SVG is read and painted on first display, not here.
    """
    path = icon_path(name if has_icon(name) else "more")
    return QIcon(_LazySvgEngine(path, color))


def icon_names() -> list[str]:
    """Every icon shipped."""
    return sorted(p.stem for p in ICON_DIR.glob("*.svg"))


def command_icon_name(attribute: str) -> str:
    """``_act_run`` → ``run``."""
    return attribute.removeprefix("_act_")


def menu_icon_name(title: str) -> str:
    """``Open Recent`` → ``menu_open_recent``."""
    clean = title.replace("&", "").replace("…", "").strip().lower()
    return "menu_" + "_".join(clean.split())


def apply_command_icons(window: object, color: str = INK) -> None:
    """Give every ``_act_*`` action of ``window`` its SVG icon.

    The menus and the toolbars then show the same picture as the ribbon.
    """
    for attribute, value in vars(window).items():
        if not attribute.startswith("_act_") or not hasattr(value, "setIcon"):
            continue
        name = command_icon_name(attribute)
        if has_icon(name):
            value.setIcon(icon_for(name, color))
