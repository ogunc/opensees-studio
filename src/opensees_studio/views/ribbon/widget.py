"""Ribbon: the menu actions regrouped by the modelling workflow.

The ribbon does not own a single check or dialog. Every button is a thin
wrapper over an existing ``QAction`` from the menu bar, so the shortcut, the
enabled state, the help topic and the slot are exactly the ones the menu uses.

Tabs follow the order an engineer models:

``Inicio · Modelar · Definir · Cargas · Asignar · Análisis · Diseño · Resultados · Vista``

**Diseño** splits into material subpanels (Acero, Concreto, Cold-formed, Madera,
Otros). The menus stay available: *Options → Use Ribbon* toggles the ribbon, and
the ribbon's own **Menús** button shows the menu bar without leaving it.

Nothing here is a second engine: the *Steel Design Workflow* principle applied to
the whole application.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QScrollArea,
    QStackedWidget,
    QTabBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.views.i18n import tr
from opensees_studio.views.ribbon.icons import icon_for

# ── the tab map ──────────────────────────────────────────────────
#: menu title → (tab id, group title). Submenus override the group.
TAB_OF_MENU: dict[str, tuple[str, str]] = {
    "File": ("home", "File"),
    "Edit": ("model", "Edit"),
    "Select": ("model", "Select"),
    "Define": ("define", "Define"),
    "Assign": ("assign", "Assign"),
    "Analyze": ("analyze", "Analysis"),
    "Display": ("results", "Results"),
    "Design": ("design", "Design"),
    "View": ("view", "Views"),
    "Tools": ("model", "Draw"),
    "Options": ("home", "Session"),
    "Help": ("help", "Help"),
}

#: submenu title → (tab id, group title) when the menu's own group is too big.
SUBGROUP: dict[str, tuple[str, str]] = {
    "Import": ("home", "Interchange"),
    "Export": ("home", "Interchange"),
    "Open Recent": ("home", "File"),
    "Time Series": ("define", "Series"),
    "Joint": ("assign", "Joint"),
    "Frame": ("assign", "Frame"),
    "Area": ("assign", "Area"),
    "Rotate": ("view", "Camera"),
    "Color By": ("view", "Color"),
    "Visibility": ("view", "Visibilidad"),
    "Panels": ("view", "Panels"),
    "Steel Connections": ("design", "Connections"),
    "Connection Calculators": ("design", "Calculators"),
    "Language": ("home", "Session"),
    "Autosave Recovery Copy": ("home", "Session"),
    "Keyboard Shortcuts": ("home", "Session"),
}

#: Order the tabs appear in, with their labels.
TAB_ORDER: tuple[tuple[str, str], ...] = (
    ("home", "Home"),
    ("model", "Modeling"),
    ("define", "Define"),
    ("loads", "Loads"),
    ("assign", "Assign"),
    ("analyze", "Analysis"),
    ("design", "Design"),
    ("results", "Results"),
    ("view", "Views"),
    ("help", "Help"),
)

#: Design actions by material subpanel (matched on the action's label).
DESIGN_MATERIALS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "acero",
        "Steel",
        (
            "Design Basis",
            "Direct Analysis",
            "Notional",
            "Member Classification",
            "Built-Up",
            "Steel Frame Check",
            "Display Steel Ratios",
            "Storey Drift",
            "Connections by Joint",
            "Base Plates",
            "Connections (AISC 358",
            "Gussets",
            "Column Splices",
            "Connection Checks",
        ),
    ),
    ("concreto", "Concrete", ("Concrete Frame Check",)),
    ("cold", "Cold-formed", ()),
    ("madera", "Timber", ()),
    ("otros", "Other", ()),
)

#: How many buttons a group shows before the rest go to **More**.
VISIBLE_PER_GROUP = 3

#: A label this long is shown beside its icon; longer ones are icon-only.
LABEL_LIMIT = 5

#: Icon size of the ribbon buttons, in pixels.
ICON_SIZE = 18

#: The icon colour: mid slate, readable on both the light and the dark theme.
_ICON_COLOR = "#94a3b8"

#: Group title → the glyph used when its actions carry no icon of their own.
GROUP_ICONS: dict[str, str] = {
    "File": "file",
    "Edit": "edit",
    "Select": "select",
    "Draw": "frame",
    "Interchange": "file",
    "Session": "calc",
    "Define": "section",
    "Series": "time",
    "Patterns": "pattern",
    "Seismic": "load",
    "Nodal": "node",
    "Member": "frame",
    "Surface": "area",
    "Joint": "joint",
    "Frame": "frame",
    "Area": "area",
    "Camera": "view",
    "Color": "view",
    "Visibility": "view",
    "Panels": "view",
    "Connections": "connection",
    "Calculators": "calc",
    "Material": "material",
    "Analysis": "calc",
    "Design": "design",
    "Results": "result",
}

#: Actions that belong to the Cargas tab whatever menu they sit in.
#: ``label → group title``; matched on the label the menu shows.
LOAD_GROUP: dict[str, str] = {
    "Add Plain Load Pattern": "Patterns",
    "Add Uniform Excitation": "Patterns",
    "Add Multi-Support Excitation": "Patterns",
    "Seismic Loads (Equivalent Lateral Force)": "Seismic",
    "Point Loads": "Nodal",
    "Distributed Load": "Member",
    "Trapezoidal Load": "Member",
    "Point Load": "Member",
    "Temperature Load": "Member",
    "Tendon (Post-Tensioning)": "Member",
    "Surface Load on Shells": "Surface",
    "Floor Load to Frames": "Surface",
}


@dataclass
class RibbonItem:
    """One button: an existing action plus how it is drawn."""

    action: Any
    role: str = "small"
    """``primary`` (big, icon above) or ``small`` (icon beside)."""


@dataclass
class RibbonGroup:
    """A titled cluster of buttons, with the overflow for the rest."""

    title: str
    items: list[RibbonItem] = field(default_factory=list)
    overflow: list[RibbonItem] = field(default_factory=list)


@dataclass
class RibbonMaterial:
    """One material subpanel of the Design tab."""

    id: str
    label: str
    groups: list[RibbonGroup] = field(default_factory=list)


@dataclass
class RibbonTab:
    """One ribbon tab: its groups, or the Design material subpanels."""

    id: str
    label: str
    groups: list[RibbonGroup] = field(default_factory=list)
    materials: list[RibbonMaterial] = field(default_factory=list)

    @property
    def is_design(self) -> bool:
        return bool(self.materials)


def _clean(text: str) -> str:
    """The label a menu shows, without the ``&`` accelerator."""
    return text.replace("&", "").replace("…", "").strip()


def build_ribbon_tabs(menu_bar: Any) -> list[RibbonTab]:
    """Group every menu action into ribbon tabs.

    Every action that has a menu entry lands in exactly one group, so the ribbon
    covers the menus by construction. A group with more than
    :data:`VISIBLE_PER_GROUP` buttons keeps the rest in its **More** menu.
    """
    buckets: dict[tuple[str, str], list[RibbonItem]] = defaultdict(list)
    design_items: list[tuple[str, Any]] = []

    def walk(menu: Any, menu_title: str, submenu_title: str | None) -> None:
        for action in menu.actions():
            label = _clean(action.text())
            sub = action.menu()
            if sub is not None:
                title = _clean(sub.title())
                walk(sub, menu_title, title)
                continue
            if not label or action.isSeparator():
                continue
            if menu_title == "Design":
                design_items.append((label, action))
                continue
            load_group = LOAD_GROUP.get(label)
            if load_group is not None:
                buckets[("loads", load_group)].append(RibbonItem(action=action, role="small"))
                continue
            key = SUBGROUP.get(submenu_title or "", TAB_OF_MENU.get(menu_title, ("model", "Otros")))
            role = "primary" if _is_primary(menu_title, label) else "small"
            buckets[key].append(RibbonItem(action=action, role=role))

    for menu_action in menu_bar.actions():
        menu = menu_action.menu()
        if menu is None:
            continue
        title = _clean(menu_action.text())
        walk(menu, title, None)

    # ── the tabs, in order, with their groups in first-seen order ──
    tabs: list[RibbonTab] = []
    for tab_id, label in TAB_ORDER:
        if tab_id == "design":
            continue
        groups: dict[str, RibbonGroup] = {}
        for (bucket_tab, group_title), items in buckets.items():
            if bucket_tab != tab_id:
                continue
            groups.setdefault(group_title, RibbonGroup(title=group_title))
            _fill(groups[group_title], items)
        if groups:
            tabs.append(RibbonTab(id=tab_id, label=label, groups=list(groups.values())))

    # ── Design: one subpanel per material ──
    materials: list[RibbonMaterial] = []
    used: set[int] = set()
    for material_id, material_label, needles in DESIGN_MATERIALS:
        design_groups: dict[str, RibbonGroup] = {}
        for index, (label, action) in enumerate(design_items):
            if index in used:
                continue
            if any(needle.lower() in label.lower() for needle in needles):
                used.add(index)
                group = design_groups.setdefault("Material", RibbonGroup(title="Material"))
                group.items.append(RibbonItem(action=action, role="primary"))
        if not needles:
            design_groups["Material"] = RibbonGroup(title="Material")
        materials.append(
            RibbonMaterial(
                id=material_id, label=material_label, groups=list(design_groups.values())
            )
        )
    # Anything in the Design menu that matched no material still needs a home.
    leftover = [
        RibbonItem(action=action, role="small")
        for index, (label, action) in enumerate(design_items)
        if index not in used
    ]
    if leftover:
        materials[0].groups.append(RibbonGroup(title="Other", items=leftover))
    tabs.insert(
        next(i for i, (tab_id, _) in enumerate(TAB_ORDER) if tab_id == "design"),
        RibbonTab(id="design", label="Design", materials=materials),
    )
    return tabs


def _is_primary(menu_title: str, label: str) -> bool:
    """The one or two actions of a group that deserve the big button."""
    primary = {
        "File": ("New", "Open", "Save"),
        "Edit": ("Undo", "Redo"),
        "Modelar": ("Grid", "Draw"),
        "Design": ("Design Basis", "Steel Frame Check"),
        "Analyze": ("Run",),
        "Results": ("Deformed",),
    }
    return any(label.startswith(p) for p in primary.get(menu_title, ()))


def _fill(group: RibbonGroup, items: list[RibbonItem]) -> None:
    """Put up to ``VISIBLE_PER_GROUP`` items in the group, the rest in overflow."""
    if len(items) <= VISIBLE_PER_GROUP:
        group.items.extend(items)
        return
    group.items.extend(items[:VISIBLE_PER_GROUP])
    group.overflow.extend(items[VISIBLE_PER_GROUP:])


# ── the widget ───────────────────────────────────────────────────
class RibbonBar(QWidget):
    """The tab strip plus the groups of the selected tab."""

    tabChanged = Signal(str)
    """The id of the tab the user selected (``home``, ``design``, …)."""

    materialChanged = Signal(str)
    """The id of the Design material subpanel selected."""

    menusRequested = Signal()
    """The **Menús** button: show the classic menu bar."""

    def __init__(self, tabs: list[RibbonTab], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tabs = tabs
        self._buttons: dict[str, QToolButton] = {}
        self._material_bars: dict[str, QTabBar] = {}
        self._group_holders: dict[str, QHBoxLayout] = {}
        self._group_labels: list[tuple[QLabel, str]] = []
        self._more_buttons: list[QToolButton] = []
        self._menus_button: QToolButton | None = None
        self._build()
        self.setCurrentTab(tabs[0].id if tabs else "")

    def tabs(self) -> list[RibbonTab]:
        return self._tabs

    def actions(self) -> list[Any]:
        """Every QAction the ribbon exposes, groups and overflow included.

        The coverage test compares this list with the menu bar: they must be the
        same actions, so no command is reachable from one and not the other.
        """
        out: list[Any] = []
        for tab in self._tabs:
            groups = list(tab.groups)
            for material in tab.materials:
                groups.extend(material.groups)
            for group in groups:
                out.extend(item.action for item in group.items)
                out.extend(item.action for item in group.overflow)
        return out

    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        row = QHBoxLayout()
        row.setContentsMargins(6, 2, 6, 0)
        row.setSpacing(6)
        self._tabbar = QTabBar(self)
        self._tabbar.setExpanding(False)
        self._tabbar.setDrawBase(False)
        for tab_id, label in TAB_ORDER:
            if any(t.id == tab_id for t in self._tabs):
                self._tabbar.addTab(tr(label))
        self._tabbar.currentChanged.connect(self._on_tab_changed)
        row.addWidget(self._tabbar, 1)
        menus = QToolButton(self)
        menus.setText(tr("Menus"))
        menus.setToolTip("Show or hide the classic menu bar")
        menus.setAutoRaise(True)
        menus.setCheckable(True)
        menus.setChecked(False)
        menus.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        menus.setIcon(icon_for("menus", _ICON_COLOR))
        menus.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        menus.clicked.connect(self.menusRequested)
        row.addWidget(menus)
        self._menus_button = menus
        layout.addLayout(row)

        self._stack = QStackedWidget(self)
        self._pages: dict[str, QWidget] = {}
        for tab in self._tabs:
            self._pages[tab.id] = self._build_page(tab)
            self._stack.addWidget(self._pages[tab.id])
        layout.addWidget(self._stack, 1)

    def _build_page(self, tab: RibbonTab) -> QWidget:
        page = QWidget(self)
        rows = QVBoxLayout(page)
        rows.setContentsMargins(6, 4, 6, 4)
        rows.setSpacing(2)

        if tab.materials:
            bar = QTabBar(page)
            bar.setExpanding(False)
            bar.setDrawBase(False)
            for material in tab.materials:
                bar.addTab(tr(material.label))
            bar.currentChanged.connect(
                lambda index, tab_id=tab.id: self._on_material_changed(tab_id, index)
            )
            rows.addWidget(bar)
            self._material_bars[tab.id] = bar

        body = QWidget(page)
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(6)

        scroll = QScrollArea(body)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        holder = QWidget(scroll)
        holder_layout = QHBoxLayout(holder)
        holder_layout.setContentsMargins(2, 2, 2, 2)
        holder_layout.setSpacing(6)

        for group in self._groups_of(tab, 0):
            holder_layout.addWidget(self._build_group(group, tab.id, 0))
        holder_layout.addStretch(1)
        scroll.setWidget(holder)
        scroll.setMinimumHeight(self._group_height(tab))
        body_layout.addWidget(scroll)

        rows.addWidget(body, 1)
        self._group_holders[tab.id] = holder_layout
        return page

    def _groups_of(self, tab: RibbonTab, material_index: int) -> list[RibbonGroup]:
        if not tab.materials:
            return tab.groups
        if material_index < len(tab.materials):
            return tab.materials[material_index].groups
        return []

    def _group_height(self, tab: RibbonTab) -> int:
        return 86

    def _build_group(self, group: RibbonGroup, tab_id: str, material_index: int) -> QWidget:
        box = QWidget(self)
        layout = QVBoxLayout(box)
        layout.setContentsMargins(6, 3, 6, 1)
        layout.setSpacing(1)

        row = QHBoxLayout()
        row.setSpacing(2)
        icon_name = GROUP_ICONS.get(group.title, "calc")
        for item in group.items:
            row.addWidget(self._button(item, icon_name))
        if group.overflow:
            more = QToolButton(box)
            more.setText(tr("More"))
            more.setToolTip(tr("More") + " ▾")
            more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            menu = QMenu(more)
            for item in group.overflow:
                menu.addAction(item.action)
            more.setMenu(menu)
            more.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            more.setIcon(icon_for("more", _ICON_COLOR))
            more.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
            row.addWidget(more)
            self._more_buttons.append(more)
        row.addStretch(1)
        layout.addLayout(row)

        title = QLabel(tr(group.title), box)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_font = title.font()
        title_font.setPointSizeF(max(title_font.pointSizeF() - 1.5, 8.0))
        title.setFont(title_font)
        layout.addWidget(title)
        self._group_labels.append((title, group.title))
        return box

    def _button(self, item: RibbonItem, icon_name: str) -> QToolButton:
        """One command: an icon when the label is long, text when it is short.

        A short label is kept beside the icon (it reads faster than a glyph); a
        longer one becomes icon-only with the label in the tooltip, which is
        what keeps the ribbon one row high.
        """
        button = QToolButton(self)
        label = _clean(item.action.text())
        tip = item.action.toolTip() or item.action.statusTip() or label
        if len(label) > LABEL_LIMIT:
            tip = f"{label} — {tip}" if tip and tip != label else label
        button.setToolTip(tip)
        button.setStatusTip(tip)
        button.setAccessibleName(label)

        if item.action.icon().isNull():
            item.action.setIcon(icon_for(icon_name, _ICON_COLOR))

        button.setDefaultAction(item.action)
        button.setIconSize(QSize(ICON_SIZE, ICON_SIZE))
        if len(label) <= LABEL_LIMIT:
            # A short label stays readable beside the icon.
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.setMinimumWidth(ICON_SIZE + 24)
        else:
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            button.setMinimumWidth(ICON_SIZE + 12)
        button.setMaximumHeight(ICON_SIZE + 26)
        return button

    # ── navigation ────────────────────────────────────────────────
    def _on_tab_changed(self, index: int) -> None:
        if index < 0:
            return
        tab = self._tabs[index]
        for page_id, page in self._pages.items():
            page.setVisible(page_id == tab.id)
        self._stack.setCurrentWidget(self._pages[tab.id])
        self.tabChanged.emit(tab.id)

    def _on_material_changed(self, tab_id: str, index: int) -> None:
        tab = next((t for t in self._tabs if t.id == tab_id), None)
        if tab is None or not tab.materials:
            return
        holder = self._group_holders[tab_id]
        while holder.count():
            item = holder.takeAt(0)
            if item is not None:
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
        material = tab.materials[index]
        for group in material.groups:
            holder.addWidget(self._build_group(group, tab_id, index))
        holder.addStretch(1)
        self.materialChanged.emit(material.id)

    def retranslate(self) -> None:
        """Re-label tabs, groups and buttons after a language change."""
        for index, (_, label) in enumerate(TAB_ORDER):
            if index < self._tabbar.count():
                self._tabbar.setTabText(index, tr(label))
        for tab_id, bar in self._material_bars.items():
            tab = next((t for t in self._tabs if t.id == tab_id), None)
            if tab is None:
                continue
            for index, material in enumerate(tab.materials):
                bar.setTabText(index, tr(material.label))
        for title_label, title_text in self._group_labels:
            title_label.setText(tr(title_text))
        for button in self._more_buttons:
            button.setText(tr("More"))
        if self._menus_button is not None:
            self._menus_button.setText(tr("Menus"))

    def set_menus_visible(self, visible: bool) -> None:
        """Reflect the menu bar state on the **Menus** button."""
        if self._menus_button is not None:
            self._menus_button.setChecked(visible)

    def setCurrentTab(self, tab_id: str) -> None:
        for index, tab in enumerate(self._tabs):
            if tab.id == tab_id:
                self._tabbar.setCurrentIndex(index)
                return

    def currentTab(self) -> str:
        index = self._tabbar.currentIndex()
        return self._tabs[index].id if 0 <= index < len(self._tabs) else ""
