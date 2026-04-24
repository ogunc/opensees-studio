"""Modal dialogs for model definition, assignment, and analysis."""

from opensees_studio.views.dialogs.add_node import AddNodeDialog
from opensees_studio.views.dialogs.assign_equal_dof import AssignEqualDOFDialog
from opensees_studio.views.dialogs.assign_load import AssignLoadDialog
from opensees_studio.views.dialogs.assign_hinge import AssignHingeDialog
from opensees_studio.views.dialogs.assign_masses import AssignMassesDialog
from opensees_studio.views.dialogs.assign_zls import AssignZeroLengthSectionDialog
from opensees_studio.views.dialogs.coord_grid_systems import (
    CoordSystemDataDialog,
    CoordinateGridSystemsDialog,
)
from opensees_studio.views.dialogs.define_grid_data import (
    DefineGridSystemDataDialog,
)
from opensees_studio.views.dialogs.display_options import DisplayOptionsDialog
from opensees_studio.views.dialogs.locate_origin import (
    CoordSystemLocationOrientationDialog,
)
from opensees_studio.views.dialogs.linear_time_series import LinearTimeSeriesDialog
from opensees_studio.views.dialogs.path_time_series import PathTimeSeriesDialog
from opensees_studio.views.dialogs.plain_pattern import PlainPatternDialog
from opensees_studio.views.dialogs.quick_grid_lines import QuickGridLinesDialog
from opensees_studio.views.dialogs.uniform_excitation import UniformExcitationDialog
from opensees_studio.views.dialogs.distributed_load import AssignDistributedLoadDialog
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
    "GridSystemDialog", "AddNodeDialog",
    "AssignEqualDOFDialog",
    "CoordinateGridSystemsDialog", "CoordSystemDataDialog",
    "DefineGridSystemDataDialog",
    "DisplayOptionsDialog",
    "CoordSystemLocationOrientationDialog",
    "QuickGridLinesDialog",
    "LinearTimeSeriesDialog",
    "PathTimeSeriesDialog", "UniformExcitationDialog",
    "PlainPatternDialog",
    "AssignSupportDialog", "PRESETS",
    "AssignLoadDialog",
    "AssignHingeDialog",
    "AssignMassesDialog",
    "AssignZeroLengthSectionDialog",
    "AssignDistributedLoadDialog",
    "ReplicateDialog", "MoveDialog", "MirrorDialog",
    "MaterialLibraryDialog", "SectionLibraryDialog",
    "AssignSectionDialog", "AssignMaterialDialog",
    "AnalysisCaseManagerDialog", "RunAnalysisDialog",
]
