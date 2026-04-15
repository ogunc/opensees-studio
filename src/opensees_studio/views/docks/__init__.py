"""Reusable dock widget contents."""

from opensees_studio.views.docks.deformed_shape import DeformedShapeView
from opensees_studio.views.docks.mode_shape_animator import ModeShapeAnimator
from opensees_studio.views.docks.property_editor import PropertyEditorDock
from opensees_studio.views.docks.results_panel import ResultsPanel

__all__ = ["PropertyEditorDock", "ResultsPanel",
           "DeformedShapeView", "ModeShapeAnimator"]
