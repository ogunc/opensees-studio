"""Assign → Frame dialogs: releases, end offsets, insertion point, property modifiers, trapezoidal load.

Each dialog edits one of the frame options of
:mod:`opensees_studio.core.geometry.frame_options` (or builds a
:class:`TrapezoidalElementLoad`). It starts from the value the selected
members share, or the default when they differ, and validates through the
model on OK, so an invalid combination (a spring on a fixed action, torsion
released at both ends) is reported before anything changes.
"""

from __future__ import annotations

from pydantic import ValidationError
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QMessageBox,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core import (
    CARDINAL_POINT_NAMES,
    RELEASE_DOFS,
    EndRelease,
    FrameEndOffsets,
    FrameInsertion,
    FrameModifiers,
    FrameReleases,
)
from opensees_studio.views.float_field import FloatField
from opensees_studio.views.screen_fit import FittedDialog

_RELEASE_LABELS = {
    "T": "Torsion (T)",
    "M2": "Moment 2-2 (M2, about local y)",
    "M3": "Moment 3-3 (M3, about local z)",
}


def _field(value: float, lo: float = -1e12, hi: float = 1e12, tip: str = "") -> FloatField:
    field = FloatField()
    field.setRange(lo, hi)
    field.setValue(value)
    if tip:
        field.setToolTip(tip)
    return field


def _validation_message(exc: ValidationError) -> str:
    return "\n".join(str(err.get("msg", "")).removeprefix("Value error, ") for err in exc.errors())


class _AssignDialog(FittedDialog):
    """Header, body, OK/Cancel; ``_build`` returns the model or raises ``ValidationError``."""

    def __init__(self, title: str, n_selected: int, note: str, parent: QWidget | None) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self._layout = QVBoxLayout(self)
        self._layout.addWidget(QLabel(f"Apply to <b>{n_selected}</b> selected frame element(s)."))
        self._note = note

    def _finish(self) -> None:
        if self._note:
            note = QLabel(f"<i>{self._note}</i>")
            note.setWordWrap(True)
            self._layout.addWidget(note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        self._layout.addWidget(buttons)

    def _build(self) -> object:  # pragma: no cover - overridden
        raise NotImplementedError

    def _on_accept(self) -> None:
        try:
            self._build()
        except ValidationError as exc:
            QMessageBox.warning(self, self.windowTitle(), _validation_message(exc))
            return
        self.accept()


class FrameReleasesDialog(_AssignDialog):
    """Assign → Frame → Releases/Partial Fixity: per end, per action, with springs."""

    def __init__(
        self,
        n_selected: int,
        ndm: int,
        current: FrameReleases | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            "Assign Frame Releases / Partial Fixity",
            n_selected,
            "A released action carries no force at that end of the member. A partial-fixity "
            "spring (moment per radian) makes the release elastic; leave it 0 for a full "
            "release. A 2D frame releases M3 only.",
            parent,
        )
        current = current or FrameReleases()
        grid = QGridLayout()
        for col, text in enumerate(("", "Release i", "Spring i", "Release j", "Spring j")):
            grid.addWidget(QLabel(f"<b>{text}</b>"), 0, col)
        self._release: dict[tuple[str, str], QCheckBox] = {}
        self._spring: dict[tuple[str, str], FloatField] = {}
        for row, dof in enumerate(RELEASE_DOFS, start=1):
            grid.addWidget(QLabel(_RELEASE_LABELS[dof]), row, 0)
            for k, end in enumerate(("i", "j")):
                release = current.end(end)
                box = QCheckBox()
                box.setChecked(dof in release.released)
                spring = _field(release.spring(dof), 0.0, 1e15, "Partial-fixity stiffness")
                box.toggled.connect(spring.setEnabled)
                spring.setEnabled(box.isChecked())
                if ndm == 2 and dof != "M3":
                    box.setEnabled(False)
                    spring.setEnabled(False)
                self._release[(end, dof)] = box
                self._spring[(end, dof)] = spring
                grid.addWidget(box, row, 1 + 2 * k)
                grid.addWidget(spring, row, 2 + 2 * k)
        self._layout.addLayout(grid)
        self._finish()

    def set_release(self, end: str, dof: str, released: bool, spring: float = 0.0) -> None:
        """Set one cell (tests and scripted use)."""
        self._release[(end, dof)].setChecked(released)
        self._spring[(end, dof)].setValue(spring)

    def _build(self) -> FrameReleases:
        ends = {}
        for end in ("i", "j"):
            released = tuple(d for d in RELEASE_DOFS if self._release[(end, d)].isChecked())
            springs = {
                d: self._spring[(end, d)].value()
                for d in released
                if self._spring[(end, d)].value() > 0.0
            }
            ends[end] = EndRelease(released=released, springs=springs)  # type: ignore[arg-type]
        return FrameReleases(**ends)

    def releases(self) -> FrameReleases:
        return self._build()


class FrameEndOffsetsDialog(_AssignDialog):
    """Assign → Frame → End (Length) Offsets: rigid zones at both ends."""

    def __init__(
        self,
        n_selected: int,
        current: FrameEndOffsets | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            "Assign Frame End Offsets",
            n_selected,
            "Offset lengths are measured along the member from each joint. The rigid-zone "
            "factor is the part of them that is rigid; the member's end forces are reported "
            "where its flexible part starts. Loads on a rigid zone go straight to the joint.",
            parent,
        )
        current = current or FrameEndOffsets()
        self._auto = QCheckBox("Automatic from connectivity")
        self._auto.setToolTip(
            "Take each end's offset from the largest half-extent, along the member, of the "
            "other frame members that meet it at that joint (the lengths below are ignored). "
            "Computed once, when you press OK."
        )
        self._layout.addWidget(self._auto)
        form = QFormLayout()
        self._length_i = _field(current.length_i, 0.0, 1e12, "Offset length at end i")
        self._length_j = _field(current.length_j, 0.0, 1e12, "Offset length at end j")
        self._factor = _field(current.rigid_factor, 0.0, 1.0, "0 = flexible, 1 = fully rigid")
        form.addRow("End-I length:", self._length_i)
        form.addRow("End-J length:", self._length_j)
        form.addRow("Rigid-zone factor:", self._factor)
        self._auto.toggled.connect(lambda on: self._length_i.setEnabled(not on))
        self._auto.toggled.connect(lambda on: self._length_j.setEnabled(not on))
        self._layout.addLayout(form)
        self._finish()

    def _build(self) -> FrameEndOffsets:
        return FrameEndOffsets(
            length_i=self._length_i.value(),
            length_j=self._length_j.value(),
            rigid_factor=self._factor.value(),
        )

    def offsets(self) -> FrameEndOffsets:
        return self._build()

    @property
    def automatic(self) -> bool:
        """The lengths come from the connectivity, not from the fields."""
        return self._auto.isChecked()

    def set_automatic(self, on: bool) -> None:
        self._auto.setChecked(on)


class FrameInsertionDialog(_AssignDialog):
    """Assign → Frame → Insertion Point: cardinal point plus a joint offset."""

    def __init__(
        self,
        n_selected: int,
        ndm: int,
        current: FrameInsertion | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            "Assign Frame Insertion Point",
            n_selected,
            "The cardinal point is the point of the section that sits on the line between the "
            "joints (bottom/top along local 2, left/right along local 3, looking from end i to "
            "end j). It is a rigid offset at both ends: the flexible length does not change.",
            parent,
        )
        current = current or FrameInsertion()
        form = QFormLayout()
        self._cardinal = QComboBox()
        for point, name in CARDINAL_POINT_NAMES.items():
            self._cardinal.addItem(f"{point} ({name})", point)
        self._cardinal.setCurrentIndex(self._cardinal.findData(current.cardinal_point))
        self._offset_2 = _field(current.offset_2, tip="Extra offset along local 2 (y)")
        self._offset_3 = _field(current.offset_3, tip="Extra offset along local 3 (z)")
        self._offset_3.setEnabled(ndm == 3)
        form.addRow("Cardinal point:", self._cardinal)
        form.addRow("Offset along 2:", self._offset_2)
        form.addRow("Offset along 3:", self._offset_3)
        self._layout.addLayout(form)
        self._finish()

    def set_cardinal_point(self, point: int) -> None:
        self._cardinal.setCurrentIndex(self._cardinal.findData(point))

    def _build(self) -> FrameInsertion:
        return FrameInsertion(
            cardinal_point=self._cardinal.currentData(),
            offset_2=self._offset_2.value(),
            offset_3=self._offset_3.value(),
        )

    def insertion(self) -> FrameInsertion:
        return self._build()


_MODIFIER_FIELDS = (
    ("area", "Cross-section (axial) area"),
    ("as2", "Shear area in 2 direction"),
    ("as3", "Shear area in 3 direction"),
    ("torsion", "Torsional constant"),
    ("i22", "Moment of inertia about 2 axis"),
    ("i33", "Moment of inertia about 3 axis"),
    ("mass", "Mass"),
    ("weight", "Weight"),
)


class FrameModifiersDialog(_AssignDialog):
    """Assign → Frame → Property Modifiers: multipliers on the section properties."""

    def __init__(
        self,
        n_selected: int,
        current: FrameModifiers | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(
            "Assign Frame Property Modifiers",
            n_selected,
            "Multipliers on the elastic section's properties (e.g. 0.35 on I33 for a cracked "
            "beam). A fibre section takes only the mass and weight modifiers. A shear-area "
            "multiplier of 0 turns shear deformation off for the member; a positive value "
            "keeps the Timoshenko route when the section defines shear areas.",
            parent,
        )
        current = current or FrameModifiers()
        form = QFormLayout()
        self._fields: dict[str, FloatField] = {}
        for name, label in _MODIFIER_FIELDS:
            field = _field(getattr(current, name), 0.0, 1e6)
            self._fields[name] = field
            form.addRow(f"{label}:", field)
        self._layout.addLayout(form)
        self._finish()

    def set_value(self, name: str, value: float) -> None:
        self._fields[name].setValue(value)

    def _build(self) -> FrameModifiers:
        return FrameModifiers(**{name: field.value() for name, field in self._fields.items()})

    def modifiers(self) -> FrameModifiers:
        return self._build()


class TrapezoidalLoadDialog(_AssignDialog):
    """Assign → Frame → Trapezoidal Load: a linearly varying load over part of each member."""

    def __init__(self, n_selected: int, ndm: int, parent: QWidget | None = None) -> None:
        super().__init__(
            "Assign Frame Trapezoidal Load",
            n_selected,
            "Load per unit length in the element's local axes, varying linearly from the start "
            "to the end distance (fractions of the joint-to-joint length, from end i). Equal "
            "start and end values give a uniform load over part of the span.",
            parent,
        )
        group = QGroupBox("Load")
        grid = QGridLayout(group)
        grid.addWidget(QLabel("<b>Start</b>"), 0, 1)
        grid.addWidget(QLabel("<b>End</b>"), 0, 2)
        self._w: dict[tuple[str, str], FloatField] = {}
        for row, comp in enumerate(("wx", "wy", "wz"), start=1):
            grid.addWidget(QLabel(f"{comp}:"), row, 0)
            for col, at in enumerate(("start", "end"), start=1):
                field = _field(0.0)
                field.setEnabled(not (ndm == 2 and comp == "wz"))
                self._w[(comp, at)] = field
                grid.addWidget(field, row, col)
        grid.addWidget(QLabel("x/L:"), 4, 0)
        self._x_start = _field(0.0, 0.0, 1.0, "Relative start distance from end i")
        self._x_end = _field(1.0, 0.0, 1.0, "Relative end distance from end i")
        grid.addWidget(self._x_start, 4, 1)
        grid.addWidget(self._x_end, 4, 2)
        self._layout.addWidget(group)
        self._finish()

    def set_load(self, comp: str, start: float, end: float) -> None:
        self._w[(comp, "start")].setValue(start)
        self._w[(comp, "end")].setValue(end)

    def set_span(self, x_start: float, x_end: float) -> None:
        self._x_start.setValue(x_start)
        self._x_end.setValue(x_end)

    def values(self) -> dict[str, float]:
        """Keyword arguments of a ``TrapezoidalElementLoad`` (without ``element_id``)."""
        out = {f"{comp}_{at}": field.value() for (comp, at), field in self._w.items()}
        out["x_start"] = self._x_start.value()
        out["x_end"] = self._x_end.value()
        return out

    def _build(self) -> object:
        from opensees_studio.core import TrapezoidalElementLoad

        return TrapezoidalElementLoad(element_id=1, **self.values())

    def _on_accept(self) -> None:
        if all(v == 0.0 for k, v in self.values().items() if k.startswith("w")):
            QMessageBox.warning(self, self.windowTitle(), "Enter a non-zero load.")
            return
        super()._on_accept()
