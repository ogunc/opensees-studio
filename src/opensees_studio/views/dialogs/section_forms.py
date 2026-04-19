"""Section parameter forms.

For Phase 5, only :class:`ElasticSection` has a real form. The fiber
section visual editor is deferred to Phase 5b — a flat fibre list
isn't usefully editable in a tab.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QWidget,
)

from opensees_studio.core import (
    ElasticSection,
    FiberSection,
    SectionAggregator,
)


def _spin(default: float = 0.0, *, decimals: int = 8,
          minimum: float = 1e-12, maximum: float = 1e15,
          step: float = 1.0) -> QDoubleSpinBox:
    sb = QDoubleSpinBox()
    sb.setRange(minimum, maximum)
    sb.setDecimals(decimals)
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
        for label, w in (("E:", self._e), ("A:", self._a),
                         ("Iz:", self._iz), ("Iy:", self._iy),
                         ("G:", self._g), ("J:", self._j)):
            self._layout.addRow(label, w)
        self._layout.addRow(QLabel("<i>Iy, G, J required for 3D models.</i>"))

    def _populate_specific(self, s: ElasticSection) -> None:
        self._e.setValue(s.E); self._a.setValue(s.A); self._iz.setValue(s.Iz)
        if s.Iy is not None:
            self._iy.setValue(s.Iy)
        if s.G is not None:
            self._g.setValue(s.G)
        if s.J is not None:
            self._j.setValue(s.J)

    def _read_specific(self, sid: int) -> ElasticSection:
        return ElasticSection(
            id=sid, name=self._name_edit.text(),
            E=self._e.value(), A=self._a.value(),
            Iz=self._iz.value(), Iy=self._iy.value(),
            G=self._g.value(), J=self._j.value(),
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
        self._layout.addRow(QLabel(
            "<i>Edit this fiber section from the Section Library list — "
            "Add / Modify uses the visual Fiber Section Editor.</i>"
        ))
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
        pairings = "<br>".join(
            f"  mat #{p.material_id} on DOF {p.dof}" for p in s.pairings
        ) or "(none)"
        self._summary.setText(
            f"<b>{s.name or 'Section Aggregator'}</b><br>"
            f"Wraps section: {s.section_id}<br>"
            f"Aggregated pairings:<br>{pairings}"
        )

    def _read_specific(self, sid: int) -> SectionAggregator:
        if self._cached is None:
            raise ValueError("Aggregator has no cached state.")
        return self._cached.model_copy(update={"id": sid})


FORM_REGISTRY: dict[str, type[SectionFormBase]] = {
    "ElasticSection": ElasticSectionForm,
    "FiberSection": FiberSectionSummaryForm,
    "SectionAggregator": SectionAggregatorSummaryForm,
}


def form_for(section: Any) -> SectionFormBase:
    cls = FORM_REGISTRY.get(section.type)
    if cls is None:
        # Graceful fallback — unknown section types display a minimal
        # placeholder instead of crashing the entire dialog.
        form = SectionFormBase()
        form._layout.addRow(QLabel(
            f"<i>No form registered for section type "
            f"<b>{section.type}</b> yet.</i>"
        ))
        form._section_id = section.id
        form._name_edit.setText(getattr(section, "name", "") or "")
        form._name_edit.setEnabled(False)
        return form
    form = cls()
    form.populate(section)
    return form
