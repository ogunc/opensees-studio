"""Options → Language: the interface in English or Spanish.

:class:`InterfaceTranslator` is an application-wide event filter. When a
window, dialog or dock is shown it walks its widgets and replaces every text the
catalog knows (:mod:`core.i18n`) — menus and actions, labels, buttons, check
boxes, group boxes, tabs and the window title — keeping the English original in
a dynamic property, so switching back restores it without reopening anything.
Qt's own texts (OK, Cancel, the file dialogs) come from Qt's translation files.
Table and tree column headers, a line edit's placeholder, tool tips and the
pages of a tool box are translated the same way.
A message box is a window too, so its fixed text is translated when it shows
(``tests/unit/test_i18n_messages.py`` keeps every literal one in the catalog).
A widget added to a window that is already showing is translated when it shows
itself. Texts a widget sets after it is shown go through :func:`tr`. Help pages and
messages that carry run-time values stay in English.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QEvent, QLibraryInfo, QObject, QSettings, Qt, QTranslator
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QDockWidget,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMenu,
    QTableWidget,
    QTabWidget,
    QToolBox,
    QTreeWidget,
    QWidget,
)

from opensees_studio.core.i18n import LANGUAGES, translate

SETTINGS_KEY = "interface/language"
_ORIGINAL = "_i18n_original"
#: Where a header item keeps its English text (a role nobody else uses).
_HEADER_ROLE = int(Qt.ItemDataRole.UserRole) + 0x7E5
#: The language the interface is in now (set by :class:`InterfaceTranslator`).
_current = "en"


def tr(text: str) -> str:
    """``text`` in the interface's current language (itself when the catalog lacks it)."""
    if _current == "en":
        return text
    return translate(text, _current) or text


def stored_language() -> str:
    value = str(QSettings().value(SETTINGS_KEY, "en") or "en")
    return value if value in LANGUAGES else "en"


def _translated(original: str, language: str) -> str:
    found = translate(original, language) if language != "en" else None
    return found if found is not None else original


def _shows(current: str, original: str) -> bool:
    """``current`` is ``original`` in one of the interface languages."""
    return current == original or any(
        current == translate(original, language) for language in LANGUAGES if language != "en"
    )


def _apply(obj: Any, getter: str, setter: str, language: str, key: str = _ORIGINAL) -> None:
    original = obj.property(key)
    current = getattr(obj, getter)()
    if original is None or not _shows(current, original):
        # New, or the code set another text since it was translated: that is the original now.
        original = current
        if not original:
            return
        obj.setProperty(key, original)
    getattr(obj, setter)(_translated(original, language))


def _has_own_tool_tip(action: Any) -> bool:
    """An action's tool tip is its text unless the code set another one."""

    def plain(text: str) -> str:
        return text.split("\t", 1)[0].replace("&", "").rstrip(".…").strip()

    return bool(action.toolTip()) and plain(action.toolTip()) != plain(action.text())


def _apply_item(item: Any, column: int | None, language: str) -> None:
    """A table or tree header item: its English text is kept in :data:`_HEADER_ROLE`."""
    args = () if column is None else (column,)
    original = item.data(*args, _HEADER_ROLE)
    text = item.text(*args)
    if original is None or not _shows(text, str(original)):
        # New, or the code set another text since: that one is the original now.
        original = text
        if not original:
            return
        item.setData(*args, _HEADER_ROLE, original)
    item.setText(*args, _translated(str(original), language))


def _translate_headers(view: QTableWidget | QTreeWidget, language: str) -> None:
    if isinstance(view, QTreeWidget):
        header = view.headerItem()
        for column in range(view.columnCount()):
            _apply_item(header, column, language)
        return
    for column in range(view.columnCount()):
        item = view.horizontalHeaderItem(column)
        if item is not None:
            _apply_item(item, None, language)
    for row in range(view.rowCount()):
        item = view.verticalHeaderItem(row)
        if item is not None:
            _apply_item(item, None, language)


def _translate_one(child: QWidget, language: str) -> None:
    """Translate the texts of ``child`` itself, not of the widgets inside it."""
    if isinstance(child, QLabel | QAbstractButton):
        _apply(child, "text", "setText", language)
    elif isinstance(child, QGroupBox):
        _apply(child, "title", "setTitle", language)
    elif isinstance(child, QLineEdit):
        _apply(child, "placeholderText", "setPlaceholderText", language, "_i18n_placeholder")
    elif isinstance(child, QTableWidget | QTreeWidget):
        _translate_headers(child, language)
    elif isinstance(child, QToolBox):
        for index in range(child.count()):
            key = f"_i18n_page_{index}"
            original = child.property(key) or child.itemText(index)
            child.setProperty(key, original)
            child.setItemText(index, _translated(original, language))
    elif isinstance(child, QTabWidget):
        for index in range(child.count()):
            key = f"_i18n_tab_{index}"
            original = child.property(key) or child.tabText(index)
            if not _shows(child.tabText(index), original):
                original = child.tabText(index)  # the code renamed the tab since
            child.setProperty(key, original)
            child.setTabText(index, _translated(original, language))
    if child.toolTip():
        _apply(child, "toolTip", "setToolTip", language, "_i18n_tip")


def translate_widget(widget: QWidget, language: str) -> None:
    """Translate ``widget`` and everything inside it (menus and their actions too)."""
    _apply(widget, "windowTitle", "setWindowTitle", language, "_i18n_title")
    for child in [widget, *widget.findChildren(QWidget)]:
        if isinstance(child, QDockWidget) and child is not widget:
            # Its title is also the tab label when docks share an area.
            _apply(child, "windowTitle", "setWindowTitle", language, "_i18n_title")
        _translate_one(child, language)
        if isinstance(child, QMenu):
            # The title is the text of the menu's action: translate it through that.
            _apply(child.menuAction(), "text", "setText", language)
        for action in child.actions():
            _apply(action, "text", "setText", language)
            if _has_own_tool_tip(action) or action.property("_i18n_tip") is not None:
                _apply(action, "toolTip", "setToolTip", language, "_i18n_tip")


class InterfaceTranslator(QObject):
    """Translates windows as they appear; :meth:`set_language` retranslates the open ones."""

    def __init__(self, app: QApplication, language: str = "en") -> None:
        super().__init__(app)
        self._app = app
        self.language = "en"
        self._qt = QTranslator(self)
        app.installEventFilter(self)
        self.set_language(language)

    def set_language(self, language: str) -> None:
        global _current
        _current = language
        self._app.removeTranslator(self._qt)
        if language != "en":
            path = QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)
            if self._qt.load(f"qtbase_{language}", path):
                self._app.installTranslator(self._qt)
        self.language = language
        for widget in self._app.topLevelWidgets():
            translate_widget(widget, language)

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if (
            event.type() == QEvent.Type.Show
            and isinstance(watched, QWidget)
            and self.language != "en"
        ):
            # A results dock added after the window showed is not a window itself.
            if watched.isWindow() or isinstance(watched, QDockWidget):
                translate_widget(watched, self.language)
            else:
                # A widget a panel adds after its window showed (the properties of the
                # selection, a form that changes with a combo box) is translated as it shows.
                _translate_one(watched, self.language)
        return False


def install(app: QApplication) -> InterfaceTranslator:
    """The application's translator, in the language the user chose last."""
    return InterfaceTranslator(app, stored_language())
