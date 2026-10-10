"""The help window, and the F1 that opens it on the topic you are looking at.

F1 is handled by an application-wide event filter rather than by a shortcut,
because the interesting case is *while a menu is open*: the popup has the
keyboard, and only a filter sees the key before the popup does. The topic is then
resolved from what is actually on screen — the item under the cursor in the open
menu, the dialog on top, or the menu the cursor is resting on — and falls back to
the contents page.

Nothing here decides what the help *says*: that is
:mod:`opensees_studio.core.help`.
"""

from __future__ import annotations

import weakref

import shiboken6
from PySide6.QtCore import QEvent, QObject, Qt, QUrl
from PySide6.QtGui import QKeyEvent, QShowEvent
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLineEdit,
    QMenu,
    QTextBrowser,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core.help import (
    DEFAULT_TOPIC,
    TOPIC_PROPERTY,
    TOPICS,
    groups_present,
    resolve_topic,
    topic,
    topics_in_group,
)
from opensees_studio.views.screen_fit import FittedDialog, fit_to_available_screen


def topic_of(widget: QObject | None) -> str | None:
    """The help topic a widget declares, if any."""
    if widget is None:
        return None
    value = widget.property(TOPIC_PROPERTY)
    return str(value) if value else None


class HelpWindow(FittedDialog):
    """Contents on the left, the selected topic on the right."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("OpenSees Studio — Help")
        self.setModal(False)
        self._current = DEFAULT_TOPIC
        self._build_ui()
        self.show_topic(DEFAULT_TOPIC)

    # ── ui ──────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        top = QHBoxLayout()
        self._filter = QLineEdit()
        self._filter.setPlaceholderText("Filter topics…")
        self._filter.textChanged.connect(self._apply_filter)
        top.addWidget(self._filter)
        layout.addLayout(top)

        body = QHBoxLayout()
        self._contents = QTreeWidget()
        self._contents.setHeaderHidden(True)
        self._contents.setMinimumWidth(240)
        self._contents.currentItemChanged.connect(self._on_contents_changed)
        body.addWidget(self._contents, 1)

        self._page = QTextBrowser()
        self._page.setOpenLinks(False)
        self._page.anchorClicked.connect(self._on_anchor)
        body.addWidget(self._page, 3)
        layout.addLayout(body)

        self._populate()
        self.resize(900, 560)

    def _populate(self) -> None:
        self._contents.clear()
        for group in groups_present():
            parent = QTreeWidgetItem([group])
            parent.setFlags(Qt.ItemFlag.ItemIsEnabled)  # a heading, not a topic
            for topic_id, entry in topics_in_group(group):
                child = QTreeWidgetItem([entry.title])
                child.setData(0, Qt.ItemDataRole.UserRole, topic_id)
                child.setToolTip(0, entry.summary or entry.title)
                parent.addChild(child)
            self._contents.addTopLevelItem(parent)
        self._contents.expandAll()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not event.spontaneous():
            fit_to_available_screen(self)

    # ── topics ──────────────────────────────────────────────────────
    def show_topic(self, topic_id: str) -> None:
        """Show a topic, mark it in the contents and remember it."""
        entry = topic(topic_id)
        resolved = topic_id if topic_id in TOPICS else DEFAULT_TOPIC
        self._current = resolved
        self._page.setHtml(entry.html())
        self._page.verticalScrollBar().setValue(0)
        self._select_in_contents(resolved)

    def topic_id(self) -> str:
        return self._current

    def _groups(self) -> list[QTreeWidgetItem]:
        """The group items (PySide types the accessors as optional)."""
        items = [
            self._contents.topLevelItem(index)
            for index in range(self._contents.topLevelItemCount())
        ]
        return [item for item in items if item is not None]

    def _children(self, parent: QTreeWidgetItem) -> list[QTreeWidgetItem]:
        items = [parent.child(index) for index in range(parent.childCount())]
        return [item for item in items if item is not None]

    def _select_in_contents(self, topic_id: str) -> None:
        self._contents.blockSignals(True)
        for parent in self._groups():
            for child in self._children(parent):
                if child.data(0, Qt.ItemDataRole.UserRole) == topic_id:
                    self._contents.setCurrentItem(child)
                    self._contents.scrollToItem(child)
                    self._contents.blockSignals(False)
                    return
        self._contents.blockSignals(False)

    def _on_contents_changed(self, current: QTreeWidgetItem | None, _previous: object) -> None:
        if current is None:
            return
        topic_id = current.data(0, Qt.ItemDataRole.UserRole)
        if topic_id:
            self.show_topic(str(topic_id))

    def _on_anchor(self, url: QUrl) -> None:
        """``topic:<id>`` links inside a page switch to that topic."""
        text = url.toString()
        if text.startswith("topic:"):
            self.show_topic(text[len("topic:") :])

    def _apply_filter(self, text: str) -> None:
        needle = text.strip().lower()
        for parent in self._groups():
            visible_children = 0
            for child in self._children(parent):
                topic_id = str(child.data(0, Qt.ItemDataRole.UserRole))
                entry = TOPICS.get(topic_id)
                haystack = " ".join(
                    [entry.title, entry.summary, entry.body] if entry else [child.text(0)]
                ).lower()
                matches = not needle or needle in haystack
                child.setHidden(not matches)
                visible_children += int(matches)
            parent.setHidden(visible_children == 0)
        if needle:
            self._contents.expandAll()


class HelpController(QObject):
    """F1 opens the help at whatever the user is looking at."""

    #: The controller currently answering F1, held weakly: one window, one help,
    #: so installing a second one (a test, or a second main window) uninstalls
    #: the first instead of leaving two filters racing for the same key. Weakly,
    #: because a closed window's controller is deleted by Qt while this registry
    #: would otherwise keep the wrapper alive.
    _active: weakref.ReferenceType[HelpController] | None = None

    def __init__(self, window: QWidget) -> None:
        super().__init__(window)
        self._window = window
        self._help: HelpWindow | None = None

    # ── plumbing ────────────────────────────────────────────────────
    def install(self) -> None:
        """Watch every key press in the application, dialogs included."""
        previous = self._current()
        if previous is not None and previous is not self:
            previous.uninstall()
        HelpController._active = weakref.ref(self)
        app = QApplication.instance()
        if app is not None:
            app.installEventFilter(self)

    def uninstall(self) -> None:
        if shiboken6.isValid(self):  # the window may already have been destroyed
            app = QApplication.instance()
            if app is not None:
                app.removeEventFilter(self)
        current = self._current()
        if current is None or current is self:
            HelpController._active = None

    @staticmethod
    def _current() -> HelpController | None:
        """The controller answering F1, or None when it is already gone."""
        reference = HelpController._active
        if reference is None:
            return None
        controller = reference()
        if controller is None or not shiboken6.isValid(controller):
            HelpController._active = None
            return None
        return controller

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        """F1 is the help, wherever it is pressed."""
        if event.type() == QEvent.Type.KeyPress:
            key_event = event
            if isinstance(key_event, QKeyEvent) and key_event.key() == Qt.Key.Key_F1:
                self.open_help()
                return True
        return super().eventFilter(watched, event)

    # ── what the user is looking at ─────────────────────────────────
    def current_topic(self) -> str:
        """The topic of the open menu, the dialog on top, or the contents.

        Gathering is Qt's job (which popup is open, what is highlighted); the
        decision itself is :func:`opensees_studio.core.help.resolve_topic`, so it
        can be tested without a display.
        """
        app = QApplication.instance()
        if not isinstance(app, QApplication):  # no GUI: nothing on screen to read
            return DEFAULT_TOPIC

        highlighted: str | None = None
        menu_first: str | None = None
        popup = app.activePopupWidget()
        if isinstance(popup, QMenu):
            highlighted = topic_of(popup.activeAction()) or topic_of(popup)
            menu_first = self._first_topic(popup)

        menubar = getattr(self._window, "menuBar", None)
        if menu_first is None and callable(menubar):
            active = menubar().activeAction()
            menu = active.menu() if active is not None else None
            if isinstance(menu, QMenu):
                menu_first = self._first_topic(menu)

        return resolve_topic(
            highlighted=highlighted,
            menu_first=menu_first,
            widget_topics=(
                topic_of(app.activeModalWidget()),
                topic_of(app.activeWindow()),
                topic_of(self._window),
            ),
        )

    @staticmethod
    def _first_topic(menu: QMenu) -> str | None:
        """The topic of the menu's first real entry: what an open menu shows."""
        for action in menu.actions():
            if not action.isSeparator() and topic_of(action):
                return str(topic_of(action))
        return None

    # ── the window ──────────────────────────────────────────────────
    def help_window(self) -> HelpWindow:
        if self._help is None:
            self._help = HelpWindow(self._window)
        return self._help

    def open_help(self, topic_id: str | None = None) -> None:
        """Show the help at ``topic_id``, or at the topic of what is on screen."""
        window = self.help_window()
        window.show_topic(topic_id or self.current_topic())
        if window.isMinimized():
            window.showNormal()
        window.show()
        window.raise_()
        window.activateWindow()
