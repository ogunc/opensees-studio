"""Define Grid System Data form — SAP2000 parity.

Editable spreadsheets (QTableWidget) for X, Y, and Z grid lines, each
row being one :class:`GridLine`. Columns match SAP2000:
    Grid ID | Ordinate/Spacing | Line Type | Visibility | Bubble Loc | Color

Top-level controls:
- Display Grid as: Ordinates | Spacing (radio)
- Hide All Grid Lines
- Glue to Grid Lines
- Bubble Size
- System Name + Coord Origin (summary; edit via 'Locate System Origin')
- Locate System Origin button → opens CoordSystemLocationOrientationDialog
- Quick Start button → QuickGridLinesDialog
- Reorder Ordinates button → re-sorts rows by ordinate
- Add Row / Delete Row toolbar buttons
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core.geometry import (
    CoordinateGridSystem,
    CoordinateSystem,
    GridLine,
    GridSystem,
)


_LINE_TYPE_CHOICES = ["Primary", "Secondary"]
_BUBBLE_LOC_CHOICES = ["Start", "End"]


class _AxisGridTable(QWidget):
    """A single X/Y/Z spreadsheet — one row per GridLine."""

    COLUMNS = ["Grid ID", "Ordinate", "Line Type", "Visibility", "Bubble Loc", "Color"]

    def __init__(self, axis: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.axis = axis
        self._show_spacing = False
        self._build_ui()

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)

        self._table = QTableWidget(0, len(self.COLUMNS))
        self._table.setHorizontalHeaderLabels(self.COLUMNS)
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Interactive,
        )
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.verticalHeader().setDefaultSectionSize(22)
        self._table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows,
        )
        self._table.setAlternatingRowColors(True)
        self._table.cellDoubleClicked.connect(self._on_cell_double_clicked)
        root.addWidget(self._table, 1)

        btn_row = QHBoxLayout()
        self._btn_add = QPushButton("Add Row")
        self._btn_del = QPushButton("Delete Row")
        self._btn_sort = QPushButton("Reorder by Ordinate")
        self._btn_add.clicked.connect(self._on_add_row)
        self._btn_del.clicked.connect(self._on_delete_row)
        self._btn_sort.clicked.connect(self._on_reorder)
        btn_row.addWidget(self._btn_add)
        btn_row.addWidget(self._btn_del)
        btn_row.addWidget(self._btn_sort)
        btn_row.addStretch(1)
        root.addLayout(btn_row)

    # ── data i/o ──────────────────────────────────────────────────
    def load_lines(self, lines: list[GridLine]) -> None:
        self._table.setRowCount(0)
        for ln in lines:
            self._append_row(ln)

    def set_display_spacing(self, as_spacing: bool) -> None:
        """Switch the Ordinate column between absolute coords and spacings."""
        if as_spacing == self._show_spacing:
            return
        # Read the current ordinates, then rewrite as spacings (or back).
        ords = self._collect_ordinates()
        self._show_spacing = as_spacing
        header = self.COLUMNS.copy()
        header[1] = "Spacing" if as_spacing else "Ordinate"
        self._table.setHorizontalHeaderLabels(header)
        for row, v in enumerate(self._iter_display_values(ords)):
            item = self._table.item(row, 1)
            if item is not None:
                item.setText(f"{v:g}")

    def _iter_display_values(self, ords: list[float]) -> list[float]:
        if not self._show_spacing:
            return list(ords)
        out: list[float] = []
        prev = 0.0
        for i, v in enumerate(ords):
            if i == 0:
                out.append(v)           # first row: absolute position
            else:
                out.append(v - prev)    # subsequent rows: spacing from previous
            prev = v
        return out

    def _collect_ordinates(self) -> list[float]:
        """Read the current Ordinate column, interpreting as absolute coords.

        If the table is in Spacing mode, the first row is the absolute
        starting coordinate and the rest accumulate.
        """
        raw: list[float] = []
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 1)
            try:
                raw.append(float(item.text()) if item is not None else 0.0)
            except ValueError:
                raw.append(0.0)
        if not self._show_spacing:
            return raw
        # Spacing mode: accumulate
        ords: list[float] = []
        acc = 0.0
        for i, v in enumerate(raw):
            if i == 0:
                acc = v
            else:
                acc += v
            ords.append(acc)
        return ords

    def collect_lines(self) -> list[GridLine]:
        """Read the table into a list of GridLine records."""
        ords = self._collect_ordinates()
        out: list[GridLine] = []
        for row in range(self._table.rowCount()):
            id_item = self._table.item(row, 0)
            line_type_widget = self._table.cellWidget(row, 2)
            visible_widget = self._table.cellWidget(row, 3)
            bubble_widget = self._table.cellWidget(row, 4)
            color_item = self._table.item(row, 5)
            out.append(GridLine(
                id=(id_item.text().strip() if id_item else f"{self.axis}{row + 1}"),
                ordinate=ords[row] if row < len(ords) else 0.0,
                line_type=(
                    line_type_widget.currentText()  # type: ignore[union-attr]
                    if isinstance(line_type_widget, QComboBox) else "Primary"
                ),
                visible=(
                    visible_widget.isChecked()      # type: ignore[union-attr]
                    if isinstance(visible_widget, QCheckBox) else True
                ),
                bubble_loc=(
                    bubble_widget.currentText()     # type: ignore[union-attr]
                    if isinstance(bubble_widget, QComboBox) else "End"
                ),
                color=(color_item.text() if color_item else "#808080"),
            ))
        return out

    # ── row ops ───────────────────────────────────────────────────
    def _append_row(self, ln: GridLine) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)

        # Grid ID (editable text)
        self._table.setItem(row, 0, QTableWidgetItem(ln.id))

        # Ordinate/Spacing (editable text)
        # On load we start in Ordinate mode.
        display_val = ln.ordinate
        if self._show_spacing and row > 0:
            # compute spacing from previous stored ordinate
            prev_item = self._table.item(row - 1, 1)
            try:
                display_val = ln.ordinate - float(prev_item.text()) if prev_item else ln.ordinate
            except ValueError:
                display_val = ln.ordinate
        self._table.setItem(row, 1, QTableWidgetItem(f"{display_val:g}"))

        # Line Type combo
        cb = QComboBox()
        cb.addItems(_LINE_TYPE_CHOICES)
        cb.setCurrentText(ln.line_type)
        self._table.setCellWidget(row, 2, cb)

        # Visibility checkbox (wrapped in a widget to centre)
        vis = QCheckBox()
        vis.setChecked(ln.visible)
        vis_wrap = QWidget()
        lay = QHBoxLayout(vis_wrap); lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(vis)
        lay.setAlignment(Qt.AlignmentFlag.AlignCenter)
        # We keep the QCheckBox directly; the wrap is optional visual
        self._table.setCellWidget(row, 3, vis)

        # Bubble Loc combo
        bubble = QComboBox()
        bubble.addItems(_BUBBLE_LOC_CHOICES)
        bubble.setCurrentText(ln.bubble_loc)
        self._table.setCellWidget(row, 4, bubble)

        # Color — hex string + swatch background
        color_item = QTableWidgetItem(ln.color)
        color_item.setBackground(QColor(ln.color))
        color_item.setFlags(color_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._table.setItem(row, 5, color_item)

    def _on_add_row(self) -> None:
        new_id = f"{self.axis}{self._table.rowCount() + 1}"
        self._append_row(GridLine(id=new_id, ordinate=0.0))

    def _on_delete_row(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            return
        self._table.removeRow(row)

    def _on_reorder(self) -> None:
        lines = self.collect_lines()
        lines.sort(key=lambda ln: ln.ordinate)
        self._table.setRowCount(0)
        self._show_spacing = False   # reset to ordinate view after sort
        self._table.setHorizontalHeaderLabels(self.COLUMNS)
        for ln in lines:
            self._append_row(ln)

    def _on_cell_double_clicked(self, row: int, col: int) -> None:
        if col == 5:   # Color picker
            item = self._table.item(row, col)
            current = QColor(item.text() if item else "#808080")
            new = QColorDialog.getColor(current, self, "Grid Line Color")
            if new.isValid():
                hex_str = new.name().upper()
                if item is not None:
                    item.setText(hex_str)
                    item.setBackground(new)


class DefineGridSystemDataDialog(QDialog):
    """SAP2000-parity Define Grid System Data form."""

    def __init__(
        self,
        existing: CoordinateGridSystem | None = None,
        is_global: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(
            "Define Grid System Data" if existing is not None
            else "Add Grid System"
        )
        self.resize(780, 620)
        self._is_global = is_global
        # Working copy: keep origin/rotation for round-tripping without
        # re-opening the Coord System Location form.
        self._origin: tuple[float, float, float] = (
            existing.coord.origin if existing else (0.0, 0.0, 0.0)
        )
        self._rotation_deg: tuple[float, float, float] = (
            existing.coord.rotation_deg if existing else (0.0, 0.0, 0.0)
        )
        self._build_ui()
        if existing is not None:
            self._load_existing(existing)
        elif not self._is_global:
            self._name_edit.setText("CSYS1")

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        # ── Header: name + display-mode + system-origin button ──
        head = QHBoxLayout()
        name_form = QFormLayout()
        self._name_edit = QLineEdit()
        if self._is_global:
            self._name_edit.setText("Global")
            self._name_edit.setEnabled(False)
        name_form.addRow("System Name:", self._name_edit)
        head.addLayout(name_form)

        head.addSpacing(15)

        display_box = QGroupBox("Display Grid as")
        db_row = QHBoxLayout(display_box)
        self._rb_ordinates = QRadioButton("Ordinates")
        self._rb_spacing = QRadioButton("Spacing")
        self._rb_ordinates.setChecked(True)
        self._rb_ordinates.toggled.connect(self._on_display_mode_changed)
        db_row.addWidget(self._rb_ordinates)
        db_row.addWidget(self._rb_spacing)
        head.addWidget(display_box)

        head.addStretch(1)

        self._btn_locate = QPushButton("Locate System Origin…")
        self._btn_locate.clicked.connect(self._on_locate_origin)
        if self._is_global:
            self._btn_locate.setEnabled(False)
            self._btn_locate.setToolTip(
                "Global system is anchored at the world origin."
            )
        head.addWidget(self._btn_locate)
        root.addLayout(head)

        # Origin summary line (updates when user edits via Locate form).
        self._origin_label = QLabel()
        self._origin_label.setStyleSheet("color: #666;")
        self._update_origin_label()
        root.addWidget(self._origin_label)

        # ── Tabs: X / Y / Z grid data spreadsheets ──
        self._tabs = QTabWidget()
        self._tab_x = _AxisGridTable("X")
        self._tab_y = _AxisGridTable("Y")
        self._tab_z = _AxisGridTable("Z")
        self._tabs.addTab(self._tab_x, "X Grid Data")
        self._tabs.addTab(self._tab_y, "Y Grid Data")
        self._tabs.addTab(self._tab_z, "Z Grid Data")
        root.addWidget(self._tabs, 1)

        # ── Footer: options + Quick Start + OK/Cancel ──
        opt_box = QGroupBox("Grid Options")
        opt_form = QFormLayout(opt_box)
        self._cb_hide_all = QCheckBox("Hide All Grid Lines")
        self._cb_glue = QCheckBox("Glue to Grid Lines")
        self._cb_general = QCheckBox("Convert to General Grid")
        self._cb_general.setToolTip(
            "General grids are edited as absolute line positions. Once "
            "converted, a system cannot be changed back to Cartesian."
        )
        self._bubble_size = QSpinBox()
        self._bubble_size.setRange(4, 200)
        self._bubble_size.setValue(20)
        opt_form.addRow(self._cb_hide_all)
        opt_form.addRow(self._cb_glue)
        opt_form.addRow(self._cb_general)
        opt_form.addRow("Bubble Size (px):", self._bubble_size)
        root.addWidget(opt_box)

        bottom = QHBoxLayout()
        self._btn_quick = QPushButton("Quick Start…")
        self._btn_quick.clicked.connect(self._on_quick_start)
        bottom.addWidget(self._btn_quick)
        bottom.addStretch(1)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        bottom.addWidget(buttons)
        root.addLayout(bottom)

    # ── helpers ──────────────────────────────────────────────────
    def _update_origin_label(self) -> None:
        ox, oy, oz = self._origin
        rx, ry, rz = self._rotation_deg
        self._origin_label.setText(
            f"Origin: ({ox:g}, {oy:g}, {oz:g})   "
            f"Rotation: ({rx:g}°, {ry:g}°, {rz:g}°)"
        )

    def _load_existing(self, cs: CoordinateGridSystem) -> None:
        self._name_edit.setText(cs.name)
        self._tab_x.load_lines(list(cs.grid.x_grid_lines))
        self._tab_y.load_lines(list(cs.grid.y_grid_lines))
        self._tab_z.load_lines(list(cs.grid.z_grid_lines))
        self._cb_hide_all.setChecked(cs.grid.hide_all)
        self._cb_glue.setChecked(cs.grid.glue_to_grid)
        self._cb_general.setChecked(cs.grid.is_general)
        self._bubble_size.setValue(cs.grid.bubble_size)
        self._origin = cs.coord.origin
        self._rotation_deg = cs.coord.rotation_deg
        self._update_origin_label()

    def _on_display_mode_changed(self, ordinates_checked: bool) -> None:
        as_spacing = not ordinates_checked
        self._tab_x.set_display_spacing(as_spacing)
        self._tab_y.set_display_spacing(as_spacing)
        self._tab_z.set_display_spacing(as_spacing)

    def _on_locate_origin(self) -> None:
        from opensees_studio.views.dialogs.locate_origin import (
            CoordSystemLocationOrientationDialog,
        )
        dlg = CoordSystemLocationOrientationDialog(
            origin=self._origin,
            rotation_deg=self._rotation_deg,
            parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self._origin, self._rotation_deg = dlg.location()
        self._update_origin_label()

    def _on_quick_start(self) -> None:
        from opensees_studio.views.dialogs.quick_grid_lines import (
            QuickGridLinesDialog,
        )
        dlg = QuickGridLinesDialog(parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        xs, ys, zs = dlg.ordinates()
        from opensees_studio.core.geometry import make_grid_lines
        # Revert to ordinate display mode before replacing rows.
        self._rb_ordinates.setChecked(True)
        self._tab_x.load_lines(make_grid_lines("X", xs))
        self._tab_y.load_lines(make_grid_lines("Y", ys))
        self._tab_z.load_lines(make_grid_lines("Z", zs))

    def _on_accept(self) -> None:
        name = self._name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Invalid name", "Name cannot be empty.")
            return
        # If we're in spacing mode, collect into ordinates before saving
        # (each tab handles that internally via collect_lines).
        self.accept()

    # ── result ──────────────────────────────────────────────────
    def system(self) -> CoordinateGridSystem:
        """Return the edited CoordinateGridSystem (call after accept)."""
        grid = GridSystem(
            x_grid_lines=self._tab_x.collect_lines(),
            y_grid_lines=self._tab_y.collect_lines(),
            z_grid_lines=self._tab_z.collect_lines(),
            visible=True,
            is_general=self._cb_general.isChecked(),
            hide_all=self._cb_hide_all.isChecked(),
            glue_to_grid=self._cb_glue.isChecked(),
            bubble_size=self._bubble_size.value(),
        )
        return CoordinateGridSystem(
            name=self._name_edit.text().strip(),
            coord=CoordinateSystem(
                origin=self._origin, rotation_deg=self._rotation_deg,
            ),
            grid=grid,
        )
