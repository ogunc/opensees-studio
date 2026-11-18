"""Assign → Frame → Tendon (Post-Tensioning): a tendon in each selected member.

The tendon is a load, not a member: its anchorage forces and the pressure along
its parabola go into a Plain load pattern (see :mod:`core.prestress`).
"""

from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QDialogButtonBox, QFormLayout, QLabel, QVBoxLayout, QWidget

from opensees_studio.core import Project
from opensees_studio.core.help import TOPIC_PROPERTY
from opensees_studio.core.units import labels_for
from opensees_studio.views.dialogs.area_loads import _pattern_combo
from opensees_studio.views.float_field import FloatField
from opensees_studio.views.screen_fit import FittedDialog


class TendonLoadDialog(FittedDialog):
    """Force, profile (three eccentricities), losses and the load pattern."""

    def __init__(self, n_members: int, project: Project, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Assign Tendon (Post-Tensioning)")
        self.setProperty(TOPIC_PROPERTY, "assign.tendon")
        labels = labels_for(project.meta.units)
        layout = QVBoxLayout(self)
        intro = QLabel(
            f"A tendon in each of the <b>{n_members}</b> selected member(s), applied as its "
            "equivalent loads. Eccentricities along local y (a horizontal 2D beam's y is up: a "
            "tendon below the centroid is negative)."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        self.pattern = _pattern_combo(project)
        form.addRow("Load pattern:", self.pattern)
        self._force = self._field(1.0, minimum=1e-12)
        form.addRow(f"Jacking force [{labels.force}]:", self._force)
        self._e_i = self._field(0.0)
        self._e_mid = self._field(0.0)
        self._e_j = self._field(0.0)
        form.addRow(f"Eccentricity at end i [{labels.length}]:", self._e_i)
        form.addRow(f"Eccentricity at midspan [{labels.length}]:", self._e_mid)
        form.addRow(f"Eccentricity at end j [{labels.length}]:", self._e_j)
        self._stressed = QComboBox()
        for text, value in (("End i", "i"), ("End j", "j"), ("Both ends", "both")):
            self._stressed.addItem(text, value)
        form.addRow("Stressed from:", self._stressed)
        self._friction = self._field(0.0, minimum=0.0)
        form.addRow("Curvature friction μ [1/rad]:", self._friction)
        self._wobble = self._field(0.0, minimum=0.0)
        form.addRow(f"Wobble k [1/{labels.length}]:", self._wobble)
        self._loss = self._field(0.0, minimum=0.0)
        self._loss.setRange(0.0, 0.99)
        form.addRow("Long-term loss (fraction):", self._loss)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _field(value: float, *, minimum: float = -1e18) -> FloatField:
        field = FloatField()
        field.setRange(minimum, 1e18)
        field.setValue(value)
        return field

    def pattern_id(self) -> int | None:
        data = self.pattern.currentData()
        return None if data is None else int(data)

    def values(self) -> dict[str, object]:
        return {
            "force": self._force.value(),
            "e_i": self._e_i.value(),
            "e_mid": self._e_mid.value(),
            "e_j": self._e_j.value(),
            "stressed_from": self._stressed.currentData(),
            "friction": self._friction.value(),
            "wobble": self._wobble.value(),
            "long_term_loss": self._loss.value(),
        }
