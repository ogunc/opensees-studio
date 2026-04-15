"""Modal dialogs for model definition and assignment."""

from opensees_studio.views.dialogs.assign_load import AssignLoadDialog
from opensees_studio.views.dialogs.assign_support import AssignSupportDialog, PRESETS
from opensees_studio.views.dialogs.grid_system import GridSystemDialog
from opensees_studio.views.dialogs.mirror import MirrorDialog
from opensees_studio.views.dialogs.move import MoveDialog
from opensees_studio.views.dialogs.replicate import ReplicateDialog

__all__ = [
    "GridSystemDialog",
    "AssignSupportDialog", "PRESETS",
    "AssignLoadDialog",
    "ReplicateDialog", "MoveDialog", "MirrorDialog",
]
