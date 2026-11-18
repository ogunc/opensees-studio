"""Design → Concrete Frame Check (ACI 318-19): settings, a run, and the member table.

The window reads the case results the session has and runs nothing itself; the
check is :func:`services.concrete_design.concrete_frame_check`. OK stores the
settings with the project (one undoable command, by the window).
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core.design.settings import ConcreteDesign, DesignSettings
from opensees_studio.core.help import TOPIC_PROPERTY
from opensees_studio.core.units import UnitSystem, labels_for, length_scale, stress_scale
from opensees_studio.services.concrete_design import ConcreteReport, concrete_frame_check
from opensees_studio.views.float_field import FloatField
from opensees_studio.views.screen_fit import FittedDialog, MessageArea

COLUMNS = ("Member", "Section", "Ratio", "Governing check", "ACI 318-19", "Load set", "Station")


class ConcreteDesignDialog(FittedDialog):
    """Stirrups, λ and the transverse type; Check fills the table."""

    def __init__(
        self, project: Any, results: dict[int, Any], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Concrete Frame Check (ACI 318-19)")
        self.setProperty(TOPIC_PROPERTY, "design.concrete_check")
        self._project = project
        self._results = results
        self._report: ConcreteReport | None = None
        self.show_ratios_requested = False
        units = project.meta.units
        labels = labels_for(units)
        mm = length_scale(UnitSystem.SI_MM_N, units)
        mpa = stress_scale(UnitSystem.SI_MM_N, units)
        stored = (project.design or DesignSettings()).concrete or ConcreteDesign()
        layout = QVBoxLayout(self)
        intro = QLabel(
            "Every frame member whose section is a fibre section of concrete and bars (or the "
            "elastic twin the Concrete Section Wizard made) is checked at 25 stations over the "
            "load sets of Design → Steel Frame Check: axial force and bending by strain "
            "compatibility, biaxial bending, shear, the torsion threshold, minimum steel and "
            "the tension-controlled limit of beams."
        )
        intro.setWordWrap(True)
        layout.addWidget(intro)
        form = QFormLayout()
        self._av = self._field(stored.stirrup_area or 157.0 * mm * mm)
        form.addRow(f"Stirrup legs area Av [{labels.length}²]:", self._av)
        self._s = self._field(stored.stirrup_spacing or 150.0 * mm)
        form.addRow(f"Stirrup spacing s [{labels.length}]:", self._s)
        self._fyt = self._field(stored.fyt or 420.0 * mpa)
        form.addRow(f"Stirrup yield fyt [{labels.stress}]:", self._fyt)
        self._lam = self._field(stored.lam)
        self._lam.setRange(0.5, 1.0)
        form.addRow("Lightweight factor λ:", self._lam)
        self._transverse = QComboBox()
        self._transverse.addItem("Tied (φ = 0.65)", "tied")
        self._transverse.addItem("Spiral (φ = 0.75)", "spiral")
        self._transverse.setCurrentIndex(max(0, self._transverse.findData(stored.transverse)))
        form.addRow("Transverse reinforcement:", self._transverse)
        layout.addLayout(form)
        run = QPushButton("Check")
        run.clicked.connect(self.run)
        layout.addWidget(run)
        self._table = QTableWidget(0, len(COLUMNS))
        self._table.setHorizontalHeaderLabels(list(COLUMNS))
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._table.setMinimumHeight(200)
        layout.addWidget(self._table)
        self._message = MessageArea()
        layout.addWidget(self._message)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self._ratios = QPushButton("Show ratios on model")
        self._ratios.setEnabled(False)
        self._ratios.clicked.connect(self._show_ratios)
        buttons.addButton(self._ratios, QDialogButtonBox.ButtonRole.ActionRole)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _field(value: float) -> FloatField:
        field = FloatField()
        field.setRange(1e-12, 1e18)
        field.setValue(value)
        return field

    def settings(self) -> DesignSettings:
        base = self._project.design or DesignSettings()
        concrete = ConcreteDesign(
            stirrup_area=self._av.value(),
            stirrup_spacing=self._s.value(),
            fyt=self._fyt.value(),
            lam=self._lam.value(),
            transverse=self._transverse.currentData(),
        )
        return base.model_copy(update={"concrete": concrete})

    def report(self) -> ConcreteReport | None:
        return self._report

    def run(self) -> None:
        settings = self.settings()
        self._report = report = concrete_frame_check(self._project, self._results, settings)
        designed = [m for m in report.members if m.status != "not designed"]
        self._table.setRowCount(len(report.members))
        for row, member in enumerate(sorted(report.members, key=lambda m: -m.ratio)):
            cells = (
                str(member.element_id),
                member.section,
                f"{member.ratio:.3f}" if member.status != "not designed" else "—",
                member.check or "; ".join(member.notes),
                member.clause,
                member.load_set,
                f"{member.station:.2f}",
            )
            for column, text in enumerate(cells):
                self._table.setItem(row, column, QTableWidgetItem(text))
        level = "error" if report.failing else "info" if designed else "warning"
        self._message.show_message(" ".join([report.summary(), *report.notes]), level)
        self._ratios.setEnabled(bool(designed))

    def _show_ratios(self) -> None:
        self.show_ratios_requested = True
        self.accept()
