"""Material Tester: run one uniaxial material through a strain protocol.

Non-modal front-end for :class:`MaterialTesterViewModel`.  The test runs
in-process on the GUI thread: a 1200-point Steel02 history takes about 3 ms,
far below the point where a worker thread would pay off.
"""

from __future__ import annotations

import contextlib
import re
from typing import Any

import pyqtgraph as pg
from PySide6.QtCore import QLocale
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.viewmodels import ProjectViewModel
from opensees_studio.viewmodels.material_tester_vm import (
    PROTOCOL_LABELS,
    MaterialTesterViewModel,
)


def _parse_peaks(text: str) -> list[float]:
    """Peaks separated by spaces, commas or semicolons; point decimal separator."""
    return [float(tok) for tok in re.split(r"[\s,;]+", text.strip()) if tok]


class MaterialTesterDialog(QDialog):
    """Pick a material and a protocol, run, plot stress against strain."""

    def __init__(self, vm: ProjectViewModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Material Tester")
        self.setModal(False)
        self.resize(900, 560)
        self._vm = vm
        self._tester = MaterialTesterViewModel(vm.project)
        self._curve: Any | None = None
        self._build_ui()
        self._refresh_materials()
        self._on_protocol_changed()
        vm.projectChanged.connect(self._refresh_materials)
        vm.modelMutated.connect(self._refresh_materials)

    @property
    def view_model(self) -> MaterialTesterViewModel:
        return self._tester

    # ---- construction ----------------------------------------------------
    def _build_ui(self) -> None:
        root = QHBoxLayout(self)

        left = QVBoxLayout()
        form = QFormLayout()
        self._material = QComboBox()
        form.addRow("Material:", self._material)

        self._protocol = QComboBox()
        for kind, label in PROTOCOL_LABELS.items():
            self._protocol.addItem(label, kind)
        self._protocol.setCurrentIndex(self._protocol.findData(self._tester.protocol_kind))
        self._protocol.currentIndexChanged.connect(self._on_protocol_changed)
        form.addRow("Protocol:", self._protocol)

        self._amplitude = QDoubleSpinBox()
        self._amplitude.setLocale(QLocale(QLocale.Language.C))
        self._amplitude.setDecimals(6)
        self._amplitude.setRange(1e-6, 1.0)
        self._amplitude.setSingleStep(0.001)
        self._amplitude.setValue(self._tester.amplitude)
        self._amplitude_label = QLabel("Strain amplitude:")
        form.addRow(self._amplitude_label, self._amplitude)

        self._cycles = QSpinBox()
        self._cycles.setRange(1, 100)
        self._cycles.setValue(self._tester.n_cycles)
        self._cycles_label = QLabel("Cycles:")
        form.addRow(self._cycles_label, self._cycles)

        self._peaks = QLineEdit(" ".join(f"{p:g}" for p in self._tester.peaks))
        self._peaks.setToolTip("Positive, increasing peak strains, e.g. 0.0025 0.005 0.01")
        self._peaks_label = QLabel("Peak strains:")
        form.addRow(self._peaks_label, self._peaks)

        self._steps = QSpinBox()
        self._steps.setRange(2, 10000)
        self._steps.setValue(self._tester.steps_per_half_cycle)
        self._steps.setToolTip(
            "Equal increments on every branch: 0 to peak, peak to opposite peak, peak to 0."
        )
        form.addRow("Steps per half-cycle:", self._steps)
        left.addLayout(form)

        buttons = QHBoxLayout()
        self._run_btn = QPushButton("Run")
        self._run_btn.setDefault(True)
        self._run_btn.clicked.connect(self.run)
        buttons.addWidget(self._run_btn)
        self._export_btn = QPushButton("Export CSV…")
        self._export_btn.setEnabled(False)
        self._export_btn.clicked.connect(self._on_export)
        buttons.addWidget(self._export_btn)
        left.addLayout(buttons)

        self._summary = QPlainTextEdit()
        self._summary.setReadOnly(True)
        self._summary.setPlaceholderText("Run a test to see peak stress, stiffness and energy.")
        left.addWidget(self._summary, 1)
        root.addLayout(left, 0)

        pg.setConfigOptions(antialias=True)
        self._plot = pg.PlotWidget()
        self._plot.setBackground("#1e1e1e")
        self._plot.showGrid(x=True, y=True, alpha=0.3)
        # Stress and strain differ by orders of magnitude: scale axes independently.
        self._plot.getPlotItem().getViewBox().setAspectLocked(False)
        self._update_axis_labels()
        root.addWidget(self._plot, 1)

    # ---- state sync -------------------------------------------------------
    def _refresh_materials(self, *_: object) -> None:
        self._tester.set_project(self._vm.project)
        self._material.blockSignals(True)
        self._material.clear()
        for mat in self._tester.materials():
            self._material.addItem(self._tester.material_label(mat), mat.id)
        idx = self._material.findData(self._tester.material_id)
        self._material.setCurrentIndex(max(idx, 0))
        self._material.blockSignals(False)
        self._run_btn.setEnabled(self._material.count() > 0)
        self._update_axis_labels()

    def _on_protocol_changed(self, *_: object) -> None:
        kind = self._protocol.currentData()
        for w in (self._amplitude, self._amplitude_label):
            w.setVisible(kind in ("monotonic", "cyclic"))
        for w in (self._cycles, self._cycles_label):
            w.setVisible(kind == "cyclic")
        for w in (self._peaks, self._peaks_label):
            w.setVisible(kind == "increasing")

    def _update_axis_labels(self) -> None:
        unit = self._tester.stress_unit()
        self._plot.setLabel("bottom", "Strain")
        self._plot.setLabel("left", f"Stress [{unit}]" if unit else "Stress")

    def _push_inputs(self) -> str | None:
        """Copy widget values into the view model; return a parse error, if any."""
        t = self._tester
        t.material_id = self._material.currentData()
        t.protocol_kind = self._protocol.currentData()
        t.amplitude = self._amplitude.value()
        t.n_cycles = self._cycles.value()
        t.steps_per_half_cycle = self._steps.value()
        try:
            t.peaks = _parse_peaks(self._peaks.text())
        except ValueError:
            return "Peak strains must be numbers with a point decimal separator."
        return None

    # ---- actions ------------------------------------------------------------
    def run(self) -> bool:
        """Run the selected test and replace the previous curve."""
        self._clear_curve()
        parse_error = self._push_inputs()
        ok = False if parse_error else self._tester.run()
        self._summary.setPlainText(parse_error or self._tester.summary_text())
        self._export_btn.setEnabled(ok)
        if ok:
            self._curve = self._plot.plot(
                self._tester.strain,
                self._tester.stress,
                pen=pg.mkPen("#1f77b4", width=2),
            )
            self._plot.enableAutoRange()
        self._update_axis_labels()
        return ok

    def curve_data(self) -> tuple[Any, Any] | None:
        """The plotted (strain, stress) arrays, or ``None`` when the plot is empty."""
        if self._curve is None:
            return None
        return self._curve.getData()

    def _on_export(self) -> None:
        mat = self._tester.material()
        default = f"material_{mat.id}_{mat.type}.csv" if mat else "material_test.csv"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export stress-strain CSV", default, "CSV files (*.csv)"
        )
        if not path:
            return
        try:
            out = self._tester.export_csv(path)
        except OSError as exc:
            self._summary.appendPlainText(f"\nExport failed: {exc}")
            return
        self._summary.appendPlainText(f"\nExported {self._tester.strain.size} rows to {out}")

    def _clear_curve(self) -> None:
        if self._curve is not None:
            with contextlib.suppress(Exception):
                self._plot.removeItem(self._curve)
            self._curve = None
