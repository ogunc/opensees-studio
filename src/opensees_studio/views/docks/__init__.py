"""Reusable dock widget contents."""

from opensees_studio.views.docks.deformed_shape import DeformedShapeView
from opensees_studio.views.docks.force_diagram import ForceDiagramView
from opensees_studio.views.docks.hysteresis import HysteresisView
from opensees_studio.views.docks.mode_shape_animator import ModeShapeAnimator
from opensees_studio.views.docks.property_editor import PropertyEditorDock
from opensees_studio.views.docks.pushover_curve import PushoverCurveView
from opensees_studio.views.docks.response_spectrum import ResponseSpectrumView
from opensees_studio.views.docks.results_panel import ResultsPanel
from opensees_studio.views.docks.time_history import TimeHistoryView

__all__ = [
    "PropertyEditorDock", "ResultsPanel",
    "DeformedShapeView", "ModeShapeAnimator",
    "ForceDiagramView", "TimeHistoryView", "HysteresisView",
    "PushoverCurveView", "ResponseSpectrumView",
]
