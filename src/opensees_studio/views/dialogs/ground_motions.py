"""Ground Motions catalog dialog (Define menu, beside Material Tester).

Import acceleration records (format auto-detected, with an explicit
override and a dt field for bare value lists), inspect their metadata
(PGA, D5-95, status), preview the acceleration trace, remove unused
entries and relink a missing or changed file (hash re-checked).

GM-2 additions: a response-spectrum plot (log period axis, Sa in g) of
the selected records with the project's target spectrum overlaid, a
target editor (TBDY 2018 from SDS and SD1, or a user period/Sa table)
and a Scale panel (PGA, Sa(T1), period range) whose Apply writes the
factors to the Path time series backed by the records through one
undoable command. Records are never modified by scaling.

Records enter the project as catalog references (relative path +
content hash) via undoable commands; sample values are never embedded
in ``.osmodel``.
"""

from __future__ import annotations

import contextlib
from typing import Any

import pyqtgraph as pg
from PySide6.QtCore import QItemSelectionModel, QLocale, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.commands.ground_motions import (
    AddGroundMotionCommand,
    RelinkGroundMotionCommand,
    RemoveGroundMotionCommand,
    SetGroundMotionUnitsCommand,
    SetSeriesFactorsCommand,
    SetTargetSpectrumCommand,
)
from opensees_studio.core import TBDY_RANGE_PRESET, ScalingMethod
from opensees_studio.viewmodels import ProjectViewModel
from opensees_studio.viewmodels.ground_motion_catalog_vm import (
    FORMAT_CHOICES,
    METHOD_CHOICES,
    PLOT_PERIODS,
    UNIT_CHOICES,
    GroundMotionCatalogViewModel,
    ScalingPreview,
)

_COLUMNS = ("Name", "dt [s]", "npts", "PGA", "D5-95 [s]", "Units", "Status")

_FILE_FILTER = "Ground-motion records (*.AT2 *.at2 *.acc *.txt *.dat);;All files (*)"
_TABLE_FILTER = "Spectrum tables (*.txt *.csv *.dat);;All files (*)"

_RECORD_PENS = ("#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd", "#8c564b", "#e377c2")


class GroundMotionsDialog(QDialog):
    """Catalog of the project's ground-motion records."""

    def __init__(self, vm: ProjectViewModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Ground Motions")
        self.setModal(False)
        self.resize(1180, 820)
        self._vm = vm
        self._catalog = GroundMotionCatalogViewModel(vm.project, self._base_dir())
        self._curve: Any | None = None
        self._spectrum_curves: list[Any] = []
        self._target_curve: Any | None = None
        self._scaled_curve: Any | None = None
        self._preview: ScalingPreview | None = None
        self._syncing = False
        self._build_ui()
        self._refresh()
        vm.projectChanged.connect(self._on_project_changed)
        vm.modelMutated.connect(self._refresh)

    @property
    def view_model(self) -> GroundMotionCatalogViewModel:
        return self._catalog

    def _base_dir(self):  # type: ignore[no-untyped-def]
        return self._vm.path.parent if self._vm.path is not None else None

    # ---- construction ------------------------------------------------------
    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        controls = QHBoxLayout()
        self._import_btn = QPushButton("&Import…")
        self._import_btn.clicked.connect(self._on_import)
        controls.addWidget(self._import_btn)

        controls.addWidget(QLabel("Format:"))
        self._format = QComboBox()
        for key, label in FORMAT_CHOICES:
            self._format.addItem(label, key)
        self._format.currentIndexChanged.connect(self._on_format_changed)
        self._format.setToolTip("Override the content-based auto-detection for the next import.")
        controls.addWidget(self._format)

        self._dt_label = QLabel("dt [s]:")
        controls.addWidget(self._dt_label)
        self._dt = QDoubleSpinBox()
        self._dt.setLocale(QLocale(QLocale.Language.C))
        self._dt.setDecimals(6)
        self._dt.setRange(1e-6, 10.0)
        self._dt.setSingleStep(0.005)
        self._dt.setValue(0.01)
        self._dt.setToolTip("Sampling interval for a bare value list (single-column import).")
        controls.addWidget(self._dt)

        controls.addWidget(QLabel("Units:"))
        self._units = QComboBox()
        for key, label in UNIT_CHOICES:
            self._units.addItem(label, key)
        self._units.setToolTip("Acceleration units of the selected record (needed for scaling).")
        self._units.currentIndexChanged.connect(self._on_units_changed)
        controls.addWidget(self._units)

        controls.addStretch(1)
        self._relink_btn = QPushButton("Re&link…")
        self._relink_btn.clicked.connect(self._on_relink)
        controls.addWidget(self._relink_btn)
        self._remove_btn = QPushButton("&Remove")
        self._remove_btn.clicked.connect(self._on_remove)
        controls.addWidget(self._remove_btn)
        root.addLayout(controls)

        body = QHBoxLayout()
        self._table = QTableWidget(0, len(_COLUMNS))
        self._table.setHorizontalHeaderLabels(_COLUMNS)
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        body.addWidget(self._table, 1)

        pg.setConfigOptions(antialias=True)
        plots = QVBoxLayout()
        self._plot = pg.PlotWidget()
        self._plot.setBackground("#1e1e1e")
        self._plot.showGrid(x=True, y=True, alpha=0.3)
        self._plot.setLabel("bottom", "Time [s]")
        self._plot.setLabel("left", "Acceleration")
        plots.addWidget(self._plot, 1)

        self._spectrum_plot = pg.PlotWidget()
        self._spectrum_plot.setBackground("#1e1e1e")
        self._spectrum_plot.showGrid(x=True, y=True, alpha=0.3)
        self._spectrum_plot.setLogMode(x=True, y=False)
        self._spectrum_plot.setLabel("bottom", "Period [s]")
        self._spectrum_plot.setLabel("left", "Sa [g], 5 % damping")
        self._spectrum_plot.addLegend(offset=(-10, 10))
        plots.addWidget(self._spectrum_plot, 1)
        body.addLayout(plots, 1)
        root.addLayout(body, 1)

        panels = QHBoxLayout()
        panels.addWidget(self._build_target_group(), 1)
        panels.addWidget(self._build_scale_group(), 2)
        root.addLayout(panels)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        root.addWidget(self._status)

        self._on_format_changed()
        self._on_method_changed()

    @staticmethod
    def _spin(
        lo: float, hi: float, value: float, decimals: int = 3, step: float = 0.1
    ) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setLocale(QLocale(QLocale.Language.C))
        spin.setDecimals(decimals)
        spin.setRange(lo, hi)
        spin.setSingleStep(step)
        spin.setValue(value)
        return spin

    def _build_target_group(self) -> QGroupBox:
        group = QGroupBox("Target spectrum [g]")
        form = QFormLayout(group)
        self._target_kind = QComboBox()
        self._target_kind.addItem("TBDY 2018 (SDS, SD1)", "tbdy2018")
        self._target_kind.addItem("User table (period, Sa)", "user")
        self._target_kind.currentIndexChanged.connect(self._on_target_kind_changed)
        form.addRow("Kind:", self._target_kind)
        self._sds = self._spin(0.001, 10.0, 1.0, decimals=4, step=0.05)
        self._sds.setToolTip("Short-period design spectral acceleration from the AFAD TDTH map.")
        form.addRow("SDS [g]:", self._sds)
        self._sd1 = self._spin(0.001, 10.0, 0.4, decimals=4, step=0.05)
        self._sd1.setToolTip("1 s design spectral acceleration from the AFAD TDTH map.")
        form.addRow("SD1 [g]:", self._sd1)
        self._table_btn = QPushButton("Import &table…")
        self._table_btn.clicked.connect(self._on_import_table)
        form.addRow("", self._table_btn)
        self._set_target_btn = QPushButton("Set &target")
        self._set_target_btn.clicked.connect(self._on_set_target)
        form.addRow("", self._set_target_btn)
        self._target_label = QLabel("No target spectrum.")
        self._target_label.setWordWrap(True)
        form.addRow(self._target_label)
        return group

    def _build_scale_group(self) -> QGroupBox:
        group = QGroupBox("Scale selected records (factors go to their time series)")
        outer = QVBoxLayout(group)
        form = QFormLayout()
        self._method = QComboBox()
        for key, label in METHOD_CHOICES:
            self._method.addItem(label, key)
        self._method.currentIndexChanged.connect(self._on_method_changed)
        form.addRow("Method:", self._method)
        self._target_pga = self._spin(0.001, 10.0, 0.4, decimals=4, step=0.05)
        form.addRow("Target PGA [g]:", self._target_pga)
        self._t1 = self._spin(0.01, 20.0, 1.0, decimals=3, step=0.05)
        self._t1.setToolTip("Fundamental period of the structure.")
        form.addRow("T1 [s]:", self._t1)
        preset = TBDY_RANGE_PRESET
        self._range_a = self._spin(0.01, 5.0, preset.a, decimals=2, step=0.05)
        self._range_b = self._spin(0.02, 10.0, preset.b, decimals=2, step=0.05)
        self._alpha = self._spin(0.1, 5.0, preset.alpha, decimals=2, step=0.05)
        self._alpha.setToolTip(
            f"{preset.label}: alpha {preset.alpha:g} for SRSS pairs; "
            "for single components alpha is the engineer's choice."
        )
        form.addRow(f"Range a, b (x T1) [{preset.label}]:", self._range_a)
        form.addRow("", self._range_b)
        form.addRow("alpha (mean / target floor):", self._alpha)
        self._individual = QCheckBox("Individual factors (shape-fit each, then uniform)")
        form.addRow("", self._individual)
        self._pairs = QCheckBox("Pair consecutive selections as H1, H2 (SRSS)")
        form.addRow("", self._pairs)
        outer.addLayout(form)
        buttons = QHBoxLayout()
        self._preview_btn = QPushButton("&Preview")
        self._preview_btn.clicked.connect(self.preview_scaling)
        buttons.addWidget(self._preview_btn)
        self._apply_btn = QPushButton("&Apply")
        self._apply_btn.clicked.connect(self.apply_scaling)
        self._apply_btn.setEnabled(False)
        buttons.addWidget(self._apply_btn)
        buttons.addStretch(1)
        outer.addLayout(buttons)
        self._factors_label = QLabel("")
        self._factors_label.setWordWrap(True)
        outer.addWidget(self._factors_label)
        return group

    # ---- state sync ----------------------------------------------------------
    def _on_project_changed(self, *_: object) -> None:
        self._catalog.set_project(self._vm.project, self._base_dir())
        self._refresh()

    def _on_format_changed(self, *_: object) -> None:
        # dt is consumed by single-column imports only; auto-detect may
        # still land on single_column, so keep it editable there too.
        enabled = self._format.currentData() in (None, "single_column")
        self._dt.setEnabled(enabled)
        self._dt_label.setEnabled(enabled)

    def _on_target_kind_changed(self, *_: object) -> None:
        tbdy = self._target_kind.currentData() == "tbdy2018"
        self._sds.setEnabled(tbdy)
        self._sd1.setEnabled(tbdy)
        self._table_btn.setEnabled(not tbdy)
        self._set_target_btn.setEnabled(tbdy)

    def _on_method_changed(self, *_: object) -> None:
        method = self._method.currentData()
        self._target_pga.setEnabled(method == "pga")
        self._t1.setEnabled(method != "pga")
        for w in (self._range_a, self._range_b, self._alpha, self._individual, self._pairs):
            w.setEnabled(method == "period_range")
        self._clear_preview()

    def _clear_preview(self) -> None:
        self._preview = None
        self._apply_btn.setEnabled(False)
        self._factors_label.setText("")
        if self._scaled_curve is not None:
            with contextlib.suppress(Exception):
                self._spectrum_plot.removeItem(self._scaled_curve)
            self._scaled_curve = None

    def selected_record(self):  # type: ignore[no-untyped-def]
        row = self._table.currentRow()
        records = self._catalog.records()
        return records[row] if 0 <= row < len(records) else None

    def selected_records(self) -> list:  # type: ignore[type-arg]
        """Selected catalog entries in row order (multi-selection)."""
        records = self._catalog.records()
        rows = sorted({index.row() for index in self._table.selectionModel().selectedRows()})
        return [records[r] for r in rows if 0 <= r < len(records)]

    def select_records(self, record_ids: list[int]) -> None:
        """Select the rows of ``record_ids`` (clearing any other selection)."""
        model = self._table.selectionModel()
        model.clearSelection()
        wanted = set(record_ids)
        flags = QItemSelectionModel.SelectionFlag.Select | QItemSelectionModel.SelectionFlag.Rows
        for row, rec in enumerate(self._catalog.records()):
            if rec.id in wanted:
                index = self._table.model().index(row, 0)
                model.select(index, flags)
                model.setCurrentIndex(index, QItemSelectionModel.SelectionFlag.NoUpdate)
        self._on_selection_changed()

    def status_text(self) -> str:
        return self._status.text()

    def _refresh(self, *_: object) -> None:
        self._catalog.set_project(self._vm.project, self._base_dir())
        selected = self._table.currentRow()
        records = self._catalog.records()
        self._table.setRowCount(len(records))
        for row, rec in enumerate(records):
            md = self._catalog.metadata_for(rec)
            cells = (
                rec.name or str(rec.id),
                f"{rec.dt:g}",
                str(rec.npts),
                f"{md.pga:.4g}" if md else "-",
                f"{md.d5_95:.3g}" if md else "-",
                rec.accel_units,
                rec.status,
            )
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if col > 0:
                    item.setTextAlignment(
                        Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                    )
                self._table.setItem(row, col, item)
        self._table.resizeColumnsToContents()
        if 0 <= selected < len(records) and not self._table.selectionModel().selectedRows():
            self._table.selectRow(selected)
        self._refresh_target_label()
        self._on_selection_changed()

    def _refresh_target_label(self) -> None:
        target = self._catalog.active_target()
        self._target_label.setText(
            "No target spectrum." if target is None else f"Active: {target.describe()}"
        )

    def _on_selection_changed(self, *_: object) -> None:
        rec = self.selected_record()
        self._relink_btn.setEnabled(rec is not None)
        self._remove_btn.setEnabled(rec is not None)
        self._units.setEnabled(rec is not None)
        self._syncing = True
        try:
            if rec is not None:
                self._units.setCurrentIndex(max(0, self._units.findData(rec.accel_units)))
        finally:
            self._syncing = False
        self._plot_record(rec)
        self._clear_preview()
        self._plot_spectra(self.selected_records())

    def _on_units_changed(self, *_: object) -> None:
        if self._syncing:
            return
        rec = self.selected_record()
        units = self._units.currentData()
        if rec is None or units is None or units == rec.accel_units:
            return
        self._vm.apply_command(SetGroundMotionUnitsCommand(self._vm, rec.id, units))
        self._status.setText(f"'{rec.name}' units set to {units}.")

    def set_selected_units(self, units: str) -> None:
        """Set the selected record's acceleration units (undoable)."""
        self._units.setCurrentIndex(max(0, self._units.findData(units)))

    # ---- spectra ---------------------------------------------------------------
    def _plot_spectra(self, records: list) -> None:  # type: ignore[type-arg]
        for curve in self._spectrum_curves:
            with contextlib.suppress(Exception):
                self._spectrum_plot.removeItem(curve)
        self._spectrum_curves = []
        if self._target_curve is not None:
            with contextlib.suppress(Exception):
                self._spectrum_plot.removeItem(self._target_curve)
            self._target_curve = None
        problems: list[str] = []
        for i, rec in enumerate(records):
            try:
                spectrum = self._catalog.spectrum_for(rec)
            except ValueError as exc:
                problems.append(str(exc))
                continue
            pen = pg.mkPen(_RECORD_PENS[i % len(_RECORD_PENS)], width=1.5)
            self._spectrum_curves.append(
                self._spectrum_plot.plot(spectrum.periods, spectrum.sa, pen=pen, name=rec.name)
            )
        target = self._catalog.active_target()
        if target is not None:
            self._target_curve = self._spectrum_plot.plot(
                PLOT_PERIODS,
                target.sa_at(PLOT_PERIODS),
                pen=pg.mkPen("#ffffff", width=2, style=Qt.PenStyle.DashLine),
                name="Target",
            )
        self._spectrum_plot.enableAutoRange()
        if problems:
            self._status.setText(" ".join(problems))

    def spectrum_curve_count(self) -> int:
        """Record curves plus the target overlay (the scaled mean is separate)."""
        return len(self._spectrum_curves) + (1 if self._target_curve is not None else 0)

    def spectrum_curve_data(self) -> list[tuple[Any, Any]]:
        return [c.getData() for c in self._spectrum_curves]

    def _plot_record(self, rec) -> None:  # type: ignore[no-untyped-def]
        if self._curve is not None:
            with contextlib.suppress(Exception):
                self._plot.removeItem(self._curve)
            self._curve = None
        if rec is None:
            return
        values = self._catalog.values_for(rec)
        if values is None:
            self._status.setText(
                f"'{rec.name}': cannot read {rec.source_path} (status: {rec.status})."
            )
            return
        times = [i * rec.dt for i in range(len(values))]
        self._curve = self._plot.plot(times, values, pen=pg.mkPen("#1f77b4", width=1))
        self._plot.enableAutoRange()

    def curve_data(self) -> tuple[Any, Any] | None:
        """The plotted (time, acceleration) arrays, or None when empty."""
        return self._curve.getData() if self._curve is not None else None

    # ---- actions ---------------------------------------------------------------
    def _on_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import ground-motion record", "", _FILE_FILTER)
        if not path:
            return
        self.import_file(path)

    def import_file(self, path: str) -> bool:
        """Import ``path`` with the current format override; True on success."""
        if self._vm.project is None:
            return False
        try:
            record = self._catalog.build_import(
                path,
                format=self._format.currentData(),
                dt=self._dt.value(),
            )
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Import failed", str(exc))
            self._status.setText(f"Import failed: {exc}")
            return False
        self._vm.apply_command(AddGroundMotionCommand(self._vm, record))
        self._status.setText(f"Imported '{record.name}' ({record.npts} points, dt {record.dt:g}).")
        self._select_record(record.id)
        return True

    def _on_relink(self) -> None:
        rec = self.selected_record()
        if rec is None:
            return
        path, _ = QFileDialog.getOpenFileName(self, f"Relink '{rec.name}'", "", _FILE_FILTER)
        if not path:
            return
        self.relink_selected(path)

    def relink_selected(self, path: str) -> bool:
        """Relink the selected record to ``path``; True on success."""
        rec = self.selected_record()
        if rec is None:
            return False
        try:
            relinked, values = self._catalog.build_relink(rec, path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Relink failed", str(exc))
            self._status.setText(f"Relink failed: {exc}")
            return False
        self._vm.apply_command(RelinkGroundMotionCommand(self._vm, relinked, values))
        self._status.setText(f"Relinked '{relinked.name}' to {relinked.source_path}.")
        self._select_record(relinked.id)
        return True

    def remove_selected(self) -> bool:
        """Remove the selected record; refused while a series uses it."""
        rec = self.selected_record()
        if rec is None:
            return False
        in_use = self._catalog.series_using(rec.id)
        if in_use:
            QMessageBox.warning(
                self,
                "Record in use",
                f"'{rec.name}' is used by time series {in_use}. "
                "Remove or relink those series first.",
            )
            return False
        self._vm.apply_command(RemoveGroundMotionCommand(self._vm, rec.id))
        self._status.setText(f"Removed '{rec.name}'.")
        return True

    def _on_remove(self) -> None:
        self.remove_selected()

    # ---- target spectrum -----------------------------------------------------
    def _on_set_target(self) -> None:
        self.set_target_tbdy(self._sds.value(), self._sd1.value())

    def set_target_tbdy(self, sds: float, sd1: float) -> bool:
        """Make a TBDY 2018 spectrum the project's target (undoable)."""
        try:
            spectrum = self._catalog.build_target_tbdy(sds, sd1)
        except ValueError as exc:
            QMessageBox.warning(self, "Target spectrum", str(exc))
            return False
        self._vm.apply_command(SetTargetSpectrumCommand(self._vm, spectrum))
        self._status.setText(f"Target set: {spectrum.describe()}.")
        return True

    def _on_import_table(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import target spectrum table", "", _TABLE_FILTER
        )
        if path:
            self.set_target_table(path)

    def set_target_table(self, path: str) -> bool:
        """Make a user period/Sa table the project's target (undoable)."""
        try:
            spectrum = self._catalog.build_target_user(path)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Target spectrum", str(exc))
            self._status.setText(f"Target table rejected: {exc}")
            return False
        self._vm.apply_command(SetTargetSpectrumCommand(self._vm, spectrum))
        self._status.setText(f"Target set: {spectrum.describe()}.")
        return True

    # ---- scaling -----------------------------------------------------------------
    def preview_scaling(self) -> ScalingPreview | None:
        """Compute factors for the selected records; None with the reason shown."""
        self._clear_preview()
        method: ScalingMethod = self._method.currentData()
        ids = [rec.id for rec in self.selected_records()]
        try:
            preview = self._catalog.preview_scaling(
                method,
                ids,
                target_pga=self._target_pga.value(),
                t1=self._t1.value(),
                a=self._range_a.value(),
                b=self._range_b.value(),
                alpha=self._alpha.value(),
                individual=self._individual.isChecked(),
                pair_consecutive=self._pairs.isChecked(),
            )
        except (KeyError, ValueError) as exc:
            self._status.setText(f"Scaling refused: {exc}")
            return None
        self._preview = preview
        names = {rec.id: rec.name for rec in self._catalog.records()}
        lines = [f"{names.get(rid, rid)}: k = {k:.4g}" for rid, k in preview.factors.items()]
        if preview.series_factors:
            lines.append(
                "Series factors: "
                + ", ".join(f"#{sid} = {f:.5g}" for sid, f in preview.series_factors.items())
            )
        if preview.unbacked:
            lines.append(
                "No time series is backed by record(s) "
                + ", ".join(names.get(rid, str(rid)) for rid in preview.unbacked)
                + "; nothing to write for them."
            )
        self._factors_label.setText("\n".join(lines))
        self._status.setText(preview.summary)
        if preview.periods is not None and preview.scaled_mean_sa is not None:
            self._scaled_curve = self._spectrum_plot.plot(
                preview.periods,
                preview.scaled_mean_sa,
                pen=pg.mkPen("#ffd700", width=2, style=Qt.PenStyle.DotLine),
                name="Scaled mean",
            )
        self._apply_btn.setEnabled(bool(preview.series_factors))
        return preview

    def apply_scaling(self) -> bool:
        """Write the previewed factors to the series through one undoable command."""
        preview = self._preview
        if preview is None:
            preview = self.preview_scaling()
        if preview is None or not preview.series_factors:
            return False
        self._vm.apply_command(
            SetSeriesFactorsCommand(
                self._vm, preview.series_factors, f"Scale ground motions ({preview.method})"
            )
        )
        self._status.setText(
            f"Applied factors to time series {sorted(preview.series_factors)}. {preview.summary}"
        )
        return True

    def _select_record(self, record_id: int) -> None:
        for row, rec in enumerate(self._catalog.records()):
            if rec.id == record_id:
                self._table.selectRow(row)
                return
