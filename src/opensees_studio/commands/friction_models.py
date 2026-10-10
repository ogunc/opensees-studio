"""Commands that add, edit or remove friction models (sliding bearings)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from opensees_studio.commands.base import ProjectCommand
from opensees_studio.core import SLIDING_BEARING_CLASSES

if TYPE_CHECKING:
    from opensees_studio.core import Project
    from opensees_studio.viewmodels import ProjectViewModel


def friction_model_users(project: Project, friction_model_id: int) -> list[int]:
    """Ids of the sliding bearings that reference ``friction_model_id``."""
    return [
        el.id
        for el in project.elements
        if isinstance(el, SLIDING_BEARING_CLASSES) and el.friction_model_id == friction_model_id
    ]


class AddFrictionModelsCommand(ProjectCommand):
    """Add one or more friction models in a single undoable step."""

    def __init__(
        self, vm: ProjectViewModel, friction_models: list[Any], *, text: str | None = None
    ) -> None:
        super().__init__(vm, text or f"Add {len(friction_models)} friction model(s)")
        self._models = list(friction_models)

    def redo(self) -> None:
        existing = {fm.id for fm in self.project.friction_models}
        for fm in self._models:
            if fm.id in existing:
                raise ValueError(f"Friction model id {fm.id} already exists.")
        self.project.friction_models.extend(self._models)
        self._notify()

    def undo(self) -> None:
        ids = {fm.id for fm in self._models}
        self.project.friction_models[:] = [
            fm for fm in self.project.friction_models if fm.id not in ids
        ]
        self._notify()


class DeleteFrictionModelsCommand(ProjectCommand):
    """Remove friction models; refused while a sliding bearing references one."""

    def __init__(self, vm: ProjectViewModel, friction_model_ids: set[int]) -> None:
        super().__init__(vm, f"Delete {len(friction_model_ids)} friction model(s)")
        self._ids = set(friction_model_ids)
        self._removed: list[tuple[int, Any]] = []

    def redo(self) -> None:
        for fid in sorted(self._ids):
            users = friction_model_users(self.project, fid)
            if users:
                raise ValueError(
                    f"Friction model {fid} is used by bearing element(s) "
                    f"{', '.join(str(u) for u in users)}; reassign or delete them first."
                )
        self._removed = [
            (i, fm) for i, fm in enumerate(self.project.friction_models) if fm.id in self._ids
        ]
        self.project.friction_models[:] = [
            fm for fm in self.project.friction_models if fm.id not in self._ids
        ]
        self._notify()

    def undo(self) -> None:
        for i, fm in self._removed:
            self.project.friction_models.insert(min(i, len(self.project.friction_models)), fm)
        self._removed.clear()
        self._notify()


class UpdateFrictionModelCommand(ProjectCommand):
    """Replace a friction model's parameters (or its concrete type) at a given id."""

    def __init__(self, vm: ProjectViewModel, new_model: Any) -> None:
        super().__init__(vm, f"Edit friction model {new_model.id}")
        self._new = new_model
        self._old: Any | None = None
        self._index: int | None = None

    def redo(self) -> None:
        for i, fm in enumerate(self.project.friction_models):
            if fm.id == self._new.id:
                self._old = fm
                self._index = i
                self.project.friction_models[i] = self._new
                self._notify()
                return
        raise KeyError(f"Friction model with id={self._new.id} not found.")

    def undo(self) -> None:
        if self._old is not None and self._index is not None:
            self.project.friction_models[self._index] = self._old
        self._notify()
