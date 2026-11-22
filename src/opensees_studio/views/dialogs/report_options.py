"""File → Export → Report: the language, the layout and the chapters and tables that go in.

The tree lists the report's own chapters and subsections
(:func:`services.report.report_sections`), so a section another part of the
program adds to the report shows up here without changes. Unchecking a chapter
leaves it out with its subsections. The choice is remembered between exports
(by section key) in the application settings.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace

from PySide6.QtCore import QSettings, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core.help import TOPIC_PROPERTY
from opensees_studio.services.report_layout import ReportOptions, ReportSection
from opensees_studio.views.screen_fit import FittedDialog

SETTINGS_GROUP = "report"
_KEY = Qt.ItemDataRole.UserRole


def _flag(settings: QSettings, name: str, default: bool) -> bool:
    value = settings.value(f"{SETTINGS_GROUP}/{name}", default)
    return value in (True, "true", "1", 1)


def load_options(settings: QSettings | None = None) -> ReportOptions:
    """The options saved by the last export (the defaults the first time)."""
    settings = settings or QSettings()
    default = ReportOptions()
    raw = settings.value(f"{SETTINGS_GROUP}/excluded", [])
    if isinstance(raw, str):
        excluded = [raw]
    elif isinstance(raw, list | tuple):
        excluded = [str(k) for k in raw]
    else:
        excluded = []
    return ReportOptions(
        cover=_flag(settings, "cover", default.cover),
        cover_figure=_flag(settings, "cover_figure", default.cover_figure),
        contents=_flag(settings, "contents", default.contents),
        number_headings=_flag(settings, "number_headings", default.number_headings),
        chapter_page_break=_flag(settings, "chapter_page_break", default.chapter_page_break),
        header_footer=_flag(settings, "header_footer", default.header_footer),
        keep_tables_together=_flag(settings, "keep_tables_together", default.keep_tables_together),
        language="es" if settings.value(f"{SETTINGS_GROUP}/language", "en") == "es" else "en",
        excluded=frozenset(str(k) for k in excluded if k),
    )


def save_options(options: ReportOptions, settings: QSettings | None = None) -> None:
    settings = settings or QSettings()
    for name in (
        "cover",
        "cover_figure",
        "contents",
        "number_headings",
        "chapter_page_break",
        "header_footer",
        "keep_tables_together",
    ):
        settings.setValue(f"{SETTINGS_GROUP}/{name}", "true" if getattr(options, name) else "false")
    settings.setValue(f"{SETTINGS_GROUP}/language", options.language)
    settings.setValue(f"{SETTINGS_GROUP}/excluded", sorted(options.excluded))


class ReportOptionsDialog(FittedDialog):
    """Cover, contents, header and footer, and a checkable tree of the report's sections."""

    def __init__(
        self,
        sections: Sequence[ReportSection],
        options: ReportOptions | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Export Report")
        self.setProperty(TOPIC_PROPERTY, "file.export_report")
        options = options or ReportOptions()
        self._options = options
        layout = QVBoxLayout(self)

        form = QFormLayout()
        self._language = QComboBox()
        self._language.addItem("English", "en")
        self._language.addItem("Español", "es")
        self._language.setCurrentIndex(1 if options.language == "es" else 0)
        form.addRow("Language:", self._language)
        layout.addLayout(form)

        page = QGroupBox("Layout")
        page_layout = QVBoxLayout(page)
        self._cover = QCheckBox("Cover page (project, author, date, revisions)")
        self._figure = QCheckBox(
            "Drawing of the structure on the cover (isometric; elevation in 2D)"
        )
        self._contents = QCheckBox("Table of contents")
        self._numbers = QCheckBox("Number chapters and subsections (1, 1.1, …)")
        self._chapter_break = QCheckBox("Start every chapter on a new page")
        self._running = QCheckBox("Header and footer with page numbers (PDF, Word)")
        self._together = QCheckBox("Keep tables on one page where they fit (PDF, Word)")
        for box, on in (
            (self._cover, options.cover),
            (self._figure, options.cover_figure),
            (self._contents, options.contents),
            (self._numbers, options.number_headings),
            (self._chapter_break, options.chapter_page_break),
            (self._running, options.header_footer),
            (self._together, options.keep_tables_together),
        ):
            box.setChecked(on)
            page_layout.addWidget(box)
        self._figure.setEnabled(options.cover)
        self._cover.toggled.connect(self._figure.setEnabled)
        layout.addWidget(page)

        layout.addWidget(QLabel("Chapters and tables in the report:"))
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["Section", "Tables"])
        self._tree.setRootIsDecorated(True)
        self._items: dict[str, QTreeWidgetItem] = {}
        chapters: dict[str, QTreeWidgetItem] = {}
        for section in sections:
            item = QTreeWidgetItem([section.title, str(section.tables) if section.tables else ""])
            item.setData(0, _KEY, section.key)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(
                0,
                Qt.CheckState.Unchecked
                if section.key in options.excluded
                else Qt.CheckState.Checked,
            )
            parent_item = chapters.get(section.parent or "")
            if parent_item is not None:
                parent_item.addChild(item)
            else:
                self._tree.addTopLevelItem(item)
                chapters[section.key] = item
            self._items[section.key] = item
        self._tree.expandAll()
        self._tree.resizeColumnToContents(0)
        self._tree.itemChanged.connect(self._on_item_changed)
        for chapter in chapters.values():
            self._sync_children(chapter)
        layout.addWidget(self._tree, 1)

        row = QHBoxLayout()
        select_all = QPushButton("Select All")
        select_none = QPushButton("Select None")
        select_all.clicked.connect(lambda: self._set_all(Qt.CheckState.Checked))
        select_none.clicked.connect(lambda: self._set_all(Qt.CheckState.Unchecked))
        row.addWidget(select_all)
        row.addWidget(select_none)
        row.addStretch(1)
        layout.addLayout(row)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.resize(520, 620)

    def _sync_children(self, chapter: QTreeWidgetItem) -> None:
        """A chapter left out greys its subsections (they go with it)."""
        on = chapter.checkState(0) == Qt.CheckState.Checked
        for i in range(chapter.childCount()):
            child = chapter.child(i)
            if child is not None:
                child.setDisabled(not on)

    def _on_item_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column == 0 and item.parent() is None:
            self._sync_children(item)

    def _set_all(self, state: Qt.CheckState) -> None:
        for item in self._items.values():
            item.setCheckState(0, state)

    def set_checked(self, key: str, on: bool) -> None:
        """Check or uncheck the section ``key`` (as a click would)."""
        self._items[key].setCheckState(0, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)

    def options(self) -> ReportOptions:
        """The chosen layout; ``excluded`` keeps the saved keys this report does not have."""
        shown = set(self._items)
        excluded = {k for k in self._options.excluded if k not in shown} | {
            key for key, item in self._items.items() if item.checkState(0) != Qt.CheckState.Checked
        }
        return replace(
            self._options,
            cover=self._cover.isChecked(),
            cover_figure=self._figure.isChecked(),
            contents=self._contents.isChecked(),
            number_headings=self._numbers.isChecked(),
            chapter_page_break=self._chapter_break.isChecked(),
            header_footer=self._running.isChecked(),
            keep_tables_together=self._together.isChecked(),
            language=str(self._language.currentData()),
            excluded=frozenset(excluded),
        )
