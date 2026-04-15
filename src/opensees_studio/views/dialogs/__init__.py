"""Modal dialogs for model definition, assignment, and analysis."""

from opensees_studio.views.dialogs.assign_load import AssignLoadDialog
from opensees_studio.views.dialogs.assign_property import (
    AssignMaterialDialog,
    AssignSectionDialog,
)
from opensees_studio.views.dialogs.assign_support import AssignSupportDialog, PRESETS
from opensees_studio.views.dialogs.case_manager import AnalysisCaseManagerDialog
from opensees_studio.views.dialogs.grid_system import GridSystemDialog
from opensees_studio.views.dialogs.material_library import MaterialLibraryDialog
from opensees_studio.views.dialogs.mirror import MirrorDialog
from opensees_studio.views.dialogs.move import MoveDialog
from opensees_studio.views.dialogs.replicate import ReplicateDialog
from opensees_studio.views.dialogs.run_analysis import RunAnalysisDialog
from opensees_studio.views.dialogs.section_library import SectionLibraryDialog

__all__ = [
    "GridSystemDialog",
    "AssignSupportDialog", "PRESETS",
    "AssignLoadDialog",
    "ReplicateDialog", "MoveDialog", "MirrorDialog",
    "MaterialLibraryDialog", "SectionLibraryDialog",
    "AssignSectionDialog", "AssignMaterialDialog",
    "AnalysisCaseManagerDialog", "RunAnalysisDialog",
]
