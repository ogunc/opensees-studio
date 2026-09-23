"""Base class for undoable project mutations.

Every model edit goes through a :class:`ProjectCommand` so the
QUndoStack can replay it. Commands work *in place* on the project's
mutable lists — Pydantic re-validation is skipped for performance, so
each concrete command is responsible for keeping the model valid (no
duplicate ids, no dangling references). For a full re-validation
(e.g. before a Save), the caller can invoke
``project.validate_references()`` explicitly.
"""

from __future__ import annotations

import weakref
from typing import TYPE_CHECKING

from PySide6.QtGui import QUndoCommand

if TYPE_CHECKING:
    from opensees_studio.core import Project
    from opensees_studio.viewmodels import ProjectViewModel


class ProjectCommand(QUndoCommand):
    """Base for commands that mutate the active project.

    Concrete subclasses override :meth:`redo` and :meth:`undo` and call
    :meth:`_notify` exactly once at the end of each.

    The view model is held by weak reference. Once pushed, the command is
    owned by the view model's ``QUndoStack``, which the view model owns;
    a strong back-reference closes a cycle that only Python's cyclic GC
    can free, and freeing many such PySide6 cycles in one GC pass
    corrupts the heap (``0xC0000374``).
    """

    def __init__(self, vm: ProjectViewModel, text: str) -> None:
        super().__init__(text)
        self._vm_ref = weakref.ref(vm)

    @property
    def vm(self) -> ProjectViewModel:
        vm = self._vm_ref()
        if vm is None:
            raise RuntimeError(f"Cannot apply '{self.text()}': its view model is gone.")
        return vm

    @property
    def project(self) -> Project:
        if self.vm.project is None:
            raise RuntimeError(f"Cannot apply '{self.text()}': no active project.")
        return self.vm.project

    def _notify(self) -> None:
        """Mark the project dirty and fire the mutation signal."""
        vm = self.vm
        vm.mark_dirty()
        vm.modelMutated.emit()
