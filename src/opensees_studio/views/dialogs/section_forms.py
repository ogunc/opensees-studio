"""Section parameter forms.

For Phase 5, only :class:`ElasticSection` has a real form. The fiber
section visual editor is deferred to Phase 5b — a flat fibre list
isn't usefully editable in a tab.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core import (
    DEFAULT_UNIT_WEIGHT,
    ElasticMembranePlateSection,
    ElasticSection,
    FiberSection,
    NonprismaticSection,
    NonprismaticSegment,
    SectionAggregator,
)
from opensees_studio.views.float_field import FloatField


def _spin(
    default: float = 0.0,
    *,
    minimum: float = 1e-12,
    maximum: float = 1e15,
    step: float = 1.0,
) -> FloatField:
    sb = FloatField()
    sb.setRange(minimum, maximum)
    sb.setSingleStep(step)
    sb.setValue(default)
    return sb


class SectionFormBase(QWidget):
    type_label: str = "Section"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._section_id: int | None = None
        self._layout = QFormLayout(self)
        self._name_edit = QLineEdit()
        self._layout.addRow("Name:", self._name_edit)

    def populate(self, section: Any) -> None:
        self._section_id = section.id
        self._name_edit.setText(section.name)
        self._populate_specific(section)

    def _populate_specific(self, section: Any) -> None: ...

    def read(self, section_id: int | None = None) -> Any:
        sid = self._section_id if self._section_id is not None else section_id
        if sid is None:
            raise ValueError("Section id required.")
        return self._read_specific(sid)

    def _read_specific(self, section_id: int) -> Any:
        raise NotImplementedError


class ElasticSectionForm(SectionFormBase):
    type_label = "Elastic Section"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._e = _spin(200e9, step=1e9)
        self._a = _spin(0.01, step=1e-4)
        self._iz = _spin(8.33e-6, step=1e-7)
        self._iy = _spin(8.33e-6, step=1e-7)
        self._g = _spin(80e9, step=1e9)
        self._j = _spin(1e-6, step=1e-7)
        self._as2 = _spin(0.0, minimum=0.0, step=1e-4)
        self._as3 = _spin(0.0, minimum=0.0, step=1e-4)
        for w, axis in ((self._as2, "2 (y)"), (self._as3, "3 (z)")):
            w.setToolTip(
                f"Shear area for shear along local {axis}. 0 = rigid in shear (Euler-Bernoulli). "
                "With a shear area the member becomes a Timoshenko beam; it then takes "
                "full-length uniform loads only, and needs G."
            )
        self._unit_weight = _spin(0.0, minimum=0.0, step=1e3)
        self._unit_weight.setToolTip(
            "Weight per unit volume (force / length³). A load pattern with a self "
            "weight applies gamma * A per unit length; 0 = weightless."
        )
        self._shape: Any = None
        for label, w in (
            ("E:", self._e),
            ("A:", self._a),
            ("Iz:", self._iz),
            ("Iy:", self._iy),
            ("G:", self._g),
            ("J:", self._j),
            ("Shear area As2:", self._as2),
            ("Shear area As3:", self._as3),
            ("Unit weight γ:", self._unit_weight),
        ):
            self._layout.addRow(label, w)
        self._layout.addRow(QLabel("<i>Iy, G, J required for 3D models.</i>"))

    def _populate_specific(self, s: ElasticSection) -> None:
        self._e.setValue(s.E)
        self._a.setValue(s.A)
        self._iz.setValue(s.Iz)
        if s.Iy is not None:
            self._iy.setValue(s.Iy)
        if s.G is not None:
            self._g.setValue(s.G)
        if s.J is not None:
            self._j.setValue(s.J)
        self._as2.setValue(s.As2 or 0.0)
        self._as3.setValue(s.As3 or 0.0)
        self._unit_weight.setValue(s.unit_weight)
        self._shape = s.shape

    def _read_specific(self, sid: int) -> ElasticSection:
        return ElasticSection(
            id=sid,
            name=self._name_edit.text(),
            E=self._e.value(),
            A=self._a.value(),
            Iz=self._iz.value(),
            Iy=self._iy.value(),
            G=self._g.value(),
            J=self._j.value(),
            As2=self._as2.value() or None,
            As3=self._as3.value() or None,
            unit_weight=self._unit_weight.value(),
            shape=self._shape,
        )


class FiberSectionSummaryForm(SectionFormBase):
    """Read-only overview of a :class:`FiberSection`.

    Fiber sections are authored via the dedicated visual editor
    (``FiberSectionEditor``), not inline in the library. Clicking the
    row in the Section Library just shows a summary here — editing is
    done by double-clicking the list entry (which opens the editor).
    """

    type_label = "Fiber Section"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._name_edit.setEnabled(False)
        self._summary = QLabel("")
        self._summary.setWordWrap(True)
        self._summary.setStyleSheet("color: #555;")
        self._layout.addRow(self._summary)
        self._layout.addRow(
            QLabel(
                "<i>Edit this fiber section from the Section Library list — "
                "Add / Modify uses the visual Fiber Section Editor.</i>"
            )
        )
        self._cached: FiberSection | None = None

    def _populate_specific(self, s: FiberSection) -> None:
        self._cached = s
        n_patches = len(s.patches)
        n_layers = len(s.layers)
        n_fibres = len(s.fibres)
        gj = f"{s.GJ:g}" if s.GJ is not None else "(none)"
        self._summary.setText(
            f"<b>{s.name or 'Fiber Section'}</b><br>"
            f"Patches: {n_patches}<br>"
            f"Layers:  {n_layers}<br>"
            f"Explicit fibres: {n_fibres}<br>"
            f"GJ: {gj}"
        )

    def _read_specific(self, sid: int) -> FiberSection:
        # Round-trip: Apply changes returns the cached section (nothing
        # editable in this summary). Users edit via the Fiber Editor.
        if self._cached is None:
            return FiberSection(id=sid)
        return self._cached.model_copy(update={"id": sid})


class SectionAggregatorSummaryForm(SectionFormBase):
    """Read-only overview of a :class:`SectionAggregator`."""

    type_label = "Section Aggregator"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._name_edit.setEnabled(False)
        self._summary = QLabel("")
        self._summary.setWordWrap(True)
        self._summary.setStyleSheet("color: #555;")
        self._layout.addRow(self._summary)
        self._cached: SectionAggregator | None = None

    def _populate_specific(self, s: SectionAggregator) -> None:
        self._cached = s
        pairings = (
            "<br>".join(f"  mat #{p.material_id} on DOF {p.dof}" for p in s.pairings) or "(none)"
        )
        self._summary.setText(
            f"<b>{s.name or 'Section Aggregator'}</b><br>"
            f"Wraps section: {s.section_id}<br>"
            f"Aggregated pairings:<br>{pairings}"
        )

    def _read_specific(self, sid: int) -> SectionAggregator:
        if self._cached is None:
            raise ValueError("Aggregator has no cached state.")
        return self._cached.model_copy(update={"id": sid})


class ElasticMembranePlateSectionForm(SectionFormBase):
    """The section a ShellMITC4 element takes: E, nu, h and rho."""

    type_label = "Plate Section (shell)"

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._e = _spin(200e9, step=1e9)
        self._nu = _spin(0.3, minimum=-1.0, maximum=0.5, step=0.05)
        self._h = _spin(0.2, minimum=1e-9, step=0.01)
        self._rho = _spin(7850.0, minimum=0.0, step=100.0)
        self._unit_weight = _spin(DEFAULT_UNIT_WEIGHT, minimum=0.0, step=1e3)
        self._unit_weight.setToolTip(
            "Weight per unit volume (force / length³). A load pattern with a self "
            "weight applies gamma * h per unit area; 0 = weightless."
        )
        for label, widget in (
            ("E:", self._e),
            ("Nu:", self._nu),
            ("Thickness h:", self._h),
            ("Density rho:", self._rho),
            ("Unit weight γ:", self._unit_weight),
        ):
            self._layout.addRow(label, widget)
        self._layout.addRow(
            QLabel("<i>The plate carries its own E and thickness; no material reference.</i>")
        )

    def _populate_specific(self, s: ElasticMembranePlateSection) -> None:
        self._e.setValue(s.E)
        self._nu.setValue(s.nu)
        self._h.setValue(s.h)
        self._rho.setValue(s.rho)
        self._unit_weight.setValue(s.unit_weight)

    def _read_specific(self, section_id: int) -> ElasticMembranePlateSection:
        return ElasticMembranePlateSection(
            id=section_id,
            name=self._name_edit.text() or "Plate",
            E=self._e.value(),
            nu=self._nu.value(),
            h=self._h.value(),
            rho=self._rho.value(),
            unit_weight=self._unit_weight.value(),
        )


class NonprismaticSectionForm(SectionFormBase):
    """Tapered section: a table of prismatic start/end sections and lengths.

    Segments are applied from the member's I end to its J end in table order.
    The subdivision count is used when the section is assigned to a member;
    changing it later does not rebuild members that were already subdivided
    (the Section Library refreshes their section properties, not their
    topology).
    """

    type_label = "Nonprismatic Section"
    needs_project = True

    _HEADERS = ("Start section", "End section", "Length type", "Length", "Variation")

    def __init__(self, project: Any = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._project = project
        self._elastic_sections = (
            [s for s in project.sections if isinstance(s, ElasticSection)]
            if project is not None
            else []
        )
        self._subdivisions = QSpinBox()
        self._subdivisions.setRange(12, 200)
        self._subdivisions.setValue(12)
        self._subdivisions.setToolTip(
            "Number of elastic beam-column elements a member is split into when the "
            "section is assigned (minimum 12)."
        )
        self._layout.addRow("Subdivisions:", self._subdivisions)

        table_box = QVBoxLayout()
        self._table = QTableWidget(0, len(self._HEADERS))
        self._table.setHorizontalHeaderLabels(self._HEADERS)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table_box.addWidget(self._table)
        buttons = QWidget()
        button_row = QHBoxLayout(buttons)
        button_row.setContentsMargins(0, 0, 0, 0)
        add = QPushButton("Add segment")
        remove = QPushButton("Remove segment")
        add.clicked.connect(self._on_add_row)
        remove.clicked.connect(self._on_remove_row)
        button_row.addWidget(add)
        button_row.addWidget(remove)
        button_row.addStretch(1)
        table_box.addWidget(buttons)
        self._layout.addRow(table_box)
        self._layout.addRow(
            QLabel(
                "<i>Segments run from end i to end j in table order. "
                "Absolute lengths are member lengths; relative lengths are fractions "
                "of the member. A member is subdivided into the number of pieces above."
            )
        )
        if self._elastic_sections:
            self._add_row(
                start=self._elastic_sections[0].id,
                end=self._elastic_sections[0].id,
                length=1.0,
            )
        else:
            warning = QLabel(
                "<b>Define at least one Elastic Section first:</b> a nonprismatic "
                "section is built from prismatic elastic sections."
            )
            warning.setWordWrap(True)
            self._layout.addRow(warning)

    def _section_combo(self, selected: int | None) -> QComboBox:
        combo = QComboBox()
        for section in self._elastic_sections:
            label = f"#{section.id}  {section.name or '(unnamed)'}"
            combo.addItem(label, section.id)
        if selected is not None:
            index = combo.findData(selected)
            if index >= 0:
                combo.setCurrentIndex(index)
        return combo

    def _length_type_combo(self, value: str) -> QComboBox:
        combo = QComboBox()
        combo.addItem("Absolute", "absolute")
        combo.addItem("Relative (0-1)", "relative")
        index = combo.findData(value)
        combo.setCurrentIndex(max(0, index))
        return combo

    def _variation_combo(self, value: str) -> QComboBox:
        combo = QComboBox()
        for label, key in (
            ("Linear", "linear"),
            ("Parabolic", "parabolic"),
            ("Cubic", "cubic"),
        ):
            combo.addItem(label, key)
        index = combo.findData(value)
        combo.setCurrentIndex(max(0, index))
        return combo

    def _add_row(
        self,
        start: int | None = None,
        end: int | None = None,
        length_type: str = "absolute",
        length: float = 1.0,
        variation: str = "linear",
    ) -> None:
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setCellWidget(row, 0, self._section_combo(start))
        self._table.setCellWidget(row, 1, self._section_combo(end))
        self._table.setCellWidget(row, 2, self._length_type_combo(length_type))
        field = FloatField()
        field.setRange(1e-12, 1e15)
        field.setValue(length)
        self._table.setCellWidget(row, 3, field)
        self._table.setCellWidget(row, 4, self._variation_combo(variation))

    def _on_add_row(self) -> None:
        start = self._elastic_sections[0].id if self._elastic_sections else None
        self._add_row(start=start, end=start)

    def _on_remove_row(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            row = self._table.rowCount() - 1
        if row >= 0:
            self._table.removeRow(row)

    def _populate_specific(self, s: NonprismaticSection) -> None:
        self._subdivisions.setValue(s.subdivisions)
        self._table.setRowCount(0)
        for segment in s.segments:
            self._add_row(
                start=segment.start_section_id,
                end=segment.end_section_id,
                length_type=segment.length_type,
                length=segment.length,
                variation=segment.variation,
            )

    def _read_specific(self, section_id: int) -> NonprismaticSection:
        if self._table.rowCount() == 0:
            raise ValueError("A nonprismatic section needs at least one segment.")
        segments: list[NonprismaticSegment] = []
        for row in range(self._table.rowCount()):
            start_widget = self._table.cellWidget(row, 0)
            end_widget = self._table.cellWidget(row, 1)
            type_widget = self._table.cellWidget(row, 2)
            length_widget = self._table.cellWidget(row, 3)
            variation_widget = self._table.cellWidget(row, 4)
            if not (
                isinstance(start_widget, QComboBox)
                and isinstance(end_widget, QComboBox)
                and isinstance(type_widget, QComboBox)
                and isinstance(variation_widget, QComboBox)
                and isinstance(length_widget, FloatField)
            ):
                raise ValueError(f"Segment {row + 1} is incomplete.")
            start = start_widget.currentData()
            end = end_widget.currentData()
            if start is None or end is None:
                raise ValueError(f"Segment {row + 1} needs a start and an end Elastic Section.")
            length = float(length_widget.value())
            if length <= 0.0:
                raise ValueError(f"Segment {row + 1} needs a positive length.")
            segments.append(
                NonprismaticSegment(
                    start_section_id=int(start),
                    end_section_id=int(end),
                    length_type=type_widget.currentData(),
                    length=length,
                    variation=variation_widget.currentData(),
                )
            )
        return NonprismaticSection(
            id=section_id,
            name=self._name_edit.text(),
            segments=segments,
            subdivisions=int(self._subdivisions.value()),
        )


FORM_REGISTRY: dict[str, type[SectionFormBase]] = {
    "ElasticSection": ElasticSectionForm,
    "NonprismaticSection": NonprismaticSectionForm,
    "FiberSection": FiberSectionSummaryForm,
    "SectionAggregator": SectionAggregatorSummaryForm,
    "ElasticMembranePlateSection": ElasticMembranePlateSectionForm,
}


def _register_shell_forms() -> None:
    from opensees_studio.views.dialogs.shell_section_forms import (
        LayeredShellForm,
        PlateFiberSectionForm,
    )

    FORM_REGISTRY["LayeredShell"] = LayeredShellForm
    FORM_REGISTRY["PlateFiber"] = PlateFiberSectionForm


_register_shell_forms()


def make_form(cls: type[SectionFormBase], project: Any = None) -> SectionFormBase:
    """A new form of ``cls``; the shell forms get ``project`` for their material choices."""
    if getattr(cls, "needs_project", False):
        return cls(project=project)  # type: ignore[call-arg]
    return cls()


def form_for(section: Any, project: Any = None) -> SectionFormBase:
    cls = FORM_REGISTRY.get(section.type)
    if cls is None:
        # Graceful fallback — unknown section types display a minimal
        # placeholder instead of crashing the entire dialog.
        form = SectionFormBase()
        form._layout.addRow(
            QLabel(f"<i>No form registered for section type <b>{section.type}</b> yet.</i>")
        )
        form._section_id = section.id
        form._name_edit.setText(getattr(section, "name", "") or "")
        form._name_edit.setEnabled(False)
        return form
    form = make_form(cls, project)
    form.populate(section)
    return form
