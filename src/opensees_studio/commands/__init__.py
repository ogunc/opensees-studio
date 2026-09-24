"""Undoable project mutations — every model edit goes through one of these."""

from opensees_studio.commands.analysis import (
    AddAnalysisCasesCommand,
    DeleteAnalysisCasesCommand,
    UpdateAnalysisCaseCommand,
)
from opensees_studio.commands.base import ProjectCommand
from opensees_studio.commands.constraints import (
    AddEqualDOFConstraintCommand,
)
from opensees_studio.commands.elements import (
    AddElementsCommand,
    AssignMaterialCommand,
    AssignSectionCommand,
    ConvertElementTypeCommand,
    DeleteElementsCommand,
    ReplaceElementsCommand,
    UpdateElementFieldsCommand,
)
from opensees_studio.commands.grid import (
    SetCoordSystemsCommand,
    SetGridSystemCommand,
)
from opensees_studio.commands.loads import (
    AddElementLoadsCommand,
    AddNodalLoadsCommand,
)
from opensees_studio.commands.materials import (
    AddMaterialsCommand,
    DeleteMaterialsCommand,
    UpdateMaterialCommand,
)
from opensees_studio.commands.nodes import (
    AddNodesCommand,
    DeleteNodesCommand,
    SetMassCommand,
    SetRestraintCommand,
)
from opensees_studio.commands.sections import (
    AddSectionsCommand,
    DeleteSectionsCommand,
    UpdateSectionCommand,
)
from opensees_studio.commands.series_and_patterns import (
    AddLoadPatternCommand,
    AddTimeSeriesCommand,
    ReplaceTimeSeriesCommand,
)
from opensees_studio.commands.transforms import (
    MirrorCommand,
    MoveNodesCommand,
    Plane,
    ReplicateCommand,
)

__all__ = [
    "AddAnalysisCasesCommand",
    "AddElementLoadsCommand",
    "AddElementsCommand",
    "AddEqualDOFConstraintCommand",
    "AddLoadPatternCommand",
    "AddMaterialsCommand",
    "AddNodalLoadsCommand",
    "AddNodesCommand",
    "AddSectionsCommand",
    "AddTimeSeriesCommand",
    "AssignMaterialCommand",
    "AssignSectionCommand",
    "ConvertElementTypeCommand",
    "DeleteAnalysisCasesCommand",
    "DeleteElementsCommand",
    "DeleteMaterialsCommand",
    "DeleteNodesCommand",
    "DeleteSectionsCommand",
    "MirrorCommand",
    "MoveNodesCommand",
    "Plane",
    "ProjectCommand",
    "ReplaceElementsCommand",
    "ReplaceTimeSeriesCommand",
    "ReplicateCommand",
    "SetCoordSystemsCommand",
    "SetGridSystemCommand",
    "SetMassCommand",
    "SetRestraintCommand",
    "UpdateAnalysisCaseCommand",
    "UpdateElementFieldsCommand",
    "UpdateMaterialCommand",
    "UpdateSectionCommand",
]
