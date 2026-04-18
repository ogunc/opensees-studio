"""ProjectViewModel — Qt-aware adapter holding the current project + undo stack.

Two distinct change signals:
- ``projectChanged(Project | None)`` — the *identity* changed (open, new, close)
- ``modelMutated()`` — the same project's contents changed (commands)

Views typically connect to both: ``projectChanged`` triggers a full
re-bind (re-attach renderer, reset camera); ``modelMutated`` triggers
a re-paint without losing camera/selection state.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QUndoStack

from opensees_studio.core import Project
from opensees_studio.services import load_project, save_project


class ProjectViewModel(QObject):
    """Holds the current Project, its file path, dirty state, and undo stack."""

    projectChanged = Signal(object)   # emits Project | None
    modelMutated = Signal()           # same project, mutated by a command
    dirtyChanged = Signal(bool)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._project: Project | None = None
        self._path: Path | None = None
        self._dirty: bool = False

        self._undo_stack = QUndoStack(self)
        # Keep dirty in sync with the stack: clean index ⇒ saved baseline.
        self._undo_stack.cleanChanged.connect(self._on_stack_clean_changed)

    @Slot(bool)
    def _on_stack_clean_changed(self, clean: bool) -> None:
        # Guard against the late-fire that Qt sends during destruction.
        try:
            self._set_dirty(not clean)
        except RuntimeError:
            pass

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

    @property
    def undo_stack(self) -> QUndoStack:
        return self._undo_stack

    # ── lifecycle ────────────────────────────────────────────────────
    def new_project(self, ndm: int = 3, ndf: int = 6) -> None:
        # No pre-loaded materials / sections: the Draw tools lazily
        # create a sensible Elastic default on their first use (so the
        # user never has to "define a material before drawing"), but
        # the empty starter project stays clean and predictable for
        # everything else (commands, tests, round-trip).
        self._project = Project(ndm=ndm, ndf=ndf)
        self._path = None
        self._undo_stack.clear()
        self._set_dirty(False)
        self.projectChanged.emit(self._project)

    def open(self, path: str | Path) -> None:
        path = Path(path)
        self._project = load_project(path)
        self._path = path
        self._undo_stack.clear()
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
        self._undo_stack.setClean()
        self._set_dirty(False)
        return out

    def close(self) -> None:
        self._project = None
        self._path = None
        self._undo_stack.clear()
        self._set_dirty(False)
        self.projectChanged.emit(None)

    # ── command application ─────────────────────────────────────────
    def apply_command(self, command) -> None:  # type: ignore[no-untyped-def]
        """Push a :class:`ProjectCommand` to the undo stack and execute it."""
        if self._project is None:
            raise RuntimeError("Cannot apply a command without an active project.")
        self._undo_stack.push(command)

    def mark_dirty(self) -> None:
        self._set_dirty(True)

    def _set_dirty(self, value: bool) -> None:
        if self._dirty != value:
            self._dirty = value
            self.dirtyChanged.emit(value)
