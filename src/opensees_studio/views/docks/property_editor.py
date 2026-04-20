"""Property editor dock — selection-aware display and inline editing.

Single-node selection now lets the user edit lumped mass inline.
Edits dispatch through a callback the host wires in (typically to the
viewmodel's `apply_command`), so the property editor itself stays
dumb: no direct Project mutation, no Qt ↔ OpenSees coupling.
"""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core import Project


# Element types the Properties dock lets the user switch between.
# "ElasticBeamColumn" needs a section; "Truss" / "CorotTruss" need a
# uniaxial material + area. The Convert command drops/adds fields to
# bridge between them.
_CONVERTIBLE_ELEMENT_TYPES = [
    "Truss", "CorotTruss",
    "ElasticBeamColumn", "ForceBeamColumn", "DispBeamColumn",
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
        self.on_apply_mass: Callable[[int, tuple[float, float, float, float, float, float]], None] | None = None
        # Element callbacks — all optional; wired by MainWindow.
        self.on_change_element_type: Callable[[int, str], None] | None = None
        self.on_change_element_material: Callable[[int, int], None] | None = None
        self.on_change_element_section: Callable[[int, int], None] | None = None
        self.on_change_element_fields: Callable[[int, dict], None] | None = None
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
        form.addRow("X, Y, Z:", QLabel(
            f"{node.coords[0]:.4f}, {node.coords[1]:.4f}, {node.coords[2]:.4f}",
        ))
        form.addRow("Restraint:", QLabel(self._fmt_restraint(node.restraint)))
        self._layout.addLayout(form)

        # ── Mass editor ──
        group = QGroupBox("Lumped mass")
        gform = QFormLayout(group)
        self._mass_spins: list[QDoubleSpinBox] = []
        labels = ("mx", "my", "mz", "Ixx", "Iyy", "Izz")
        for i, lbl in enumerate(labels):
            sb = QDoubleSpinBox()
            sb.setRange(0.0, 1e12)
            sb.setDecimals(4)
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
        if (hasattr(el, "section_id")
                and self._project is not None
                and self._project.sections
                and self.on_change_element_section is not None):
            sec_cb = QComboBox()
            for s in self._project.sections:
                sec_cb.addItem(
                    f"#{s.id} {s.name or s.type}", s.id,
                )
            idx = sec_cb.findData(el.section_id)      # type: ignore[attr-defined]
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
        if (hasattr(el, "material_id")
                and self._project is not None
                and self._project.materials
                and self.on_change_element_material is not None):
            mat_cb = QComboBox()
            for m in self._project.materials:
                mat_cb.addItem(f"#{m.id} {m.name or m.type}", m.id)
            idx = mat_cb.findData(el.material_id)     # type: ignore[attr-defined]
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

        # ── Inline-editable Area (truss-style elements). ──
        if hasattr(el, "area") and self.on_change_element_fields is not None:
            area_spin = QDoubleSpinBox()
            area_spin.setRange(1e-12, 1e6)
            area_spin.setDecimals(8)
            area_spin.setValue(float(el.area))                 # type: ignore[attr-defined]
            area_spin.setSingleStep(float(el.area) * 0.1       # type: ignore[attr-defined]
                                    if el.area else 0.001)      # type: ignore[attr-defined]

            # Commit on editingFinished so we don't dispatch a command on
            # every keystroke (which would spam the undo stack).
            def _on_area_edited(_eid: int = el.id) -> None:
                new_val = area_spin.value()
                # Skip no-op edits: the property dock is re-rendered after
                # any model mutation, so editingFinished fires on focus-out
                # too — we don't want a stack of identical commands.
                try:
                    current = float(self._project.element(_eid).area)  # type: ignore[union-attr]
                except (KeyError, AttributeError):
                    current = None
                if current is not None and abs(current - new_val) < 1e-15:
                    return
                if self.on_change_element_fields is not None:
                    self.on_change_element_fields(_eid, {"area": new_val})
            area_spin.editingFinished.connect(_on_area_edited)
            form.addRow("Area:", area_spin)
        elif hasattr(el, "area"):
            form.addRow("Area:", QLabel(f"{el.area:g}"))

        if hasattr(el, "geom_transf"):
            form.addRow("Geom transf:", QLabel(el.geom_transf))
        self._layout.addLayout(form)
        self._layout.addStretch(1)

    def _show_multi(self, node_ids: frozenset[int], element_ids: frozenset[int]) -> None:
        self._layout.addWidget(QLabel("<h3>Multi-selection</h3>"))
        if node_ids:
            self._layout.addWidget(QLabel(
                f"<b>{len(node_ids)}</b> node(s) selected: {self._fmt_id_list(node_ids)}",
            ))
        if element_ids:
            self._layout.addWidget(QLabel(
                f"<b>{len(element_ids)}</b> element(s) selected: {self._fmt_id_list(element_ids)}",
            ))
        self._layout.addStretch(1)

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
        return ", ".join(str(i) for i in sorted_ids[:limit]) + f", … (+{len(sorted_ids) - limit} more)"
