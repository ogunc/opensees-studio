"""Options → Language: the interface in English or Spanish.

:class:`InterfaceTranslator` is an application-wide event filter. When a
window, dialog or dock is shown it walks its widgets and replaces every text the
catalog knows (:mod:`core.i18n`) — menus and actions, labels, buttons, check
boxes, group boxes, tabs and the window title — keeping the English original in
a dynamic property, so switching back restores it without reopening anything.
Qt's own texts (OK, Cancel, the file dialogs) come from Qt's translation files.
Help pages and messages built at run time stay in English.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QEvent, QLibraryInfo, QObject, QSettings, QTranslator
from PySide6.QtWidgets import (
    QAbstractButton,
    QApplication,
    QGroupBox,
    QLabel,
    QMenu,
    QTabWidget,
    QWidget,
)

from opensees_studio.core.i18n import LANGUAGES, translate

SETTINGS_KEY = "interface/language"
_ORIGINAL = "_i18n_original"


def stored_language() -> str:
    value = str(QSettings().value(SETTINGS_KEY, "en") or "en")
    return value if value in LANGUAGES else "en"


def _apply(obj: Any, getter: str, setter: str, language: str, key: str = _ORIGINAL) -> None:
    original = obj.property(key)
    if original is None:
        original = getattr(obj, getter)()
        if not original:
            return
        obj.setProperty(key, original)
    translated = translate(original, language) if language != "en" else None
    getattr(obj, setter)(translated if translated is not None else original)


def translate_widget(widget: QWidget, language: str) -> None:
    """Translate ``widget`` and everything inside it (menus and their actions too)."""
    _apply(widget, "windowTitle", "setWindowTitle", language, "_i18n_title")
    for child in [widget, *widget.findChildren(QWidget)]:
        if isinstance(child, QLabel | QAbstractButton):
            _apply(child, "text", "setText", language)
        elif isinstance(child, QGroupBox):
            _apply(child, "title", "setTitle", language)
        elif isinstance(child, QTabWidget):
            for index in range(child.count()):
                key = f"_i18n_tab_{index}"
                original = child.property(key) or child.tabText(index)
                child.setProperty(key, original)
                found = translate(original, language) if language != "en" else None
                child.setTabText(index, found or original)
        if isinstance(child, QMenu):
            # The title is the text of the menu's action: translate it through that.
            _apply(child.menuAction(), "text", "setText", language)
        for action in child.actions():
            _apply(action, "text", "setText", language)


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
            and watched.isWindow()
            and self.language != "en"
        ):
            translate_widget(watched, self.language)
        return False


def install(app: QApplication) -> InterfaceTranslator:
    """The application's translator, in the language the user chose last."""
    return InterfaceTranslator(app, stored_language())
