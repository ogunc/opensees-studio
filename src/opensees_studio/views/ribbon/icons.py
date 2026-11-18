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

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

#: Where the SVGs live.
ICON_DIR = Path(__file__).resolve().parents[2] / "data" / "icons"

#: The default ink: mid slate, readable on the light and the dark theme.
INK = "#64748b"

#: Pixel sizes rendered into each icon (small buttons, large buttons, HiDPI).
_SIZES = (16, 24, 32, 48, 64)


def icon_path(name: str) -> Path:
    return ICON_DIR / f"{name}.svg"


def has_icon(name: str) -> bool:
    return icon_path(name).is_file()


@cache
def icon_for(name: str, color: str = INK) -> QIcon:
    """The cached icon ``name`` in ``color``; the **More** dots when unknown."""
    path = icon_path(name)
    if not path.is_file():
        path = icon_path("more")
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
