"""ProjectViewModel — the Qt-aware holder of the current project.

Bridges the pure-Python ``Project`` model to Qt views. Phase 3 keeps it
minimal: hold a project, signal when it changes, expose load/save
convenience. Phase 4 will add command-based mutations (add node, etc.)
through ``QUndoStack``.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal

from opensees_studio.core import Project
from opensees_studio.services import load_project, save_project


class ProjectViewModel(QObject):
    """Holds the current Project and notifies on change."""

    projectChanged = Signal(object)   # emits the new Project (or None)
    dirtyChanged = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._project: Project | None = None
        self._path: Path | None = None
        self._dirty: bool = False

    # ── read ─────────────────────────────────────────────────────────
    @property
    def project(self) -> Project | None:
        return self._project

    @property
    def path(self) -> Path | None:
        return self._path

    @property
    def is_dirty(self) -> bool:
        return self._dirty

    # ── write ────────────────────────────────────────────────────────
    def new_project(self, ndm: int = 3, ndf: int = 6) -> None:
        self._project = Project(ndm=ndm, ndf=ndf)
        self._path = None
        self._set_dirty(False)
        self.projectChanged.emit(self._project)

    def open(self, path: str | Path) -> None:
        path = Path(path)
        self._project = load_project(path)
        self._path = path
        self._set_dirty(False)
        self.projectChanged.emit(self._project)

    def save(self, path: str | Path | None = None) -> Path:
        if self._project is None:
            raise RuntimeError("No project to save.")
        target = Path(path) if path is not None else self._path
        if target is None:
            raise ValueError("No path provided and no current path.")
        out = save_project(self._project, target)
        self._path = out
        self._set_dirty(False)
        return out

    def close(self) -> None:
        self._project = None
        self._path = None
        self._set_dirty(False)
        self.projectChanged.emit(None)

    def mark_dirty(self) -> None:
        self._set_dirty(True)

    def _set_dirty(self, value: bool) -> None:
        if self._dirty != value:
            self._dirty = value
            self.dirtyChanged.emit(value)
