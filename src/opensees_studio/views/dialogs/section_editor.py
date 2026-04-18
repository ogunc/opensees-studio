"""Fiber Section Editor — interactive cross-section builder.

Lets the user define a FiberSection visually by adding rectangular/circular
patches and straight rebar layers. A live preview canvas on the right shows
the expanded fibre grid with color-coded materials and computed section
properties (A, centroid, Iy, Iz).

The dialog returns a fully populated :class:`FiberSection` on accept.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSpinBox,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core.sections import (
    CircularPatch,
    FiberSection,
    RectangularPatch,
    StraightLayer,
)
from opensees_studio.services.section_properties import (
    compute_section_props,
    expand_fibres,
)

_PATCH_COLORS = [
    "#4e79a7", "#f28e2b", "#e15759", "#76b7b2",
    "#59a14f", "#edc948", "#b07aa1", "#ff9da7",
]


class FiberSectionEditor(QDialog):
    """Modal dialog: build a FiberSection from patches + layers."""

    def __init__(self, material_ids: list[int],
                 existing: FiberSection | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Fiber Section Editor")
        self.resize(1000, 650)
        self._material_ids = material_ids
        self._patches: list[Any] = []      # RectangularPatch | CircularPatch
        self._layers: list[StraightLayer] = []
        self._section_id: int = existing.id if existing else 1
        self._section_name: str = existing.name if existing else ""
        self._gj: float | None = existing.GJ if existing else None
        self._build_ui()
        if existing is not None:
            self._load_existing(existing)
        self._refresh_preview()

    def result_section(self) -> FiberSection:
        """Return the constructed FiberSection (call after accept)."""
        return FiberSection(
            id=self._section_id,
            name=self._section_name,
            GJ=self._gj,
            patches=list(self._patches),
            layers=list(self._layers),
        )

    # ── UI ──────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter)

        # ── Left panel: controls ──
        left = QWidget()
        left_layout = QVBoxLayout(left)

        # Add-patch controls
        patch_group = QGroupBox("Add Patch")
        pf = QFormLayout(patch_group)
        self._patch_type = QComboBox()
        self._patch_type.addItems(["Rectangular", "Circular"])
        self._patch_type.currentIndexChanged.connect(self._on_patch_type_changed)
        pf.addRow("Type:", self._patch_type)

        self._patch_mat = QComboBox()
        for mid in self._material_ids:
            self._patch_mat.addItem(f"Material {mid}", mid)
        if not self._material_ids:
            self._patch_mat.addItem("(none)", 1)
        pf.addRow("Material:", self._patch_mat)

        # Rect fields
        self._rect_yi = self._spin(-0.15); self._rect_zi = self._spin(-0.15)
        self._rect_yj = self._spin(0.15);  self._rect_zj = self._spin(0.15)
        self._rect_ny = self._ispin(8);    self._rect_nz = self._ispin(8)
        self._rect_rows = [
            ("y_i:", self._rect_yi), ("z_i:", self._rect_zi),
            ("y_j:", self._rect_yj), ("z_j:", self._rect_zj),
            ("n_fib_y:", self._rect_ny), ("n_fib_z:", self._rect_nz),
        ]
        for label, widget in self._rect_rows:
            pf.addRow(label, widget)

        # Circ fields (initially hidden)
        self._circ_yc = self._spin(0.0); self._circ_zc = self._spin(0.0)
        self._circ_ri = self._spin(0.0); self._circ_ro = self._spin(0.15)
        self._circ_nc = self._ispin(16); self._circ_nr = self._ispin(4)
        self._circ_rows = [
            ("y_center:", self._circ_yc), ("z_center:", self._circ_zc),
            ("r_inner:", self._circ_ri), ("r_outer:", self._circ_ro),
            ("n_circ:", self._circ_nc), ("n_rad:", self._circ_nr),
        ]
        for label, widget in self._circ_rows:
            pf.addRow(label, widget)

        self._add_patch_btn = QPushButton("Add patch")
        self._add_patch_btn.clicked.connect(self._on_add_patch)
        pf.addRow(self._add_patch_btn)
        left_layout.addWidget(patch_group)

        # Add-layer controls
        layer_group = QGroupBox("Add Rebar Layer")
        lf = QFormLayout(layer_group)
        self._layer_mat = QComboBox()
        for mid in self._material_ids:
            self._layer_mat.addItem(f"Material {mid}", mid)
        if not self._material_ids:
            self._layer_mat.addItem("(none)", 1)
        lf.addRow("Material:", self._layer_mat)
        self._layer_nbars = self._ispin(4)
        self._layer_area = self._spin(0.0005, step=0.0001, minimum=1e-12)
        self._layer_ys = self._spin(-0.12); self._layer_zs = self._spin(-0.12)
        self._layer_ye = self._spin(0.12);  self._layer_ze = self._spin(-0.12)
        lf.addRow("n_bars:", self._layer_nbars)
        lf.addRow("bar_area:", self._layer_area)
        lf.addRow("y_start:", self._layer_ys); lf.addRow("z_start:", self._layer_zs)
        lf.addRow("y_end:", self._layer_ye); lf.addRow("z_end:", self._layer_ze)
        self._add_layer_btn = QPushButton("Add layer")
        self._add_layer_btn.clicked.connect(self._on_add_layer)
        lf.addRow(self._add_layer_btn)
        left_layout.addWidget(layer_group)

        # Item list + remove
        self._item_list = QListWidget()
        left_layout.addWidget(QLabel("Components:"))
        left_layout.addWidget(self._item_list)
        self._remove_btn = QPushButton("Remove selected")
        self._remove_btn.clicked.connect(self._on_remove)
        left_layout.addWidget(self._remove_btn)

        # Buttons
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        left_layout.addWidget(buttons)

        splitter.addWidget(left)

        # ── Right panel: preview ──
        right = QWidget()
        right_layout = QVBoxLayout(right)
        pg.setConfigOptions(antialias=True)
        self._preview = pg.PlotWidget()
        self._preview.setBackground("#1e1e1e")
        self._preview.setAspectLocked(True)
        self._preview.setLabel("bottom", "y (m)")
        self._preview.setLabel("left", "z (m)")
        self._preview.showGrid(x=True, y=True, alpha=0.3)
        right_layout.addWidget(self._preview, 1)

        self._props_label = QLabel("")
        self._props_label.setStyleSheet("color: #aaa; font-family: monospace;")
        right_layout.addWidget(self._props_label)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        self._on_patch_type_changed(0)

    # ── helpers ─────────────────────────────────────────────────────
    @staticmethod
    def _spin(default: float = 0.0, *, step: float = 0.01,
              minimum: float = -1e6) -> QDoubleSpinBox:
        sb = QDoubleSpinBox()
        sb.setRange(minimum, 1e6)
        sb.setDecimals(6)
        sb.setSingleStep(step)
        sb.setValue(default)
        return sb

    @staticmethod
    def _ispin(default: int = 4) -> QSpinBox:
        sb = QSpinBox()
        sb.setRange(1, 200)
        sb.setValue(default)
        return sb

    def _on_patch_type_changed(self, idx: int) -> None:
        is_rect = (idx == 0)
        for _, w in self._rect_rows:
            w.setVisible(is_rect)
        for _, w in self._circ_rows:
            w.setVisible(not is_rect)

    # ── add / remove ────────────────────────────────────────────────
    def _on_add_patch(self) -> None:
        mid = self._patch_mat.currentData() or 1
        if self._patch_type.currentIndex() == 0:
            p = RectangularPatch(
                material_id=mid,
                n_fib_y=self._rect_ny.value(), n_fib_z=self._rect_nz.value(),
                y_i=self._rect_yi.value(), z_i=self._rect_zi.value(),
                y_j=self._rect_yj.value(), z_j=self._rect_zj.value(),
            )
            self._patches.append(p)
            self._item_list.addItem(QListWidgetItem(
                f"Rect patch  mat={mid}  "
                f"({p.y_i:.3f},{p.z_i:.3f})→({p.y_j:.3f},{p.z_j:.3f})  "
                f"{p.n_fib_y}×{p.n_fib_z}",
            ))
        else:
            p = CircularPatch(
                material_id=mid,
                n_fib_circ=self._circ_nc.value(), n_fib_rad=self._circ_nr.value(),
                y_center=self._circ_yc.value(), z_center=self._circ_zc.value(),
                r_inner=self._circ_ri.value(), r_outer=self._circ_ro.value(),
            )
            self._patches.append(p)
            self._item_list.addItem(QListWidgetItem(
                f"Circ patch  mat={mid}  "
                f"r={p.r_inner:.3f}→{p.r_outer:.3f}  {p.n_fib_circ}×{p.n_fib_rad}",
            ))
        self._refresh_preview()

    def _on_add_layer(self) -> None:
        mid = self._layer_mat.currentData() or 1
        lay = StraightLayer(
            material_id=mid,
            n_bars=self._layer_nbars.value(),
            bar_area=self._layer_area.value(),
            y_start=self._layer_ys.value(), z_start=self._layer_zs.value(),
            y_end=self._layer_ye.value(), z_end=self._layer_ze.value(),
        )
        self._layers.append(lay)
        self._item_list.addItem(QListWidgetItem(
            f"Layer  mat={mid}  {lay.n_bars} bars  A={lay.bar_area:.4g}",
        ))
        self._refresh_preview()

    def _on_remove(self) -> None:
        row = self._item_list.currentRow()
        if row < 0:
            return
        n_patches = len(self._patches)
        if row < n_patches:
            del self._patches[row]
        else:
            del self._layers[row - n_patches]
        self._item_list.takeItem(row)
        self._refresh_preview()

    # ── preview ─────────────────────────────────────────────────────
    def _refresh_preview(self) -> None:
        self._preview.clear()
        sec = FiberSection(id=999999, patches=list(self._patches),
                           layers=list(self._layers))
        props = compute_section_props(sec)
        if props.n_fibres == 0:
            self._props_label.setText("Add patches or layers to see the preview.")
            return

        f = props.fibre_yz
        # Color by material: assign a palette index per unique material_id.
        mat_ids = []
        for p in self._patches:
            mat_ids.append(p.material_id)
        for lay in self._layers:
            mat_ids.append(lay.material_id)
        unique_mats = sorted(set(mat_ids)) if mat_ids else [1]
        mat_to_color = {mid: _PATCH_COLORS[i % len(_PATCH_COLORS)]
                        for i, mid in enumerate(unique_mats)}

        # Draw patch fibres as squares, layer fibres as circles.
        # Expand per-patch for color assignment.
        for p in self._patches:
            sub_sec = FiberSection(id=999999, patches=[p])
            sub = expand_fibres(sub_sec)
            if sub.size == 0:
                continue
            color = mat_to_color.get(p.material_id, "#888888")
            self._preview.plot(
                sub[:, 0], sub[:, 1],
                pen=None, symbol="s", symbolSize=6,
                symbolBrush=color, symbolPen=None,
            )
        for lay in self._layers:
            sub_sec = FiberSection(id=999999, layers=[lay])
            sub = expand_fibres(sub_sec)
            if sub.size == 0:
                continue
            color = mat_to_color.get(lay.material_id, "#ff0000")
            self._preview.plot(
                sub[:, 0], sub[:, 1],
                pen=None, symbol="o", symbolSize=8,
                symbolBrush=color, symbolPen=pg.mkPen("#ffffff", width=1),
            )

        # Centroid marker
        self._preview.plot(
            [props.centroid_y], [props.centroid_z],
            pen=None, symbol="+", symbolSize=16,
            symbolBrush=None, symbolPen=pg.mkPen("#ff0000", width=2),
        )

        self._props_label.setText(
            f"Fibres: {props.n_fibres}   "
            f"A = {props.area:.4e} m²   "
            f"Centroid = ({props.centroid_y:.4e}, {props.centroid_z:.4e})   "
            f"Iy = {props.Iy:.4e} m⁴   Iz = {props.Iz:.4e} m⁴",
        )

    def _load_existing(self, sec: FiberSection) -> None:
        for p in sec.patches:
            self._patches.append(p)
            if isinstance(p, RectangularPatch):
                self._item_list.addItem(QListWidgetItem(
                    f"Rect patch mat={p.material_id} {p.n_fib_y}×{p.n_fib_z}",
                ))
            elif isinstance(p, CircularPatch):
                self._item_list.addItem(QListWidgetItem(
                    f"Circ patch mat={p.material_id} {p.n_fib_circ}×{p.n_fib_rad}",
                ))
        for lay in sec.layers:
            if isinstance(lay, StraightLayer):
                self._layers.append(lay)
                self._item_list.addItem(QListWidgetItem(
                    f"Layer mat={lay.material_id} {lay.n_bars} bars",
                ))
