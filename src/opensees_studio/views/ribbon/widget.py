"""Ribbon: the menu commands laid out in the order a model is built.

The ribbon owns no check or dialog. Every button wraps an existing ``QAction``
of the menu bar, so the shortcut, the enabled state, the help topic and the slot
are the menu's own. Where each command goes is :data:`layout.RIBBON_LAYOUT`
(tab → group → command); its icon is the command's SVG (:mod:`.icons`).

A group shows its large buttons (icon above the label) and then its other
commands in columns of three small rows (icon beside the label), as Office and
SAP2000 do; a whole submenu becomes one drop-down button. The menus stay
available: *Options → Use Ribbon* toggles the ribbon, and its **Menus** button
shows the menu bar without leaving it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTabBar,
    QToolButton,
    QVBoxLayout,
    QWidget,
)
from shiboken6 import isValid

from opensees_studio.views.i18n import tr
from opensees_studio.views.ribbon.icons import command_icon_name, icon_for, menu_icon_name
from opensees_studio.views.ribbon.layout import RIBBON_LAYOUT

#: Icon sizes of the large and the small buttons, in pixels.
LARGE_ICON = 32
SMALL_ICON = 16

#: Small buttons stacked per column.
ROWS = 3

#: Title of the group that collects menu commands the layout forgot.
OTHER = "Unplaced"


@dataclass
class RibbonItem:
    """One button: an action, or a submenu shown as a drop-down."""

    action: Any = None
    menu: Any = None
    icon: str = ""
    primary: bool = False

    @property
    def label(self) -> str:
        source = self.menu.title() if self.menu is not None else self.action.text()
        return _clean(source)


@dataclass
class RibbonGroup:
    title: str
    items: list[RibbonItem] = field(default_factory=list)


@dataclass
class RibbonTab:
    id: str
    label: str
    groups: list[RibbonGroup] = field(default_factory=list)


def _clean(text: str) -> str:
    """The label a menu shows, without the ``&`` accelerator or the ellipsis."""
    text = text.replace("&&", "\0").replace("&", "").replace("\0", "&")
    return text.replace("…", "").split("\t")[0].strip()


def _two_lines(text: str) -> str:
    """``"Coordinate System/Grids"`` → two lines split at the middle space."""
    words = text.replace("/", "/ ").split()
    if len(words) < 2:
        return text
    cut = min(range(1, len(words)), key=lambda i: abs(len(" ".join(words[:i])) - len(text) / 2))
    lines = " ".join(words[:cut]) + "\n" + " ".join(words[cut:])
    return lines.replace("/ ", "/")


def _label_sync(button: QToolButton, action: Any, large: bool) -> Any:
    """A slot that puts the action's menu label on ``button``."""

    def sync() -> None:
        if not (isValid(button) and isValid(action)):
            return  # the window is being torn down
        label = _clean(action.text())
        text = _two_lines(label) if large else label
        button.setText(text.replace("&", "&&"))  # a literal "&", not a mnemonic
        if large:
            metrics = button.fontMetrics()
            widest = max(metrics.horizontalAdvance(line) for line in text.split("\n"))
            button.setFixedWidth(max(LARGE_ICON, widest) + 28)

    return sync


def _menu_at(menu_bar: Any, path: str) -> Any:
    """The submenu at ``"File/Import"`` (menu titles, accelerators ignored)."""
    actions = menu_bar.actions()
    menu = None
    for part in path.split("/"):
        menu = next(
            (a.menu() for a in actions if a.menu() is not None and _clean(a.text()) == part),
            None,
        )
        if menu is None:
            raise KeyError(f"no menu {path!r}")
        actions = menu.actions()
    return menu


def _leaf_actions(menu: Any) -> list[Any]:
    out: list[Any] = []
    for action in menu.actions():
        sub = action.menu()
        if sub is not None:
            out.extend(_leaf_actions(sub))
        elif not action.isSeparator() and action.text():
            out.append(action)
    return out


def build_ribbon_tabs(window: Any) -> list[RibbonTab]:
    """The tabs of :data:`RIBBON_LAYOUT`, resolved against ``window``.

    A menu command the layout does not place lands in an **Other** group of the
    Home tab, so it is never lost; the coverage test keeps that group empty.
    """
    menu_bar = window.menuBar()
    attribute_of = {id(v): k for k, v in vars(window).items() if k.startswith("_act_")}
    placed: set[int] = set()
    tabs: list[RibbonTab] = []
    for tab_id, tab_label, groups in RIBBON_LAYOUT:
        tab = RibbonTab(id=tab_id, label=tab_label)
        for title, entries in groups:
            group = RibbonGroup(title=title)
            for entry in entries:
                name = entry.lstrip("*")
                if name.startswith("menu:"):
                    menu = _menu_at(menu_bar, name.removeprefix("menu:"))
                    placed.update(id(a) for a in _leaf_actions(menu))
                    item = RibbonItem(menu=menu, icon=menu_icon_name(menu.title()))
                else:
                    action = getattr(window, name)
                    placed.add(id(action))
                    item = RibbonItem(action=action, icon=command_icon_name(name))
                item.primary = entry.startswith("*")
                group.items.append(item)
            tab.groups.append(group)
        tabs.append(tab)

    other = RibbonGroup(title=OTHER)
    for menu_action in menu_bar.actions():
        if menu_action.menu() is None:
            continue
        for action in _leaf_actions(menu_action.menu()):
            if id(action) not in placed:
                placed.add(id(action))
                name = attribute_of.get(id(action), "")
                other.items.append(RibbonItem(action=action, icon=command_icon_name(name)))
    if other.items:
        tabs[0].groups.append(other)
    return tabs


# ── the widget ───────────────────────────────────────────────────
class RibbonBar(QWidget):
    """The tab strip plus the groups of the selected tab."""

    tabChanged = Signal(str)
    """The id of the tab the user selected (``home``, ``design``, …)."""

    menusRequested = Signal()
    """The **Menus** button: show the classic menu bar."""

    def __init__(self, tabs: list[RibbonTab], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._tabs = tabs
        self._group_labels: list[tuple[QLabel, str]] = []
        self._menu_buttons: list[tuple[QToolButton, RibbonItem]] = []
        self._menus_button: QToolButton | None = None
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self._build()
        self.setCurrentTab(tabs[0].id if tabs else "")

    def tabs(self) -> list[RibbonTab]:
        return self._tabs

    def actions(self) -> list[Any]:
        """Every QAction the ribbon reaches, drop-down submenus included.

        The coverage test compares this list with the menu bar: no command is
        reachable from one and not the other.
        """
        out: list[Any] = []
        seen: set[int] = set()
        for tab in self._tabs:
            for group in tab.groups:
                for item in group.items:
                    reached = [item.action] if item.menu is None else _leaf_actions(item.menu)
                    for action in reached:
                        if id(action) not in seen:
                            seen.add(id(action))
                            out.append(action)
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
        for tab in self._tabs:
            self._tabbar.addTab(tr(tab.label))
        self._tabbar.currentChanged.connect(self._on_tab_changed)
        row.addWidget(self._tabbar, 1)
        menus = QToolButton(self)
        menus.setText(tr("Menus"))
        menus.setToolTip(tr("Menus"))
        menus.setAutoRaise(True)
        menus.setCheckable(True)
        menus.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        menus.setIcon(icon_for("menus"))
        menus.setIconSize(QSize(SMALL_ICON, SMALL_ICON))
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
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        holder = QWidget(scroll)
        row = QHBoxLayout(holder)
        row.setContentsMargins(4, 2, 4, 0)
        row.setSpacing(0)
        for index, group in enumerate(tab.groups):
            if index:
                line = QWidget(holder)
                line.setFixedWidth(1)
                line.setStyleSheet("background: palette(mid);")
                row.addWidget(line)
            row.addWidget(self._build_group(group, holder))
        row.addStretch(1)
        scroll.setWidget(holder)
        # Room for the groups and, on a narrow window, the scroll bar under them.
        bar = scroll.horizontalScrollBar().sizeHint().height()
        scroll.setFixedHeight(holder.sizeHint().height() + bar)
        return scroll

    def _build_group(self, group: RibbonGroup, parent: QWidget) -> QWidget:
        box = QWidget(parent)
        outer = QVBoxLayout(box)
        outer.setContentsMargins(4, 0, 4, 0)
        outer.setSpacing(0)

        body = QHBoxLayout()
        body.setSpacing(2)
        small: list[RibbonItem] = []
        for item in group.items:
            if item.primary:
                body.addWidget(self._button(item, large=True))
            else:
                small.append(item)
        if small:
            grid = QGridLayout()
            grid.setHorizontalSpacing(2)
            grid.setVerticalSpacing(0)
            for index, item in enumerate(small):
                grid.addWidget(
                    self._button(item, large=False),
                    index % ROWS,
                    index // ROWS,
                    Qt.AlignmentFlag.AlignLeft,
                )
            body.addLayout(grid)
        body.addStretch(1)
        outer.addLayout(body, 1)

        title = QLabel(tr(group.title), box)
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = title.font()
        font.setPointSizeF(max(font.pointSizeF() - 1.5, 7.5))
        title.setFont(font)
        title.setEnabled(False)  # the palette's muted text colour
        outer.addWidget(title)
        self._group_labels.append((title, group.title))
        return box

    def _button(self, item: RibbonItem, *, large: bool) -> QToolButton:
        button = QToolButton(self)
        button.setAutoRaise(True)
        size = LARGE_ICON if large else SMALL_ICON
        icon = icon_for(item.icon)
        if item.menu is not None:
            button.setText(tr(item.label))
            button.setIcon(icon)
            button.setMenu(item.menu)
            button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
            button.setToolTip(tr(item.label))
            self._menu_buttons.append((button, item))
        else:
            if item.action.icon().isNull():
                item.action.setIcon(icon)
            button.setDefaultAction(item.action)
            # The full menu label, not a toolbar's short icon text; a large
            # button breaks it over two lines instead of eliding it.
            sync = _label_sync(button, item.action, large)
            item.action.changed.connect(sync)
            sync()
        button.setAccessibleName(item.label)
        button.setIconSize(QSize(size, size))
        if large:
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)
        else:
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
            button.setFixedHeight(SMALL_ICON + 8)
            button.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        return button

    # ── navigation ────────────────────────────────────────────────
    def _on_tab_changed(self, index: int) -> None:
        if not 0 <= index < len(self._tabs):
            return
        tab = self._tabs[index]
        self._stack.setCurrentWidget(self._pages[tab.id])
        self.tabChanged.emit(tab.id)

    def retranslate(self) -> None:
        """Re-label tabs, groups and drop-downs after a language change.

        The command buttons follow their action, which the menus retranslate.
        """
        for index, tab in enumerate(self._tabs):
            self._tabbar.setTabText(index, tr(tab.label))
        for title_label, title_text in self._group_labels:
            title_label.setText(tr(title_text))
        for button, item in self._menu_buttons:
            button.setText(tr(item.label))
            button.setToolTip(tr(item.label))
        if self._menus_button is not None:
            self._menus_button.setText(tr("Menus"))
            self._menus_button.setToolTip(tr("Menus"))

    def set_menus_visible(self, visible: bool) -> None:
        """Reflect the menu bar state on the **Menus** button."""
        if self._menus_button is not None:
            self._menus_button.setChecked(visible)

    def setCurrentTab(self, tab_id: str) -> None:
        for index, tab in enumerate(self._tabs):
            if tab.id == tab_id:
                self._tabbar.setCurrentIndex(index)
                self._stack.setCurrentWidget(self._pages[tab.id])
                return

    def currentTab(self) -> str:
        index = self._tabbar.currentIndex()
        return self._tabs[index].id if 0 <= index < len(self._tabs) else ""
