"""Property editor dock — selection-aware display and inline editing.

Single-node selection now lets the user edit lumped mass inline.
Edits dispatch through a callback the host wires in (typically to the
viewmodel's `apply_command`), so the property editor itself stays
dumb: no direct Project mutation, no Qt ↔ OpenSees coupling.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core import (
    BEAM_INTEGRATION_RULES,
    BEARING_CLASSES,
    CARDINAL_POINT_NAMES,
    GEOM_TRANSF_TYPES,
    SLIDING_BEARING_CLASSES,
    FrameEndOffsets,
    FrameMember,
    Project,
)
from opensees_studio.views.float_field import FloatField

# Element types the Properties dock lets the user switch between.
# "ElasticBeamColumn" needs a section; "Truss" / "CorotTruss" need a
# uniaxial material + area. The Convert command drops/adds fields to
# bridge between them.
_CONVERTIBLE_ELEMENT_TYPES = [
    "Truss",
    "CorotTruss",
    "ElasticBeamColumn",
    "ForceBeamColumn",
    "DispBeamColumn",
]


class PropertyEditorDock(QScrollArea):
    """The dock contents — embed in a QDockWidget.

    The host can set :attr:`on_apply_mass` to receive inline mass edits
    as ``(node_id, (mx, my, mz, Ixx, Iyy, Izz))``. If not wired, the
    apply button is hidden.
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self._inner = QWidget()
        self._layout = QVBoxLayout(self._inner)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self.setWidget(self._inner)
        self._project: Project | None = None
        self.on_apply_mass: (
            Callable[[int, tuple[float, float, float, float, float, float]], None] | None
        ) = None
        # Element callbacks — all optional; wired by MainWindow.
        self.on_change_element_type: Callable[[int, str], None] | None = None
        self.on_change_element_material: Callable[[int, int], None] | None = None
        self.on_change_element_section: Callable[[int, int], None] | None = None
        self.on_change_element_fields: Callable[[int, dict], None] | None = None
        # Multi-selection callbacks — one call per Apply, one undo step on the host side.
        self.on_assign_node_restraints: Callable[[dict[int, tuple[bool, ...]]], None] | None = None
        self.on_assign_node_masses: Callable[[dict[int, tuple[float, ...]]], None] | None = None
        self.on_assign_elements: Callable[[MultiElementEdit], None] | None = None
        self._show_empty()

    def set_project(self, project: Project | None) -> None:
        self._project = project
        self._show_empty()

    def update_for_selection(self, node_ids: frozenset[int], element_ids: frozenset[int]) -> None:
        """Populate the panel based on the current selection."""
        self._clear()
        if self._project is None or (not node_ids and not element_ids):
            self._show_empty()
            return

        total = len(node_ids) + len(element_ids)
        if total == 1:
            if node_ids:
                self._show_node(next(iter(node_ids)))
            else:
                self._show_element(next(iter(element_ids)))
        else:
            self._show_multi(node_ids, element_ids)

    # ── helpers ──────────────────────────────────────────────────────
    def _clear(self) -> None:
        """Recursively remove every child widget AND layout under self._layout."""
        while self._layout.count():
            item = self._layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
                continue
            child_layout = item.layout()
            if child_layout is not None:
                self._delete_layout(child_layout)

    @staticmethod
    def _delete_layout(layout) -> None:  # type: ignore[no-untyped-def]
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
            child = item.layout()
            if child is not None:
                PropertyEditorDock._delete_layout(child)
        layout.deleteLater()

    def _show_empty(self) -> None:
        self._clear()
        lbl = QLabel("<i>(no selection)</i>")
        self._layout.addWidget(lbl)
        self._layout.addStretch(1)

    def _show_node(self, node_id: int) -> None:
        try:
            node = self._project.node(node_id)  # type: ignore[union-attr]
        except (KeyError, AttributeError):
            self._show_empty()
            return
        self._layout.addWidget(QLabel(f"<h3>Node #{node.id}</h3>"))
        form = QFormLayout()
        form.addRow("Name:", QLabel(node.name or "—"))
        form.addRow(
            "X, Y, Z:",
            QLabel(
                f"{node.coords[0]:.4f}, {node.coords[1]:.4f}, {node.coords[2]:.4f}",
            ),
        )
        form.addRow("Restraint:", QLabel(self._fmt_restraint(node.restraint)))
        self._layout.addLayout(form)

        # ── Mass editor ──
        group = QGroupBox("Lumped mass")
        gform = QFormLayout(group)
        self._mass_spins: list[FloatField] = []
        labels = ("mx", "my", "mz", "Ixx", "Iyy", "Izz")
        for i, lbl in enumerate(labels):
            sb = FloatField()
            sb.setRange(0.0, 1e12)
            sb.setSingleStep(100.0)
            sb.setValue(float(node.mass[i]))
            self._mass_spins.append(sb)
            gform.addRow(f"{lbl}:", sb)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self._apply_mass_btn = QPushButton("Apply mass")
        self._apply_mass_btn.clicked.connect(
            lambda: self._emit_apply_mass(node.id),
        )
        if self.on_apply_mass is None:
            self._apply_mass_btn.setVisible(False)
        btn_row.addWidget(self._apply_mass_btn)
        gform.addRow(btn_row)

        self._layout.addWidget(group)
        self._layout.addStretch(1)

    def _emit_apply_mass(self, node_id: int) -> None:
        if self.on_apply_mass is None:
            return
        mass = tuple(sb.value() for sb in self._mass_spins)
        self.on_apply_mass(node_id, mass)  # type: ignore[arg-type]

    def _show_element(self, element_id: int) -> None:
        try:
            el = self._project.element(element_id)  # type: ignore[union-attr]
        except (KeyError, AttributeError):
            self._show_empty()
            return
        self._layout.addWidget(QLabel(f"<h3>Element #{el.id}</h3>"))
        form = QFormLayout()

        # ── Type selector (convertible types only). ──
        if el.type in _CONVERTIBLE_ELEMENT_TYPES and self.on_change_element_type is not None:
            type_cb = QComboBox()
            type_cb.addItems(_CONVERTIBLE_ELEMENT_TYPES)
            type_cb.setCurrentText(el.type)

            def _on_type_changed(new_type: str, _eid: int = el.id) -> None:
                if new_type != el.type and self.on_change_element_type is not None:
                    self.on_change_element_type(_eid, new_type)

            type_cb.currentTextChanged.connect(_on_type_changed)
            form.addRow("Type:", type_cb)
        else:
            form.addRow("Type:", QLabel(el.type))

        form.addRow("Name:", QLabel(el.name or "—"))
        form.addRow("Nodes:", QLabel(", ".join(str(n) for n in el.nodes)))

        # ── Section picker for frame elements. ──
        if (
            hasattr(el, "section_id")
            and self._project is not None
            and self._project.sections
            and self.on_change_element_section is not None
        ):
            sec_cb = QComboBox()
            for s in self._project.sections:
                sec_cb.addItem(
                    f"#{s.id} {s.name or s.type}",
                    s.id,
                )
            idx = sec_cb.findData(el.section_id)
            if idx >= 0:
                sec_cb.setCurrentIndex(idx)

            def _on_section_changed(_i: int, _eid: int = el.id) -> None:
                sid = sec_cb.currentData()
                if sid is not None and self.on_change_element_section is not None:
                    self.on_change_element_section(_eid, int(sid))

            sec_cb.currentIndexChanged.connect(_on_section_changed)
            form.addRow("Section:", sec_cb)
        elif hasattr(el, "section_id"):
            form.addRow("Section id:", QLabel(str(el.section_id)))

        # ── Material picker for truss / uniaxial-material elements. ──
        if (
            hasattr(el, "material_id")
            and self._project is not None
            and self._project.materials
            and self.on_change_element_material is not None
        ):
            mat_cb = QComboBox()
            for m in self._project.materials:
                mat_cb.addItem(f"#{m.id} {m.name or m.type}", m.id)
            idx = mat_cb.findData(el.material_id)
            if idx >= 0:
                mat_cb.setCurrentIndex(idx)

            def _on_material_changed(_i: int, _eid: int = el.id) -> None:
                mid = mat_cb.currentData()
                if mid is not None and self.on_change_element_material is not None:
                    self.on_change_element_material(_eid, int(mid))

            mat_cb.currentIndexChanged.connect(_on_material_changed)
            form.addRow("Material:", mat_cb)
        elif hasattr(el, "material_id"):
            form.addRow("Material id:", QLabel(str(el.material_id)))

        # ── Inline-editable Area (truss-style elements) and unit weight. ──
        for field, label, minimum in (
            ("area", "Area:", 1e-12),
            ("unit_weight", "Unit weight γ:", 0.0),
        ):
            if not hasattr(el, field):
                continue
            value = float(getattr(el, field))
            if self.on_change_element_fields is None:
                form.addRow(label, QLabel(f"{value:g}"))
                continue
            spin = FloatField()
            spin.setRange(minimum, 1e12)
            spin.setValue(value)
            spin.setSingleStep(value * 0.1 if value else 0.001)

            # Commit on editingFinished so we don't dispatch a command on
            # every keystroke (which would spam the undo stack).
            def _on_edited(
                _eid: int = el.id, _field: str = field, _spin: FloatField = spin
            ) -> None:
                new_val = _spin.value()
                # Skip no-op edits: the property dock is re-rendered after
                # any model mutation, so editingFinished fires on focus-out
                # too — we don't want a stack of identical commands.
                try:
                    current = float(getattr(self._project.element(_eid), _field))  # type: ignore[union-attr]
                except (KeyError, AttributeError):
                    current = None
                if current == new_val:
                    return
                if self.on_change_element_fields is not None:
                    self.on_change_element_fields(_eid, {_field: new_val})

            spin.editingFinished.connect(_on_edited)
            form.addRow(label, spin)

        if hasattr(el, "geom_transf") and self.on_change_element_fields is not None:
            transf_cb = QComboBox()
            transf_cb.addItems(list(GEOM_TRANSF_TYPES))
            transf_cb.setCurrentText(el.geom_transf)

            def _on_transf_changed(new: str, _eid: int = el.id, _old: str = el.geom_transf) -> None:
                if new != _old and self.on_change_element_fields is not None:
                    self.on_change_element_fields(_eid, {"geom_transf": new})

            transf_cb.currentTextChanged.connect(_on_transf_changed)
            form.addRow("Geom transf:", transf_cb)
        elif hasattr(el, "geom_transf"):
            form.addRow("Geom transf:", QLabel(el.geom_transf))
        # ``getattr`` rather than a ``hasattr`` guard plus attribute access: the
        # element union is wide, and mypy does not narrow through ``hasattr``,
        # so the direct read is a type error for every member without the field.
        integration = getattr(el, "integration", None)
        if integration is not None and self.on_change_element_fields is not None:
            self._add_integration_rows(form, el)
        elif integration is not None:
            points = getattr(el, "integration_points", None)
            form.addRow("Integration:", QLabel(f"{integration}, {points} points"))
        if isinstance(el, FrameMember):
            self._add_frame_option_rows(form, el)
        if isinstance(el, SLIDING_BEARING_CLASSES):
            self._add_sliding_bearing_rows(form, el, self._project)
        elif isinstance(el, BEARING_CLASSES):
            self._add_bearing_rows(form, el)
        self._layout.addLayout(form)
        self._layout.addStretch(1)

    @staticmethod
    def _release_text(el: Any) -> str:
        parts = []
        for end in ("i", "j"):
            release = el.releases.end(end)
            if not release.released:
                continue
            items = [
                f"{d} (k={release.spring(d):g})" if release.spring(d) else d
                for d in release.released
            ]
            parts.append(f"{end}: {', '.join(items)}")
        return "; ".join(parts) or "none"

    @staticmethod
    def _modifier_text(el: Any) -> str:
        mods = el.modifiers
        changed = [
            f"{name}={getattr(mods, name):g}"
            for name in type(mods).model_fields
            if getattr(mods, name) != 1.0
        ]
        return ", ".join(changed) or "none"

    def _add_frame_option_rows(self, form: QFormLayout, el: Any) -> None:
        """Frame assignments: releases and modifiers as text, offsets and insertion editable."""
        form.addRow("Releases:", QLabel(self._release_text(el)))
        form.addRow("Modifiers:", QLabel(self._modifier_text(el)))
        offsets = el.end_offsets
        insertion = el.insertion
        if self.on_change_element_fields is None:
            form.addRow(
                "End offsets:",
                QLabel(
                    f"i {offsets.length_i:g}, j {offsets.length_j:g}, "
                    f"rigid factor {offsets.rigid_factor:g}"
                ),
            )
            form.addRow("Insertion:", QLabel(f"cardinal point {insertion.cardinal_point}"))
            return
        fields: dict[str, FloatField] = {}
        for name, label, hi in (
            ("length_i", "Offset i:", 1e12),
            ("length_j", "Offset j:", 1e12),
            ("rigid_factor", "Rigid-zone factor:", 1.0),
        ):
            field = FloatField()
            field.setRange(0.0, hi)
            field.setValue(getattr(offsets, name))
            fields[name] = field
            form.addRow(label, field)

        def _commit_offsets(_eid: int = el.id, _old: Any = offsets) -> None:
            values = {name: field.value() for name, field in fields.items()}
            if values == _old.model_dump() or self.on_change_element_fields is None:
                return
            try:
                new = FrameEndOffsets(**values)
            except ValueError:
                return
            self.on_change_element_fields(_eid, {"end_offsets": new})

        for field in fields.values():
            field.editingFinished.connect(_commit_offsets)

        cardinal = QComboBox()
        for point, name in CARDINAL_POINT_NAMES.items():
            cardinal.addItem(f"{point} ({name})", point)
        cardinal.setCurrentIndex(cardinal.findData(insertion.cardinal_point))

        def _commit_cardinal(_i: int, _eid: int = el.id, _old: Any = insertion) -> None:
            point = cardinal.currentData()
            if point != _old.cardinal_point and self.on_change_element_fields is not None:
                self.on_change_element_fields(
                    _eid, {"insertion": _old.model_copy(update={"cardinal_point": point})}
                )

        cardinal.currentIndexChanged.connect(_commit_cardinal)
        form.addRow("Cardinal point:", cardinal)
        self._frame_offset_fields = fields
        self._cardinal_point = cardinal

    def _add_integration_rows(self, form: QFormLayout, el: Any) -> None:
        """Editable beam integration rule and point count (force/disp beam-columns)."""
        rule_cb = QComboBox()
        rule_cb.addItems(list(BEAM_INTEGRATION_RULES))
        rule_cb.setCurrentText(el.integration)
        points_sb = QSpinBox()
        points_sb.setRange(2, 10)
        points_sb.setValue(el.integration_points)

        def _commit(_arg: object = None, _eid: int = el.id) -> None:
            rule, points = rule_cb.currentText(), points_sb.value()
            if (rule, points) == (el.integration, el.integration_points):
                return
            if self.on_change_element_fields is not None:
                self.on_change_element_fields(
                    _eid, {"integration": rule, "integration_points": points}
                )

        rule_cb.currentTextChanged.connect(_commit)
        points_sb.editingFinished.connect(_commit)
        self._integration_rule = rule_cb
        self._integration_points = points_sb
        form.addRow("Integration rule:", rule_cb)
        form.addRow("Integration points:", points_sb)

    @staticmethod
    def _add_bearing_options_row(form: QFormLayout, el: Any) -> None:
        flags = []
        if el.orient is not None:
            flags.append("orient " + ", ".join(f"{v:g}" for v in el.orient))
        if el.shear_dist != 0.5:
            flags.append(f"shearDist {el.shear_dist:g}")
        if el.do_rayleigh:
            flags.append("doRayleigh")
        if el.mass:
            flags.append(f"mass {el.mass:g}")
        form.addRow("Options:", QLabel(", ".join(flags) if flags else "defaults"))

    @staticmethod
    def _add_sliding_bearing_rows(form: QFormLayout, el: Any, project: Project | None) -> None:
        """Read-only parameters and derived values of a sliding bearing."""
        form.addRow("Type:", QLabel(el.type))
        form.addRow("Nodes:", QLabel(f"{el.nodes[0]} - {el.nodes[1]}"))
        friction = f"#{el.friction_model_id}"
        if project is not None:
            try:
                fm = project.friction_model(el.friction_model_id)
                friction += f" {fm.name or fm.type} [{fm.type}]"
            except KeyError:
                friction += " (missing)"
        form.addRow("Friction model:", QLabel(friction))
        form.addRow("Kinit:", QLabel(f"{el.k_init:g}"))
        if el.type == "SingleFPBearing":
            form.addRow("Reff:", QLabel(f"{el.r_eff:g}"))
            if project is not None:
                units = project.meta.units
                form.addRow(
                    "Isolated period 2 pi sqrt(Reff / g):",
                    QLabel(f"{el.isolated_period(units):.6g} s"),
                )
        mats = f"P #{el.p_material_id}, Mz #{el.mz_material_id}"
        if el.t_material_id is not None or el.my_material_id is not None:
            mats += f", T #{el.t_material_id}, My #{el.my_material_id}"
        form.addRow("Materials:", QLabel(mats))
        if el.max_iter != 25 or el.tol != 1e-12:
            form.addRow("-iter:", QLabel(f"{el.max_iter} iterations, tol {el.tol:g}"))
        PropertyEditorDock._add_bearing_options_row(form, el)

    @staticmethod
    def _add_bearing_rows(form: QFormLayout, el: Any) -> None:
        """Read-only parameters and derived values of an elastomeric bearing."""
        form.addRow("Type:", QLabel(el.type))
        form.addRow("Nodes:", QLabel(f"{el.nodes[0]} - {el.nodes[1]}"))
        form.addRow("Kinit:", QLabel(f"{el.k_init:g}"))
        form.addRow("Qd:", QLabel(f"{el.qd:g}"))
        form.addRow("alpha1 / alpha2 / mu:", QLabel(f"{el.alpha1:g} / {el.alpha2:g} / {el.mu:g}"))
        if el.type == "ElastomericBearingBoucWen":
            form.addRow("eta / beta / gamma:", QLabel(f"{el.eta:g} / {el.beta:g} / {el.gamma:g}"))
        mats = f"P #{el.p_material_id}, Mz #{el.mz_material_id}"
        if el.t_material_id is not None or el.my_material_id is not None:
            mats += f", T #{el.t_material_id}, My #{el.my_material_id}"
        form.addRow("Materials:", QLabel(mats))
        form.addRow("Yield displacement u_y:", QLabel(f"{el.yield_displacement:.6g}"))
        form.addRow("Yield force F_y:", QLabel(f"{el.yield_force:.6g}"))
        PropertyEditorDock._add_bearing_options_row(form, el)

    def _show_multi(self, node_ids: frozenset[int], element_ids: frozenset[int]) -> None:
        """Several things selected: edit what they share, in one step per group.

        A value every selected item has is shown as it is; one that differs
        shows ``(varies)`` and is left alone unless it is changed. Apply sends
        only what was changed.
        """
        self._layout.addWidget(QLabel("<h3>Multi-selection</h3>"))
        project = self._project
        nodes = [n for n in project.nodes if n.id in node_ids] if project else []
        elements = [e for e in project.elements if e.id in element_ids] if project else []
        if node_ids:
            self._layout.addWidget(
                QLabel(
                    f"<b>{len(node_ids)}</b> node(s) selected: {self._fmt_id_list(node_ids)}",
                )
            )
            if nodes and (
                self.on_assign_node_restraints is not None or self.on_assign_node_masses is not None
            ):
                self._layout.addWidget(self._multi_node_group(nodes))
        if element_ids:
            self._layout.addWidget(
                QLabel(
                    f"<b>{len(element_ids)}</b> element(s) selected: {self._fmt_id_list(element_ids)}",
                )
            )
            if elements and self.on_assign_elements is not None:
                self._layout.addWidget(self._multi_element_group(elements))
        self._layout.addStretch(1)

    # ── multi-selection: joints ──────────────────────────────────────
    def _multi_node_group(self, nodes: list[Any]) -> QGroupBox:
        group = QGroupBox(f"Edit {len(nodes)} joint(s)")
        form = QFormLayout(group)
        labels = ("Ux", "Uy", "Uz", "Rx", "Ry", "Rz")
        row = QHBoxLayout()
        boxes: list[QCheckBox] = []
        for i, label in enumerate(labels):
            box = QCheckBox(label)
            values = {bool(n.restraint[i]) for n in nodes}
            if len(values) > 1:
                box.setTristate(True)
                box.setCheckState(Qt.CheckState.PartiallyChecked)
            else:
                box.setChecked(values.pop())
            boxes.append(box)
            row.addWidget(box)
        form.addRow("Restraint:", row)
        masses = [_multi_float([float(n.mass[i]) for n in nodes], 0.0, 1e12) for i in range(6)]
        for label, field in zip(("mx", "my", "mz", "Ixx", "Iyy", "Izz"), masses, strict=True):
            form.addRow(f"{label}:", field)

        def _apply() -> None:
            restraints: dict[int, tuple[bool, ...]] = {}
            new_masses: dict[int, tuple[float, ...]] = {}
            for node in nodes:
                r = tuple(
                    bool(node.restraint[i])
                    if box.checkState() == Qt.CheckState.PartiallyChecked
                    else box.isChecked()
                    for i, box in enumerate(boxes)
                )
                if r != tuple(node.restraint):
                    restraints[node.id] = r
                m = tuple(
                    float(node.mass[i]) if (v := _read_multi(field)) is None else v
                    for i, field in enumerate(masses)
                )
                if m != tuple(node.mass):
                    new_masses[node.id] = m
            if restraints and self.on_assign_node_restraints is not None:
                self.on_assign_node_restraints(restraints)
            if new_masses and self.on_assign_node_masses is not None:
                self.on_assign_node_masses(new_masses)

        button = QPushButton(f"Apply to {len(nodes)} joint(s)")
        button.clicked.connect(_apply)
        form.addRow(button)
        self._multi_restraint_boxes = boxes
        self._multi_mass_fields = masses
        self._multi_node_apply = button
        return group

    # ── multi-selection: elements ────────────────────────────────────
    def _multi_element_group(self, elements: list[Any]) -> QGroupBox:
        project = self._project
        assert project is not None
        group = QGroupBox(f"Edit {len(elements)} element(s)")
        form = QFormLayout(group)
        types = {e.type for e in elements}
        form.addRow("Types:", QLabel(", ".join(sorted(types))))
        controls: dict[str, Any] = {}

        if all(e.type in _CONVERTIBLE_ELEMENT_TYPES for e in elements):
            controls["type"] = _multi_combo(
                [(t, t) for t in _CONVERTIBLE_ELEMENT_TYPES], [e.type for e in elements]
            )
            form.addRow("Type:", controls["type"])
        with_section = [e for e in elements if hasattr(e, "section_id")]
        if with_section and project.sections:
            controls["section_id"] = _multi_combo(
                [(f"#{s.id} {s.name or s.type}", s.id) for s in project.sections],
                [e.section_id for e in with_section],
            )
            form.addRow(f"Section ({len(with_section)}):", controls["section_id"])
        with_material = [e for e in elements if hasattr(e, "material_id")]
        if with_material and project.materials:
            controls["material_id"] = _multi_combo(
                [(f"#{m.id} {m.name or m.type}", m.id) for m in project.materials],
                [e.material_id for e in with_material],
            )
            form.addRow(f"Material ({len(with_material)}):", controls["material_id"])
        with_area = [e for e in elements if hasattr(e, "area")]
        if with_area:
            controls["area"] = _multi_float([float(e.area) for e in with_area], 1e-12, 1e6)
            form.addRow(f"Area ({len(with_area)}):", controls["area"])
        with_weight = [e for e in elements if hasattr(e, "unit_weight")]
        if with_weight:
            controls["unit_weight"] = _multi_float(
                [float(e.unit_weight) for e in with_weight], 0.0, 1e12
            )
            form.addRow(f"Unit weight γ ({len(with_weight)}):", controls["unit_weight"])
        with_transf = [e for e in elements if hasattr(e, "geom_transf")]
        if with_transf:
            controls["geom_transf"] = _multi_combo(
                [(t, t) for t in GEOM_TRANSF_TYPES], [e.geom_transf for e in with_transf]
            )
            form.addRow(f"Geom transf ({len(with_transf)}):", controls["geom_transf"])
        with_rule = [e for e in elements if getattr(e, "integration", None) is not None]
        if with_rule:
            controls["integration"] = _multi_combo(
                [(r, r) for r in BEAM_INTEGRATION_RULES], [e.integration for e in with_rule]
            )
            controls["integration_points"] = _multi_combo(
                [(str(p), p) for p in range(2, 11)], [e.integration_points for e in with_rule]
            )
            form.addRow(f"Integration rule ({len(with_rule)}):", controls["integration"])
            form.addRow("Integration points:", controls["integration_points"])
        members = [e for e in elements if isinstance(e, FrameMember)]
        if members:
            for name, label, hi in (
                ("length_i", "Offset i", 1e12),
                ("length_j", "Offset j", 1e12),
                ("rigid_factor", "Rigid-zone factor", 1.0),
            ):
                controls[name] = _multi_float(
                    [float(getattr(e.end_offsets, name)) for e in members], 0.0, hi
                )
                form.addRow(f"{label} ({len(members)}):", controls[name])
            controls["cardinal_point"] = _multi_combo(
                [(f"{p} ({n})", p) for p, n in CARDINAL_POINT_NAMES.items()],
                [e.insertion.cardinal_point for e in members],
            )
            form.addRow("Cardinal point:", controls["cardinal_point"])
            releases = {self._release_text(e) for e in members}
            modifiers = {self._modifier_text(e) for e in members}
            form.addRow("Releases:", QLabel(releases.pop() if len(releases) == 1 else "(varies)"))
            form.addRow(
                "Modifiers:", QLabel(modifiers.pop() if len(modifiers) == 1 else "(varies)")
            )

        def _apply() -> None:
            edit = MultiElementEdit(element_ids={e.id for e in elements})
            if "type" in controls:
                edit.new_type = _read_combo(controls["type"])
            for key in ("section_id", "material_id"):
                if key in controls:
                    setattr(edit, key, _read_combo(controls[key]))
            fields: dict[str, Any] = {}
            for key in ("geom_transf", "integration", "integration_points"):
                if key in controls and (value := _read_combo(controls[key])) is not None:
                    fields[key] = value
            if "area" in controls and (area := _read_multi(controls["area"])) is not None:
                fields["area"] = area
            if (
                "unit_weight" in controls
                and (weight := _read_multi(controls["unit_weight"])) is not None
            ):
                fields["unit_weight"] = weight
            edit.fields = fields
            if members:
                offsets = {
                    k: _read_multi(controls[k]) for k in ("length_i", "length_j", "rigid_factor")
                }
                point = _read_combo(controls["cardinal_point"])
                for e in members:
                    update: dict[str, Any] = {}
                    changed = {k: v for k, v in offsets.items() if v is not None}
                    if changed:
                        new = e.end_offsets.model_copy(update=changed)
                        if new != e.end_offsets:
                            update["end_offsets"] = new
                    if point is not None and point != e.insertion.cardinal_point:
                        update["insertion"] = e.insertion.model_copy(
                            update={"cardinal_point": point}
                        )
                    if update:
                        edit.per_element[e.id] = update
            if edit.is_empty or self.on_assign_elements is None:
                return
            self.on_assign_elements(edit)

        button = QPushButton(f"Apply to {len(elements)} element(s)")
        button.clicked.connect(_apply)
        form.addRow(button)
        self._multi_element_controls = controls
        self._multi_element_apply = button
        return group

    @staticmethod
    def _fmt_restraint(r: tuple[bool, ...]) -> str:
        labels = ("Ux", "Uy", "Uz", "Rx", "Ry", "Rz")
        fixed = [labels[i] for i, v in enumerate(r) if v]
        return ", ".join(fixed) if fixed else "free"

    @staticmethod
    def _fmt_id_list(ids: frozenset[int], limit: int = 12) -> str:
        sorted_ids = sorted(ids)
        if len(sorted_ids) <= limit:
            return ", ".join(str(i) for i in sorted_ids)
        return (
            ", ".join(str(i) for i in sorted_ids[:limit]) + f", … (+{len(sorted_ids) - limit} more)"
        )


# ─────────────────────────── multi-selection helpers ───────────────────────────
VARIES = "(varies)"
"""What a field shows when the selected items do not share its value."""


class MultiElementEdit:
    """What an Apply on several elements changes (``None`` = left as each one has it)."""

    def __init__(self, element_ids: set[int]) -> None:
        self.element_ids = element_ids
        self.new_type: str | None = None
        self.section_id: int | None = None
        self.material_id: int | None = None
        self.fields: dict[str, Any] = {}
        """Same value for every element that has the field."""
        self.per_element: dict[int, dict[str, Any]] = {}
        """Values that differ per element (end offsets, insertion)."""

    @property
    def is_empty(self) -> bool:
        return (
            self.new_type is None
            and self.section_id is None
            and self.material_id is None
            and not self.fields
            and not self.per_element
        )


def _multi_float(values: list[float], lo: float, hi: float) -> FloatField:
    """A number field: the shared value, or ``(varies)`` until the user types one."""
    field = FloatField()
    shared = set(values)
    if len(shared) == 1:
        field.setRange(lo, hi)
        field.setValue(shared.pop())
        field.setProperty("multi_initial", field.value())
        return field
    # Below the range: the minimum shows the special text and means "unchanged".
    sentinel = lo - max(1.0, abs(lo))
    field.setRange(sentinel, hi)
    field.setSpecialValueText(VARIES)
    field.setValue(sentinel)
    field.setProperty("multi_initial", sentinel)
    field.setProperty("multi_low", lo)
    return field


def _read_multi(field: FloatField) -> float | None:
    """The typed value, or ``None`` when the field still shows what it started with."""
    value = field.value()
    if value == field.property("multi_initial"):
        return None
    low = field.property("multi_low")
    if low is not None and value < float(low):
        return None
    return float(value)


def _multi_combo(items: list[tuple[str, Any]], values: list[Any]) -> QComboBox:
    """A choice: the shared one selected, or ``(varies)`` first and selected."""
    combo = QComboBox()
    shared = set(values)
    if len(shared) != 1:
        combo.addItem(VARIES, None)
    for text, data in items:
        combo.addItem(text, data)
    combo.setCurrentIndex(combo.findData(shared.pop()) if len(shared) == 1 else 0)
    combo.setProperty("multi_initial", combo.currentIndex())
    return combo


def _read_combo(combo: QComboBox) -> Any:
    """The chosen value, or ``None`` when the selection was not changed."""
    if combo.currentIndex() == combo.property("multi_initial"):
        return None
    return combo.currentData()
