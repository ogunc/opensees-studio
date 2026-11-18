"""Fiber Section Editor — interactive cross-section builder.

Lets the user define a FiberSection visually by adding rectangular/circular
patches and straight rebar layers, or a template shape: "W-shape (wide
flange)" adds the three patches of OpenSees ``WFSection2d``. A live preview canvas on the right shows
the expanded fibre grid with color-coded materials and computed section
properties (A, centroid, Iy, Iz).

The dialog returns a fully populated :class:`FiberSection` on accept.
"""

from __future__ import annotations

from typing import Any

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialogButtonBox,
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
    rc_circular_fibres,
    rc_rectangular_fibres,
    w_shape_patches,
)
from opensees_studio.services.section_properties import (
    compute_section_props,
    expand_fibres,
)
from opensees_studio.views.float_field import FloatField
from opensees_studio.views.plot_style import axis_label, readable_plot
from opensees_studio.views.screen_fit import FittedDialog, scroll_area

_PATCH_COLORS = [
    "#4e79a7",
    "#f28e2b",
    "#e15759",
    "#76b7b2",
    "#59a14f",
    "#edc948",
    "#b07aa1",
    "#ff9da7",
]


class FiberSectionEditor(FittedDialog):
    """Modal dialog: build a FiberSection from patches + layers."""

    def __init__(
        self,
        material_ids: list[int],
        existing: FiberSection | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Fiber Section Editor")
        self.resize(1000, 650)
        self._material_ids = material_ids
        self._patches: list[Any] = []  # RectangularPatch | CircularPatch
        self._layers: list[StraightLayer] = []
        self._section_id: int = existing.id if existing else 1
        self._section_name: str = existing.name if existing else ""
        self._gj: float | None = existing.GJ if existing else None
        # Loose fibres are not editable here; they are kept as they were.
        self._fibres = list(existing.fibres) if existing else []
        self._unit_weight = FloatField()
        self._unit_weight.setRange(0.0, 1e12)
        self._unit_weight.setSingleStep(1e3)
        self._unit_weight.setValue(existing.unit_weight if existing else 0.0)
        self._unit_weight.setToolTip(
            "Weight per unit volume (force / length³). A load pattern with a self "
            "weight applies gamma times the gross area (patches + bars) per length."
        )
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
            fibres=list(self._fibres),
            unit_weight=self._unit_weight.value(),
        )

    # ── UI ──────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        root = QHBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter)

        # ── Left panel: controls ──
        left = QWidget()
        left_layout = QVBoxLayout(left)
        # The patch and layer forms scroll on a short screen; OK and Cancel stay put.
        controls = QWidget()
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(0, 0, 0, 0)

        weight_row = QFormLayout()
        weight_row.addRow("Unit weight γ:", self._unit_weight)
        controls_layout.addLayout(weight_row)
        controls_layout.addWidget(self._build_template_group())
        controls_layout.addWidget(self._build_rc_group())

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
        self._rect_yi = self._spin(-0.15)
        self._rect_zi = self._spin(-0.15)
        self._rect_yj = self._spin(0.15)
        self._rect_zj = self._spin(0.15)
        self._rect_ny = self._ispin(8)
        self._rect_nz = self._ispin(8)
        self._rect_rows = [
            ("y_i:", self._rect_yi),
            ("z_i:", self._rect_zi),
            ("y_j:", self._rect_yj),
            ("z_j:", self._rect_zj),
            ("n_fib_y:", self._rect_ny),
            ("n_fib_z:", self._rect_nz),
        ]
        for label, widget in self._rect_rows:
            pf.addRow(label, widget)

        # Circ fields (initially hidden)
        self._circ_yc = self._spin(0.0)
        self._circ_zc = self._spin(0.0)
        self._circ_ri = self._spin(0.0)
        self._circ_ro = self._spin(0.15)
        self._circ_nc = self._ispin(16)
        self._circ_nr = self._ispin(4)
        self._circ_rows = [
            ("y_center:", self._circ_yc),
            ("z_center:", self._circ_zc),
            ("r_inner:", self._circ_ri),
            ("r_outer:", self._circ_ro),
            ("n_circ:", self._circ_nc),
            ("n_rad:", self._circ_nr),
        ]
        for label, widget in self._circ_rows:
            pf.addRow(label, widget)

        self._add_patch_btn = QPushButton("Add patch")
        self._add_patch_btn.clicked.connect(self._on_add_patch)
        pf.addRow(self._add_patch_btn)
        controls_layout.addWidget(patch_group)

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
        self._layer_ys = self._spin(-0.12)
        self._layer_zs = self._spin(-0.12)
        self._layer_ye = self._spin(0.12)
        self._layer_ze = self._spin(-0.12)
        lf.addRow("n_bars:", self._layer_nbars)
        lf.addRow("bar_area:", self._layer_area)
        lf.addRow("y_start:", self._layer_ys)
        lf.addRow("z_start:", self._layer_zs)
        lf.addRow("y_end:", self._layer_ye)
        lf.addRow("z_end:", self._layer_ze)
        self._add_layer_btn = QPushButton("Add layer")
        self._add_layer_btn.clicked.connect(self._on_add_layer)
        lf.addRow(self._add_layer_btn)
        controls_layout.addWidget(layer_group)

        # Item list + remove
        self._item_list = QListWidget()
        self._item_list.setMinimumHeight(80)
        controls_layout.addWidget(QLabel("Components:"))
        controls_layout.addWidget(self._item_list)
        self._remove_btn = QPushButton("Remove selected")
        self._remove_btn.clicked.connect(self._on_remove)
        controls_layout.addWidget(self._remove_btn)
        left_layout.addWidget(scroll_area(controls, vertical_only=True), 1)

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
        self._preview = readable_plot()
        self._preview.setAspectLocked(True)
        self._preview.setLabel("bottom", axis_label("y", "m"))
        self._preview.setLabel("left", axis_label("z", "m"))
        right_layout.addWidget(self._preview, 1)

        self._props_label = QLabel("")
        self._props_label.setStyleSheet("color: #aaa; font-family: monospace;")
        right_layout.addWidget(self._props_label)
        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)

        self._on_patch_type_changed(0)

    def _build_template_group(self) -> QGroupBox:
        """Template shapes; "W-shape (wide flange)" is the one offered."""
        group = QGroupBox("Add Template")
        form = QFormLayout(group)
        self._template = QComboBox()
        self._template.addItem("W-shape (wide flange)", "w_shape")
        form.addRow("Template:", self._template)
        self._w_mat = QComboBox()
        for mid in self._material_ids:
            self._w_mat.addItem(f"Material {mid}", mid)
        if not self._material_ids:
            self._w_mat.addItem("(none)", 1)
        form.addRow("Material:", self._w_mat)
        self._w_d = self._spin(0.3, minimum=1e-12)
        self._w_bf = self._spin(0.15, minimum=1e-12)
        self._w_tf = self._spin(0.012, step=0.001, minimum=1e-12)
        self._w_tw = self._spin(0.008, step=0.001, minimum=1e-12)
        self._w_nfw = self._ispin(15)
        self._w_nff = self._ispin(4)
        self._w_nfw.setToolTip("Fibres along the clear web depth d - 2 tf (WFSection2d Nfw).")
        self._w_nff.setToolTip("Fibres through each flange thickness (WFSection2d Nff).")
        for label, widget in (
            ("d (depth, along y):", self._w_d),
            ("bf (flange width):", self._w_bf),
            ("tf (flange thickness):", self._w_tf),
            ("tw (web thickness):", self._w_tw),
            ("Fibres across web depth:", self._w_nfw),
            ("Fibres through flange:", self._w_nff),
        ):
            form.addRow(label, widget)
        self._template_error = QLabel("")
        self._template_error.setWordWrap(True)
        self._template_error.setStyleSheet("color: #c0392b;")
        form.addRow(self._template_error)
        self._add_template_btn = QPushButton("Add W-shape")
        self._add_template_btn.clicked.connect(self._on_add_template)
        form.addRow(self._add_template_btn)
        return group

    def _on_add_template(self) -> None:
        """Add the flange, web and flange patches of the W-shape."""
        mid = self._w_mat.currentData() or 1
        try:
            patches = w_shape_patches(
                mid,
                d=self._w_d.value(),
                bf=self._w_bf.value(),
                tf=self._w_tf.value(),
                tw=self._w_tw.value(),
                n_web=self._w_nfw.value(),
                n_flange=self._w_nff.value(),
            )
        except ValueError as exc:
            self._template_error.setText(str(exc))
            return
        self._template_error.setText("")
        # Patches come first in the component list; layers follow them.
        at = len(self._patches)
        for offset, (part, patch) in enumerate(
            zip(("top flange", "web", "bottom flange"), patches, strict=True)
        ):
            self._patches.append(patch)
            self._item_list.insertItem(
                at + offset,
                QListWidgetItem(
                    f"W-shape {part}  mat={mid}  y {patch.y_i:.4g}→{patch.y_j:.4g}  "
                    f"{patch.n_fib_y}×{patch.n_fib_z}"
                ),
            )
        self._refresh_preview()

    # ── RC templates ────────────────────────────────────────────────
    def _material_picker(self) -> QComboBox:
        combo = QComboBox()
        for mid in self._material_ids:
            combo.addItem(f"Material {mid}", mid)
        if not self._material_ids:
            combo.addItem("(none)", 1)
        return combo

    def _build_rc_group(self) -> QGroupBox:
        """Reinforced concrete templates: a rectangle or a circle with cover, core and bars."""
        group = QGroupBox("Add RC Template")
        form = QFormLayout(group)
        self._rc_kind = QComboBox()
        self._rc_kind.addItem("Rectangular", "rect")
        self._rc_kind.addItem("Circular", "circ")
        form.addRow("Shape:", self._rc_kind)
        self._rc_core = self._material_picker()
        self._rc_cover = self._material_picker()
        self._rc_steel = self._material_picker()
        form.addRow("Core concrete:", self._rc_core)
        form.addRow("Cover concrete:", self._rc_cover)
        form.addRow("Steel:", self._rc_steel)
        self._rc_h = self._spin(0.5, minimum=1e-12)
        self._rc_b = self._spin(0.3, minimum=1e-12)
        self._rc_cover_depth = self._spin(0.05, step=0.005, minimum=1e-12)
        self._rc_bar_area = self._spin(2.85e-4, step=1e-5, minimum=1e-12)
        self._rc_top = self._ispin(3)
        self._rc_bottom = self._ispin(3)
        self._rc_side = self._ispin(1)
        self._rc_side.setMinimum(0)
        self._rc_bars = self._ispin(8)
        for label, widget in (
            ("h (y) / diameter:", self._rc_h),
            ("b (z):", self._rc_b),
            ("Cover (to bars):", self._rc_cover_depth),
            ("Bar area:", self._rc_bar_area),
            ("Top bars:", self._rc_top),
            ("Bottom bars:", self._rc_bottom),
            ("Side bars (each):", self._rc_side),
            ("Bars (circular):", self._rc_bars),
        ):
            form.addRow(label, widget)
        self._rc_error = QLabel("")
        self._rc_error.setWordWrap(True)
        self._rc_error.setStyleSheet("color: #c0392b;")
        form.addRow(self._rc_error)
        button = QPushButton("Add RC section")
        button.clicked.connect(self._on_add_rc)
        form.addRow(button)
        return group

    def _on_add_rc(self) -> None:
        """Add the core, cover and bars of the chosen RC template."""
        materials = {
            "core_material_id": self._rc_core.currentData() or 1,
            "cover_material_id": self._rc_cover.currentData() or 1,
            "steel_material_id": self._rc_steel.currentData() or 1,
        }
        try:
            if self._rc_kind.currentData() == "rect":
                patches, layers = rc_rectangular_fibres(
                    **materials,
                    h=self._rc_h.value(),
                    b=self._rc_b.value(),
                    cover=self._rc_cover_depth.value(),
                    n_top=self._rc_top.value(),
                    n_bottom=self._rc_bottom.value(),
                    n_side=self._rc_side.value(),
                    bar_area=self._rc_bar_area.value(),
                )
            else:
                patches, layers = rc_circular_fibres(  # type: ignore[assignment]
                    **materials,
                    diameter=self._rc_h.value(),
                    cover=self._rc_cover_depth.value(),
                    n_bars=self._rc_bars.value(),
                    bar_area=self._rc_bar_area.value(),
                )
        except ValueError as exc:
            self._rc_error.setText(str(exc))
            return
        self._rc_error.setText("")
        at = len(self._patches)
        for offset, patch in enumerate(patches):
            self._patches.append(patch)
            self._item_list.insertItem(
                at + offset, QListWidgetItem(f"RC {patch.kind} patch  mat={patch.material_id}")
            )
        for lay in layers:
            self._layers.append(lay)
            self._item_list.addItem(
                QListWidgetItem(f"RC bars  mat={lay.material_id}  {lay.n_bars} bar(s)")
            )
        self._refresh_preview()

    # ── helpers ─────────────────────────────────────────────────────
    @staticmethod
    def _spin(default: float = 0.0, *, step: float = 0.01, minimum: float = -1e6) -> FloatField:
        sb = FloatField()
        sb.setRange(minimum, 1e6)
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
        is_rect = idx == 0
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
                n_fib_y=self._rect_ny.value(),
                n_fib_z=self._rect_nz.value(),
                y_i=self._rect_yi.value(),
                z_i=self._rect_zi.value(),
                y_j=self._rect_yj.value(),
                z_j=self._rect_zj.value(),
            )
            self._patches.append(p)
            self._item_list.addItem(
                QListWidgetItem(
                    f"Rect patch  mat={mid}  "
                    f"({p.y_i:.3f},{p.z_i:.3f})→({p.y_j:.3f},{p.z_j:.3f})  "
                    f"{p.n_fib_y}×{p.n_fib_z}",
                )
            )
        else:
            p = CircularPatch(
                material_id=mid,
                n_fib_circ=self._circ_nc.value(),
                n_fib_rad=self._circ_nr.value(),
                y_center=self._circ_yc.value(),
                z_center=self._circ_zc.value(),
                r_inner=self._circ_ri.value(),
                r_outer=self._circ_ro.value(),
            )
            self._patches.append(p)
            self._item_list.addItem(
                QListWidgetItem(
                    f"Circ patch  mat={mid}  "
                    f"r={p.r_inner:.3f}→{p.r_outer:.3f}  {p.n_fib_circ}×{p.n_fib_rad}",
                )
            )
        self._refresh_preview()

    def _on_add_layer(self) -> None:
        mid = self._layer_mat.currentData() or 1
        lay = StraightLayer(
            material_id=mid,
            n_bars=self._layer_nbars.value(),
            bar_area=self._layer_area.value(),
            y_start=self._layer_ys.value(),
            z_start=self._layer_zs.value(),
            y_end=self._layer_ye.value(),
            z_end=self._layer_ze.value(),
        )
        self._layers.append(lay)
        self._item_list.addItem(
            QListWidgetItem(
                f"Layer  mat={mid}  {lay.n_bars} bars  A={lay.bar_area:.4g}",
            )
        )
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
        sec = FiberSection(id=999999, patches=list(self._patches), layers=list(self._layers))
        props = compute_section_props(sec)
        if props.n_fibres == 0:
            self._props_label.setText("Add patches or layers to see the preview.")
            return

        # Color by material: assign a palette index per unique material_id.
        mat_ids = []
        for p in self._patches:
            mat_ids.append(p.material_id)
        for lay in self._layers:
            mat_ids.append(lay.material_id)
        unique_mats = sorted(set(mat_ids)) if mat_ids else [1]
        mat_to_color = {
            mid: _PATCH_COLORS[i % len(_PATCH_COLORS)] for i, mid in enumerate(unique_mats)
        }

        # Draw patch fibres as squares, layer fibres as circles.
        # Expand per-patch for color assignment.
        for p in self._patches:
            sub_sec = FiberSection(id=999999, patches=[p])
            sub = expand_fibres(sub_sec)
            if sub.size == 0:
                continue
            color = mat_to_color.get(p.material_id, "#888888")
            self._preview.plot(
                sub[:, 0],
                sub[:, 1],
                pen=None,
                symbol="s",
                symbolSize=6,
                symbolBrush=color,
                symbolPen=None,
            )
        for lay in self._layers:
            sub_sec = FiberSection(id=999999, layers=[lay])
            sub = expand_fibres(sub_sec)
            if sub.size == 0:
                continue
            color = mat_to_color.get(lay.material_id, "#ff0000")
            self._preview.plot(
                sub[:, 0],
                sub[:, 1],
                pen=None,
                symbol="o",
                symbolSize=8,
                symbolBrush=color,
                symbolPen=pg.mkPen("#ffffff", width=1),
            )

        # Centroid marker
        self._preview.plot(
            [props.centroid_y],
            [props.centroid_z],
            pen=None,
            symbol="+",
            symbolSize=16,
            symbolBrush=None,
            symbolPen=pg.mkPen("#ff0000", width=2),
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
                self._item_list.addItem(
                    QListWidgetItem(
                        f"Rect patch mat={p.material_id} {p.n_fib_y}×{p.n_fib_z}",
                    )
                )
            elif isinstance(p, CircularPatch):
                self._item_list.addItem(
                    QListWidgetItem(
                        f"Circ patch mat={p.material_id} {p.n_fib_circ}×{p.n_fib_rad}",
                    )
                )
        for lay in sec.layers:
            if isinstance(lay, StraightLayer):
                self._layers.append(lay)
                self._item_list.addItem(
                    QListWidgetItem(
                        f"Layer mat={lay.material_id} {lay.n_bars} bars",
                    )
                )
