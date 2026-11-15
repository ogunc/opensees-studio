"""What the window shows with no project open, and File → Open Recent.

An empty viewport with every menu greyed out says nothing about where to begin.
:class:`StartPage` takes its place until a project exists: the three ways to
start a model, Open, the projects opened last and the bundled examples.

:class:`RecentFiles` is the list behind both the page and File → Open Recent,
kept in ``QSettings`` (newest first, at most :data:`MAX_RECENT`). Files that no
longer exist are left out when the list is read, not deleted from it, so a
project on a disconnected drive comes back when the drive does.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import (
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from opensees_studio import __version__

SETTINGS_KEY = "file/recent"
MAX_RECENT = 10

#: ``examples/`` of a source checkout; a frozen bundle has none and hides the list.
EXAMPLES_DIR = Path(__file__).resolve().parents[3] / "examples"


class RecentFiles:
    """The most recently opened or saved projects, newest first."""

    def __init__(self, settings: QSettings | None = None) -> None:
        self._settings = settings

    def _store(self) -> QSettings:
        return self._settings if self._settings is not None else QSettings()

    def _stored(self) -> list[str]:
        value = self._store().value(SETTINGS_KEY, [])
        if isinstance(value, str):  # QSettings returns a one-item list as a string
            return [value] if value else []
        if isinstance(value, list | tuple):
            return [str(item) for item in value]
        return []

    def paths(self) -> list[Path]:
        """The stored projects that still exist."""
        return [Path(item) for item in self._stored() if Path(item).is_file()]

    def add(self, path: str | Path) -> None:
        """Put ``path`` first, dropping an older entry for the same file."""
        resolved = str(Path(path).resolve())
        kept = [item for item in self._stored() if Path(item).resolve() != Path(resolved)]
        self._store().setValue(SETTINGS_KEY, [resolved, *kept][:MAX_RECENT])

    def clear(self) -> None:
        self._store().remove(SETTINGS_KEY)


def example_projects(folder: Path = EXAMPLES_DIR) -> list[Path]:
    """The ``.osmodel`` files shipped in ``examples/``, by name."""
    if not folder.is_dir():
        return []
    return sorted(folder.glob("*.osmodel"), key=lambda p: p.name.lower())


class StartPage(QWidget):
    """New, Open, recent projects and examples, for a window with no project."""

    openRequested = Signal(str)  # a path from the recent or example list
    recoverRequested = Signal()  # the autosaved copy of a never-saved project

    def __init__(
        self,
        actions: dict[str, Callable[[], None]],
        recent: RecentFiles,
        examples: list[Path] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        """``actions`` maps ``new_3d``, ``new_2d``, ``new_truss`` and ``open`` to callbacks."""
        super().__init__(parent)
        self._recent = recent
        outer = QVBoxLayout(self)
        outer.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title = QLabel(f"<h1>OpenSees Studio</h1><p>Version {__version__}</p>")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(title)

        start = QGroupBox("Start")
        buttons = QGridLayout(start)
        for column, (key, text, tip) in enumerate(
            (
                ("new_3d", "New 3D Frame", "An empty 3D model with a Dead load pattern."),
                ("new_2d", "New 2D Frame…", "A planar frame in the X-Z plane, from the wizard."),
                ("new_truss", "New 2D Truss", "A planar truss: two translations per joint."),
                ("open", "Open…", "Open a project file (.osmodel)."),
            )
        ):
            button = QPushButton(text)
            button.setToolTip(tip)
            button.setMinimumHeight(36)
            button.clicked.connect(lambda _checked=False, k=key: actions[k]())
            buttons.addWidget(button, 0, column)
        outer.addWidget(start)

        # Shown only while an autosaved copy of a never-saved project exists.
        self._recover = QPushButton()
        self._recover.setMinimumHeight(36)
        self._recover.setToolTip(
            "Open the recovery copy autosaved before the application closed, as an "
            "unsaved project. Save it to keep it."
        )
        self._recover.clicked.connect(self.recoverRequested.emit)
        self._recover.setVisible(False)
        outer.addWidget(self._recover)

        lists = QHBoxLayout()
        recent_box = QGroupBox("Recent projects")
        recent_layout = QVBoxLayout(recent_box)
        self._recent_list = QListWidget()
        self._recent_empty = QLabel("No recent projects yet.")
        recent_layout.addWidget(self._recent_list)
        recent_layout.addWidget(self._recent_empty)
        lists.addWidget(recent_box, stretch=3)

        self._examples_list = QListWidget()
        examples = example_projects() if examples is None else examples
        for path in examples:
            self._examples_list.addItem(self._item(path))
        if examples:
            examples_box = QGroupBox("Examples")
            QVBoxLayout(examples_box).addWidget(self._examples_list)
            lists.addWidget(examples_box, stretch=2)
        outer.addLayout(lists)

        hint = QLabel("Double-click a project to open it. Press F1 for help.")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        outer.addWidget(hint)

        for widget in (self._recent_list, self._examples_list):
            widget.itemActivated.connect(self._on_activated)
        self.refresh()

    @staticmethod
    def _item(path: Path) -> QListWidgetItem:
        item = QListWidgetItem(path.stem)
        item.setToolTip(str(path))
        item.setData(Qt.ItemDataRole.UserRole, str(path))
        return item

    def refresh(self) -> None:
        """Reread the recent list (it changes whenever a project is opened or saved)."""
        self._recent_list.clear()
        paths = self._recent.paths()
        for path in paths:
            self._recent_list.addItem(self._item(path))
        self._recent_list.setVisible(bool(paths))
        self._recent_empty.setVisible(not paths)

    def set_recovery(self, snapshot: Path | None) -> None:
        """Offer the autosaved copy of an unsaved project, or hide the offer."""
        if snapshot is None:
            self._recover.setVisible(False)
            return
        from datetime import datetime

        stamp = datetime.fromtimestamp(snapshot.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
        self._recover.setText(f"Recover the unsaved project (autosaved {stamp})")
        self._recover.setVisible(True)

    def _on_activated(self, item: QListWidgetItem) -> None:
        self.openRequested.emit(str(item.data(Qt.ItemDataRole.UserRole)))
