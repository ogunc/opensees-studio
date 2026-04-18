"""Coordinate/Grid Systems dialog — SAP2000's Define menu equivalent.

Lists every :class:`CoordinateGridSystem` in the project and lets the
user Add New / Add Copy / Modify / Delete them. The ``Global`` system
is special: it always exists and cannot be renamed or deleted.

Modify / Add New opens the :class:`CoordSystemDataDialog` which
combines the Coord System Location and Orientation form with the
Define Grid System Data form on a single page — origin & Euler
rotation at the top, X/Y/Z grid spacings below.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core.geometry import (
    CoordinateGridSystem,
    CoordinateSystem,
    GridSystem,
)
from opensees_studio.views.dialogs.grid_system import (
    _coords_from_spacings,
    _parse_spacings,
)


def _spacings_text(coords: list[float]) -> str:
    """Reverse a coord list back into a readable spacings expression."""
    if len(coords) < 2:
        return ""
    spacings = [coords[i + 1] - coords[i] for i in range(len(coords) - 1)]
    return ", ".join(f"{s:g}" for s in spacings)


class CoordSystemDataDialog(QDialog):
    """Edit one CoordinateGridSystem (origin + orientation + grid)."""

    def __init__(
        self,
        existing: CoordinateGridSystem | None = None,
        is_global: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(
            "Edit Coordinate/Grid System"
            if existing is not None else "Add Coordinate/Grid System"
        )
        self._is_global = is_global
        self._existing = existing
        self._build_ui()
        if existing is not None:
            self._load_existing(existing)

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        # ── Name ─────────────────────────────────────────────────
        head = QFormLayout()
        self._name_edit = QLineEdit()
        self._name_edit.setText("CSYS1")
        if self._is_global:
            self._name_edit.setText("Global")
            self._name_edit.setEnabled(False)
            self._name_edit.setToolTip("Global system cannot be renamed.")
        head.addRow("Name:", self._name_edit)
        layout.addLayout(head)

        # ── Location & Orientation ───────────────────────────────
        loc_box = QGroupBox("Location and Orientation (relative to Global)")
        loc_form = QFormLayout(loc_box)

        self._ox = self._spin(); self._oy = self._spin(); self._oz = self._spin()
        origin_row = QHBoxLayout()
        for label, w in (("X", self._ox), ("Y", self._oy), ("Z", self._oz)):
            origin_row.addWidget(QLabel(f"{label}:"))
            origin_row.addWidget(w)
        origin_wrap = QWidget(); origin_wrap.setLayout(origin_row)
        loc_form.addRow("Origin:", origin_wrap)

        self._rx = self._rot_spin(); self._ry = self._rot_spin(); self._rz = self._rot_spin()
        rot_row = QHBoxLayout()
        for label, w in (("about X", self._rx), ("about Y", self._ry), ("about Z", self._rz)):
            rot_row.addWidget(QLabel(f"{label}:"))
            rot_row.addWidget(w)
        rot_wrap = QWidget(); rot_wrap.setLayout(rot_row)
        loc_form.addRow("Rotation (deg):", rot_wrap)

        if self._is_global:
            for w in (self._ox, self._oy, self._oz, self._rx, self._ry, self._rz):
                w.setEnabled(False)
            loc_box.setToolTip(
                "Global system is anchored at the world origin "
                "with identity orientation.",
            )

        layout.addWidget(loc_box)

        # ── Grid Data ────────────────────────────────────────────
        grid_box = QGroupBox("Grid Data (Cartesian spacings)")
        grid_form = QFormLayout(grid_box)

        info = QLabel(
            "Three accepted formats per axis:<br>"
            "&bull; <b>N</b> (integer) — N grid lines at unit spacing<br>"
            "&bull; <b>n@d</b> — n equal spacings of size d<br>"
            "&bull; <b>Comma-separated</b> — explicit spacings<br>"
            "Leave blank to skip that axis."
        )
        info.setWordWrap(True)
        grid_form.addRow(info)

        self._x_edit = QLineEdit("5")
        self._y_edit = QLineEdit("5")
        self._z_edit = QLineEdit("")
        grid_form.addRow("X spacings:", self._x_edit)
        grid_form.addRow("Y spacings:", self._y_edit)
        grid_form.addRow("Z spacings:", self._z_edit)

        self._visible_cb = QCheckBox("Visible in 3D view")
        self._visible_cb.setChecked(True)
        grid_form.addRow(self._visible_cb)

        self._general_cb = QCheckBox("Convert to General Grid")
        self._general_cb.setChecked(False)
        self._general_cb.setToolTip(
            "General grids are edited as absolute line positions, not spacings. "
            "The underlying data is the same; the flag is kept for SAP2000 parity."
        )
        grid_form.addRow(self._general_cb)

        self._preview = QLabel()
        self._preview.setWordWrap(True)
        grid_form.addRow(self._preview)

        layout.addWidget(grid_box)

        # Live preview.
        for w in (self._x_edit, self._y_edit, self._z_edit):
            w.textChanged.connect(self._update_preview)
        self._update_preview()

        # ── Buttons ──────────────────────────────────────────────
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ── helpers ──────────────────────────────────────────────────
    @staticmethod
    def _spin() -> QDoubleSpinBox:
        sb = QDoubleSpinBox()
        sb.setRange(-1e9, 1e9)
        sb.setDecimals(6)
        sb.setSingleStep(0.5)
        sb.setValue(0.0)
        return sb

    @staticmethod
    def _rot_spin() -> QDoubleSpinBox:
        sb = QDoubleSpinBox()
        sb.setRange(-360.0, 360.0)
        sb.setDecimals(3)
        sb.setSingleStep(1.0)
        sb.setValue(0.0)
        return sb

    def _load_existing(self, cs: CoordinateGridSystem) -> None:
        self._name_edit.setText(cs.name)
        ox, oy, oz = cs.coord.origin
        self._ox.setValue(ox); self._oy.setValue(oy); self._oz.setValue(oz)
        rx, ry, rz = cs.coord.rotation_deg
        self._rx.setValue(rx); self._ry.setValue(ry); self._rz.setValue(rz)
        self._x_edit.setText(_spacings_text(cs.grid.x_lines))
        self._y_edit.setText(_spacings_text(cs.grid.y_lines))
        self._z_edit.setText(_spacings_text(cs.grid.z_lines))
        self._visible_cb.setChecked(cs.grid.visible)
        self._general_cb.setChecked(cs.grid.is_general)

    def _update_preview(self) -> None:
        try:
            xs = _coords_from_spacings(_parse_spacings(self._x_edit.text()))
            ys = _coords_from_spacings(_parse_spacings(self._y_edit.text()))
            zs = _coords_from_spacings(_parse_spacings(self._z_edit.text()))
            self._preview.setText(
                f"Grid: <b>{len(xs)}</b> × <b>{len(ys)}</b> × <b>{len(zs)}</b> lines."
            )
        except (ValueError, IndexError) as exc:
            self._preview.setText(f"<span style='color:red'>Parse error: {exc}</span>")

    def _on_accept(self) -> None:
        name = self._name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Invalid name", "Name cannot be empty.")
            return
        self.accept()

    def system(self) -> CoordinateGridSystem:
        """Return the CoordinateGridSystem configured by the dialog."""
        return CoordinateGridSystem(
            name=self._name_edit.text().strip(),
            coord=CoordinateSystem(
                origin=(self._ox.value(), self._oy.value(), self._oz.value()),
                rotation_deg=(self._rx.value(), self._ry.value(), self._rz.value()),
            ),
            grid=GridSystem(
                x_lines=_coords_from_spacings(_parse_spacings(self._x_edit.text())),
                y_lines=_coords_from_spacings(_parse_spacings(self._y_edit.text())),
                z_lines=_coords_from_spacings(_parse_spacings(self._z_edit.text())),
                visible=self._visible_cb.isChecked(),
                is_general=self._general_cb.isChecked(),
            ),
        )


class CoordinateGridSystemsDialog(QDialog):
    """Main Coordinate/Grid Systems form (SAP2000 parity)."""

    def __init__(
        self,
        systems: list[CoordinateGridSystem],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Coordinate/Grid Systems")
        self.resize(600, 420)
        self._systems: list[CoordinateGridSystem] = [
            s.model_copy(deep=True) for s in systems
        ]
        self._build_ui()
        self._refresh_list()

    def result_systems(self) -> list[CoordinateGridSystem]:
        """Return the edited list (call after accept)."""
        return self._systems

    def _build_ui(self) -> None:
        root = QHBoxLayout(self)

        # Left: list + action buttons.
        left = QVBoxLayout()
        left.addWidget(QLabel("<b>Systems</b>"))
        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._on_selection_changed)
        self._list.itemDoubleClicked.connect(lambda _: self._on_modify())
        left.addWidget(self._list, 1)
        root.addLayout(left, 2)

        # Right: action buttons + general-toggle + close.
        right = QVBoxLayout()
        self._btn_add = QPushButton("Add New System…")
        self._btn_copy = QPushButton("Add Copy of System…")
        self._btn_modify = QPushButton("Modify/Show System…")
        self._btn_delete = QPushButton("Delete System")
        self._btn_add.clicked.connect(self._on_add)
        self._btn_copy.clicked.connect(self._on_copy)
        self._btn_modify.clicked.connect(self._on_modify)
        self._btn_delete.clicked.connect(self._on_delete)
        right.addWidget(self._btn_add)
        right.addWidget(self._btn_copy)
        right.addWidget(self._btn_modify)
        right.addWidget(self._btn_delete)
        right.addSpacing(10)

        self._cb_general = QCheckBox("Convert to General Grid")
        self._cb_general.toggled.connect(self._on_general_toggled)
        right.addWidget(self._cb_general)

        right.addStretch(1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        right.addWidget(buttons)

        root.addLayout(right, 1)

    def _refresh_list(self, select_name: str | None = None) -> None:
        self._list.blockSignals(True)
        self._list.clear()
        for cs in self._systems:
            tag = " (Global)" if cs.is_global() else ""
            item = QListWidgetItem(cs.name + tag)
            item.setData(Qt.ItemDataRole.UserRole, cs.name)
            self._list.addItem(item)
        # Restore selection.
        if select_name is not None:
            for i in range(self._list.count()):
                if self._list.item(i).data(Qt.ItemDataRole.UserRole) == select_name:
                    self._list.setCurrentRow(i)
                    break
        elif self._list.count():
            self._list.setCurrentRow(0)
        self._list.blockSignals(False)
        self._on_selection_changed(self._list.currentRow())

    def _current(self) -> CoordinateGridSystem | None:
        row = self._list.currentRow()
        if 0 <= row < len(self._systems):
            return self._systems[row]
        return None

    def _on_selection_changed(self, _row: int) -> None:
        cs = self._current()
        is_global = cs is not None and cs.is_global()
        self._btn_delete.setEnabled(cs is not None and not is_global)
        self._btn_copy.setEnabled(cs is not None)
        self._btn_modify.setEnabled(cs is not None)
        self._cb_general.blockSignals(True)
        self._cb_general.setChecked(cs.grid.is_general if cs is not None else False)
        self._cb_general.setEnabled(
            cs is not None and not cs.grid.is_general
        )
        self._cb_general.blockSignals(False)

    # ── actions ──────────────────────────────────────────────────
    def _unique_name(self, base: str) -> str:
        existing = {s.name for s in self._systems}
        if base not in existing:
            return base
        i = 1
        while f"{base}-{i}" in existing:
            i += 1
        return f"{base}-{i}"

    def _on_add(self) -> None:
        from opensees_studio.views.dialogs.define_grid_data import (
            DefineGridSystemDataDialog,
        )
        dlg = DefineGridSystemDataDialog(parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new_sys = dlg.system()
        if any(s.name == new_sys.name for s in self._systems):
            new_sys = new_sys.model_copy(update={
                "name": self._unique_name(new_sys.name),
            })
        self._systems.append(new_sys)
        self._refresh_list(select_name=new_sys.name)

    def _on_copy(self) -> None:
        src = self._current()
        if src is None:
            return
        copy_name = self._unique_name(f"{src.name}-1")
        clone = src.model_copy(deep=True, update={"name": copy_name})
        # Force-clear the Global flag (never duplicate a Global).
        self._systems.append(clone)
        self._refresh_list(select_name=clone.name)
        self._on_modify()

    def _on_modify(self) -> None:
        cs = self._current()
        if cs is None:
            return
        from opensees_studio.views.dialogs.define_grid_data import (
            DefineGridSystemDataDialog,
        )
        dlg = DefineGridSystemDataDialog(
            existing=cs, is_global=cs.is_global(), parent=self,
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        updated = dlg.system()
        # Preserve the original name for the Global system.
        if cs.is_global() and updated.name != "Global":
            updated = updated.model_copy(update={"name": "Global"})
        # Enforce unique names against siblings.
        others = [s for s in self._systems if s is not cs]
        if any(s.name == updated.name for s in others):
            updated = updated.model_copy(update={
                "name": self._unique_name(updated.name),
            })
        row = self._list.currentRow()
        self._systems[row] = updated
        self._refresh_list(select_name=updated.name)

    def _on_delete(self) -> None:
        cs = self._current()
        if cs is None or cs.is_global():
            return
        row = self._list.currentRow()
        del self._systems[row]
        self._refresh_list()

    def _on_general_toggled(self, checked: bool) -> None:
        cs = self._current()
        if cs is None:
            return
        if cs.grid.is_general and not checked:
            # SAP2000: once converted to General, can't convert back.
            QMessageBox.information(
                self, "Convert to General",
                "Once a system is converted to General, it cannot be "
                "converted back to a regular Cartesian system.",
            )
            self._cb_general.blockSignals(True)
            self._cb_general.setChecked(True)
            self._cb_general.blockSignals(False)
            return
        if checked:
            new_grid = cs.grid.model_copy(update={"is_general": True})
            row = self._list.currentRow()
            self._systems[row] = cs.model_copy(update={"grid": new_grid})
            self._on_selection_changed(row)
