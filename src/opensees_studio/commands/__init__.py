"""Undoable project mutations — every model edit goes through one of these."""

from opensees_studio.commands.analysis import (
    AddAnalysisCasesCommand,
    DeleteAnalysisCasesCommand,
    UpdateAnalysisCaseCommand,
)
from opensees_studio.commands.base import ProjectCommand
from opensees_studio.commands.buildings import (
    AddDiaphragmCommand,
    AddRigidLinkCommand,
    RemoveConstraintsCommand,
    SetDesignSettingsCommand,
    SetMassSourceCommand,
    SetStoreysCommand,
)
from opensees_studio.commands.combinations import (
    AddCombinationsCommand,
    DeleteCombinationsCommand,
    UpdateCombinationCommand,
)
from opensees_studio.commands.constraints import (
    AddEqualDOFConstraintCommand,
)
from opensees_studio.commands.duplicates import (
    FixDuplicatesCommand,
    MergeJointsCommand,
    RepairReport,
)
from opensees_studio.commands.elements import (
    AddElementsCommand,
    AssignElementFieldsCommand,
    AssignMaterialCommand,
    AssignSectionCommand,
    ConvertElementTypeCommand,
    DeleteElementsCommand,
    ReplaceElementsCommand,
    UpdateElementFieldsCommand,
)
from opensees_studio.commands.friction_models import (
    AddFrictionModelsCommand,
    DeleteFrictionModelsCommand,
    UpdateFrictionModelCommand,
    friction_model_users,
)
from opensees_studio.commands.grid import (
    SetCoordSystemsCommand,
    SetGridSystemCommand,
)
from opensees_studio.commands.groups import (
    EditGroupMembersCommand,
    SetCustomCommandsCommand,
    SetGroupsCommand,
    SetSectionCutsCommand,
)
from opensees_studio.commands.loads import (
    AddElementLoadsCommand,
    AddNodalLoadsCommand,
    AddPatternLoadsCommand,
    AddPointElementLoadsCommand,
    AddTemperatureLoadsCommand,
    AddTrapezoidalElementLoadsCommand,
    DeleteLoadsCommand,
)
from opensees_studio.commands.materials import (
    AddMaterialsCommand,
    DeleteMaterialsCommand,
    UpdateMaterialCommand,
)
from opensees_studio.commands.mesh import MeshCommand
from opensees_studio.commands.nodes import (
    AddNodesCommand,
    DeleteNodesCommand,
    SetMassCommand,
    SetRestraintCommand,
    SetSpringCommand,
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
    SetPatternNodalLoadsCommand,
)
from opensees_studio.commands.tables import ApplyModelTablesCommand
from opensees_studio.commands.transforms import (
    MirrorCommand,
    MoveNodesCommand,
    Plane,
    ReplicateCommand,
)

__all__ = [
    "AddAnalysisCasesCommand",
    "AddCombinationsCommand",
    "AddDiaphragmCommand",
    "AddElementLoadsCommand",
    "AddElementsCommand",
    "AddEqualDOFConstraintCommand",
    "AddFrictionModelsCommand",
    "AddLoadPatternCommand",
    "AddMaterialsCommand",
    "AddNodalLoadsCommand",
    "AddNodesCommand",
    "AddPatternLoadsCommand",
    "AddPointElementLoadsCommand",
    "AddRigidLinkCommand",
    "AddSectionsCommand",
    "AddSpectrumCommand",
    "AddTemperatureLoadsCommand",
    "AddTimeSeriesCommand",
    "AddTrapezoidalElementLoadsCommand",
    "ApplyModelTablesCommand",
    "AssignElementFieldsCommand",
    "AssignMaterialCommand",
    "AssignSectionCommand",
    "ConvertElementTypeCommand",
    "DeleteAnalysisCasesCommand",
    "DeleteCombinationsCommand",
    "DeleteElementsCommand",
    "DeleteFrictionModelsCommand",
    "DeleteLoadsCommand",
    "DeleteMaterialsCommand",
    "DeleteNodesCommand",
    "DeleteSectionsCommand",
    "EditGroupMembersCommand",
    "FixDuplicatesCommand",
    "MergeJointsCommand",
    "MeshCommand",
    "MirrorCommand",
    "MoveNodesCommand",
    "Plane",
    "ProjectCommand",
    "RemoveConstraintsCommand",
    "RepairReport",
    "ReplaceElementsCommand",
    "ReplaceTimeSeriesCommand",
    "ReplicateCommand",
    "SetCoordSystemsCommand",
    "SetCustomCommandsCommand",
    "SetDesignSettingsCommand",
    "SetGridSystemCommand",
    "SetGroupsCommand",
    "SetMassCommand",
    "SetMassSourceCommand",
    "SetPatternNodalLoadsCommand",
    "SetRestraintCommand",
    "SetSectionCutsCommand",
    "SetSpringCommand",
    "SetStoreysCommand",
    "UpdateAnalysisCaseCommand",
    "UpdateCombinationCommand",
    "UpdateElementFieldsCommand",
    "UpdateFrictionModelCommand",
    "UpdateMaterialCommand",
    "UpdateSectionCommand",
    "friction_model_users",
]
