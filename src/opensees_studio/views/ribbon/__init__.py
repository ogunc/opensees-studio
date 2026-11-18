"""Ribbon: the menu commands laid out in the order a model is built.

The widget lives in :mod:`opensees_studio.views.ribbon.widget`, the placement in
:mod:`.layout` and the SVG icons in :mod:`.icons`, so callers can write::

    from opensees_studio.views.ribbon import RibbonBar, build_ribbon_tabs
"""

from __future__ import annotations

from opensees_studio.views.ribbon.layout import RIBBON_LAYOUT
from opensees_studio.views.ribbon.widget import (
    RibbonBar,
    RibbonGroup,
    RibbonItem,
    RibbonTab,
    build_ribbon_tabs,
)

__all__ = [
    "RIBBON_LAYOUT",
    "RibbonBar",
    "RibbonGroup",
    "RibbonItem",
    "RibbonTab",
    "build_ribbon_tabs",
]
