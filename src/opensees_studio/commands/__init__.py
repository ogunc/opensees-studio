"""Undoable project mutations — every model edit goes through one of these."""

from opensees_studio.commands.base import ProjectCommand
from opensees_studio.commands.elements import (
    AddElementsCommand,
    AssignMaterialCommand,
    AssignSectionCommand,
    DeleteElementsCommand,
)
from opensees_studio.commands.loads import AddNodalLoadsCommand
from opensees_studio.commands.materials import (
    AddMaterialsCommand,
    DeleteMaterialsCommand,
    UpdateMaterialCommand,
)
from opensees_studio.commands.nodes import (
    AddNodesCommand,
    DeleteNodesCommand,
    SetRestraintCommand,
)
from opensees_studio.commands.sections import (
    AddSectionsCommand,
    DeleteSectionsCommand,
    UpdateSectionCommand,
)
from opensees_studio.commands.transforms import (
    MirrorCommand,
    MoveNodesCommand,
    Plane,
    ReplicateCommand,
)

__all__ = [
    "ProjectCommand",
    "AddNodesCommand", "DeleteNodesCommand", "SetRestraintCommand",
    "AddElementsCommand", "DeleteElementsCommand",
    "AssignSectionCommand", "AssignMaterialCommand",
    "AddMaterialsCommand", "DeleteMaterialsCommand", "UpdateMaterialCommand",
    "AddSectionsCommand", "DeleteSectionsCommand", "UpdateSectionCommand",
    "AddNodalLoadsCommand",
    "MoveNodesCommand", "ReplicateCommand", "MirrorCommand", "Plane",
]
