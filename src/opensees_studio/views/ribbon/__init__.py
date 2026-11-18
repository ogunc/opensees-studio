"""Ribbon: the menu actions regrouped by the modelling workflow.

The widget lives in :mod:`opensees_studio.views.ribbon.widget`; this package
exports it and the spec builder so callers can write::

    from opensees_studio.views.ribbon import RibbonBar, build_ribbon_tabs
"""

from __future__ import annotations

from opensees_studio.views.ribbon.widget import (
    DESIGN_MATERIALS,
    SUBGROUP,
    TAB_OF_MENU,
    TAB_ORDER,
    VISIBLE_PER_GROUP,
    RibbonBar,
    RibbonGroup,
    RibbonItem,
    RibbonMaterial,
    RibbonTab,
    build_ribbon_tabs,
)

__all__ = [
    "DESIGN_MATERIALS",
    "SUBGROUP",
    "TAB_OF_MENU",
    "TAB_ORDER",
    "VISIBLE_PER_GROUP",
    "RibbonBar",
    "RibbonGroup",
    "RibbonItem",
    "RibbonMaterial",
    "RibbonTab",
    "build_ribbon_tabs",
]
