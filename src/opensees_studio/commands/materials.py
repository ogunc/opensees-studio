"""Commands that add or remove materials."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from opensees_studio.commands.base import ProjectCommand

if TYPE_CHECKING:
    from opensees_studio.viewmodels import ProjectViewModel


class AddMaterialsCommand(ProjectCommand):
    """Add one or more materials in a single undoable step."""

    def __init__(self, vm: "ProjectViewModel", materials: list[Any], *, text: str | None = None) -> None:
        super().__init__(vm, text or f"Add {len(materials)} material(s)")
        self._materials = list(materials)

    def redo(self) -> None:
        existing = {m.id for m in self.project.materials}
        for mat in self._materials:
            if mat.id in existing:
                raise ValueError(f"Material id {mat.id} already exists.")
        self.project.materials.extend(self._materials)
        self._notify()

    def undo(self) -> None:
        ids = {m.id for m in self._materials}
        self.project.materials[:] = [m for m in self.project.materials if m.id not in ids]
        self._notify()


class DeleteMaterialsCommand(ProjectCommand):
    """Remove materials (no cascade)."""

    def __init__(self, vm: "ProjectViewModel", material_ids: set[int]) -> None:
        super().__init__(vm, f"Delete {len(material_ids)} material(s)")
        self._material_ids = set(material_ids)
        self._removed: list[tuple[int, Any]] = []

    def redo(self) -> None:
        self._removed = [
            (i, m) for i, m in enumerate(self.project.materials)
            if m.id in self._material_ids
        ]
        self.project.materials[:] = [
            m for m in self.project.materials if m.id not in self._material_ids
        ]
        self._notify()

    def undo(self) -> None:
        for i, m in self._removed:
            self.project.materials.insert(min(i, len(self.project.materials)), m)
        self._removed.clear()
        self._notify()
