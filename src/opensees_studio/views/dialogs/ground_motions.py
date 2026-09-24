"""Ground Motions catalog dialog (Define menu, beside Material Tester).

Import acceleration records (format auto-detected, with an explicit
override and a dt field for bare value lists), inspect their metadata
(PGA, D5-95, status), preview the acceleration trace, remove unused
entries and relink a missing or changed file (hash re-checked).

Records enter the project as catalog references (relative path +
content hash) via undoable commands; sample values are never embedded
in ``.osmodel``.
"""

from __future__ import annotations

import contextlib
from typing import Any

import pyqtgraph as pg
from PySide6.QtCore import QLocale, Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
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
)
from opensees_studio.viewmodels import ProjectViewModel
from opensees_studio.viewmodels.ground_motion_catalog_vm import (
    FORMAT_CHOICES,
    GroundMotionCatalogViewModel,
)

_COLUMNS = ("Name", "dt [s]", "npts", "PGA", "D5-95 [s]", "Status")

_FILE_FILTER = "Ground-motion records (*.AT2 *.at2 *.acc *.txt *.dat);;All files (*)"


class GroundMotionsDialog(QDialog):
    """Catalog of the project's ground-motion records."""

    def __init__(self, vm: ProjectViewModel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Ground Motions")
        self.setModal(False)
        self.resize(980, 520)
        self._vm = vm
        self._catalog = GroundMotionCatalogViewModel(vm.project, self._base_dir())
        self._curve: Any | None = None
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
        self._table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.verticalHeader().setVisible(False)
        self._table.itemSelectionChanged.connect(self._on_selection_changed)
        body.addWidget(self._table, 1)

        pg.setConfigOptions(antialias=True)
        self._plot = pg.PlotWidget()
        self._plot.setBackground("#1e1e1e")
        self._plot.showGrid(x=True, y=True, alpha=0.3)
        self._plot.setLabel("bottom", "Time [s]")
        self._plot.setLabel("left", "Acceleration")
        body.addWidget(self._plot, 1)
        root.addLayout(body)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        root.addWidget(self._status)

        self._on_format_changed()

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

    def selected_record(self):  # type: ignore[no-untyped-def]
        row = self._table.currentRow()
        records = self._catalog.records()
        return records[row] if 0 <= row < len(records) else None

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
        if 0 <= selected < len(records):
            self._table.selectRow(selected)
        self._on_selection_changed()

    def _on_selection_changed(self, *_: object) -> None:
        rec = self.selected_record()
        self._relink_btn.setEnabled(rec is not None)
        self._remove_btn.setEnabled(rec is not None)
        self._plot_record(rec)

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

    def _select_record(self, record_id: int) -> None:
        for row, rec in enumerate(self._catalog.records()):
            if rec.id == record_id:
                self._table.selectRow(row)
                return
