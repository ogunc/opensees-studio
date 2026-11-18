"""Truss wizard: a plane truss from a few numbers.

Three pages: the shape (web pattern, span, panels, depth, chords), the members
(material and the two areas), and where the truss sits. The geometry lives in
:mod:`opensees_studio.core.trusses`; the wizard is fields, a live summary and the
translation of the chord choice into a :class:`~opensees_studio.core.TrussSpec`.

The material page reports :data:`CREATE_DEFAULT` when the project has no
uniaxial material yet. The caller creates the default one inside the same undo
macro as the truss, so cancelling never leaves a material behind.
"""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QShowEvent
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QLabel,
    QSpinBox,
    QWidget,
    QWizard,
    QWizardPage,
)

from opensees_studio.core import DEFAULT_UNIT_WEIGHT, TRUSS_TYPE_LABELS, TrussError, TrussSpec
from opensees_studio.core.help import TOPIC_PROPERTY
from opensees_studio.views.float_field import FloatField
from opensees_studio.views.screen_fit import fit_to_available_screen

#: What the material combo reports when the project has no uniaxial material.
CREATE_DEFAULT = -1

#: (label, pitched?, closed at the supports?)
CHORD_CHOICES: list[tuple[str, bool, bool]] = [
    ("Parallel chords", False, False),
    ("Pitched top chord", True, False),
    ("Triangular (closed at the supports)", True, True),
]

PLANE_CHOICES: list[tuple[str, str]] = [
    ("XZ — front elevation (Z up)", "XZ"),
    ("YZ — side elevation (Z up)", "YZ"),
]


class _CompletablePage(QWizardPage):
    """A page whose Next button follows a callable (see ``frame_wizard``)."""

    complete_check: Callable[[], bool] = staticmethod(lambda: True)

    def isComplete(self) -> bool:
        return self.complete_check()


def _field(
    value: float, *, minimum: float, maximum: float, step: float, suffix: str = ""
) -> FloatField:
    box = FloatField()
    box.setRange(minimum, maximum)
    box.setSingleStep(step)
    box.setValue(value)
    if suffix:
        box.setSuffix(f" {suffix}")
    return box


class TrussWizard(QWizard):
    """Collects a :class:`TrussSpec` (minus the material id)."""

    def __init__(
        self,
        materials: list,  # type: ignore[type-arg]
        *,
        ndm: int,
        ndf: int,
        length_unit: str = "m",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._materials = materials
        self._ndm = ndm
        self._ndf = ndf
        self._unit = length_unit
        self.setWindowTitle("Truss Wizard")
        self.setProperty(TOPIC_PROPERTY, "define.truss")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)

        self._build_geometry_page()
        self._build_members_page()
        self._build_position_page()
        self.setPage(0, self._page_geometry)
        self.setPage(1, self._page_members)
        self.setPage(2, self._page_position)
        self._refresh_summary()

    def showEvent(self, event: QShowEvent) -> None:
        super().showEvent(event)
        if not event.spontaneous():
            fit_to_available_screen(self)

    # ── pages ───────────────────────────────────────────────────────
    def _build_geometry_page(self) -> None:
        page = _CompletablePage()
        page.complete_check = lambda: self._geometry_is_complete()
        page.setTitle("Geometry")
        page.setSubTitle("Web pattern, span, panels and depth.")
        form = QFormLayout(page)

        self._type = QComboBox()
        for label, _ in TRUSS_TYPE_LABELS:
            self._type.addItem(label)
        self._span = _field(12.0, minimum=0.0, maximum=1e6, step=1.0, suffix=self._unit)
        self._panels = QSpinBox()
        self._panels.setRange(2, 100)
        self._panels.setValue(6)
        self._depth = _field(1.5, minimum=0.0, maximum=1e6, step=0.25, suffix=self._unit)
        self._depth.setToolTip("Depth at mid-span (the ridge for a pitched truss).")
        self._chords = QComboBox()
        for label, _, _ in CHORD_CHOICES:
            self._chords.addItem(label)
        self._end_depth = _field(0.5, minimum=0.0, maximum=1e6, step=0.25, suffix=self._unit)
        self._end_depth.setToolTip("Depth at the supports, for a pitched top chord.")

        form.addRow("Type:", self._type)
        form.addRow("Span:", self._span)
        form.addRow("Panels:", self._panels)
        form.addRow("Depth at mid-span:", self._depth)
        form.addRow("Top chord:", self._chords)
        form.addRow("Depth at the supports:", self._end_depth)

        self._geometry_summary = QLabel()
        self._geometry_summary.setWordWrap(True)
        form.addRow(self._geometry_summary)

        for signal in (
            self._span.valueChanged,
            self._panels.valueChanged,
            self._depth.valueChanged,
            self._end_depth.valueChanged,
        ):
            signal.connect(self._refresh_summary)
        self._type.currentIndexChanged.connect(self._refresh_summary)
        self._chords.currentIndexChanged.connect(self._refresh_summary)
        self._page_geometry = page

    def _build_members_page(self) -> None:
        page = QWizardPage()
        page.setTitle("Members")
        page.setSubTitle("One material, one area for the chords and one for the web.")
        form = QFormLayout(page)

        self._material = QComboBox()
        for material in self._materials:
            self._material.addItem(
                f"#{material.id}  {material.name or material.type}", userData=material.id
            )
        if not self._materials:
            self._material.addItem("Default steel (will be created)", userData=CREATE_DEFAULT)
        self._chord_area = _field(
            0.004, minimum=1e-12, maximum=1e6, step=0.001, suffix=f"{self._unit}²"
        )
        self._web_area = _field(
            0.002, minimum=1e-12, maximum=1e6, step=0.001, suffix=f"{self._unit}²"
        )
        form.addRow("Material:", self._material)
        form.addRow("Chord area:", self._chord_area)
        form.addRow("Web area:", self._web_area)
        self._unit_weight = _field(DEFAULT_UNIT_WEIGHT, minimum=0.0, maximum=1e12, step=1e3)
        self._unit_weight.setToolTip(
            "Weight per unit volume of the bars (force / length³), for the self "
            "weight of the DEAD case. Steel by default; 0 = weightless."
        )
        form.addRow("Unit weight γ:", self._unit_weight)
        if not self._materials:
            form.addRow(
                QLabel(
                    "<i>This project has no uniaxial material yet: a default elastic steel "
                    "(E = 200 GPa) will be created with the truss, as one undoable step.</i>"
                )
            )
        self._page_members = page

    def _build_position_page(self) -> None:
        page = QWizardPage()
        page.setTitle("Supports and position")
        page.setSubTitle("Pinned at the left end, on a roller at the right end.")
        form = QFormLayout(page)

        self._plane = QComboBox()
        for label, code in PLANE_CHOICES:
            self._plane.addItem(label, userData=code)
        if self._ndm == 2:
            self._plane.setCurrentIndex(self._plane.findData("XZ"))
            self._plane.setEnabled(False)
            self._plane.setToolTip("A 2D project builds its trusses in the XZ plane.")

        self._origin = [
            _field(0.0, minimum=-1e9, maximum=1e9, step=1.0, suffix=self._unit) for _ in range(3)
        ]
        origin_row = QWidget()
        origin_layout = QFormLayout(origin_row)
        origin_layout.setContentsMargins(0, 0, 0, 0)
        for axis, box in zip("XYZ", self._origin, strict=True):
            origin_layout.addRow(f"{axis}₀:", box)
        if self._ndm == 2:
            # A 2D model lives in the plane y = 0 (core.plane).
            self._origin[1].setEnabled(False)

        self._restrain_out_of_plane = QCheckBox(
            "Restrain the out-of-plane translation (a truss analysed on its own)"
        )
        self._restrain_out_of_plane.setChecked(True)
        if self._ndm == 2:
            self._restrain_out_of_plane.setEnabled(False)
            self._restrain_out_of_plane.setToolTip("A 2D project has no out-of-plane direction.")

        form.addRow("Plane:", self._plane)
        form.addRow("Origin:", origin_row)
        form.addRow(self._restrain_out_of_plane)
        if self._ndf in (3, 6) and not (self._ndm == 3 and self._ndf == 3):
            form.addRow(
                QLabel(
                    "<i>This is a frame model: the rotations of every truss node are "
                    "restrained, since a truss bar gives them no stiffness.</i>"
                )
            )
        self._page_position = page

    # ── live summary ────────────────────────────────────────────────
    def _refresh_summary(self) -> None:
        _, pitched, closed = CHORD_CHOICES[self._chords.currentIndex()]
        self._end_depth.setEnabled(pitched and not closed)
        try:
            spec = self._spec(material_id=1)
        except TrussError as exc:
            self._geometry_summary.setText(f"<b>Check the numbers:</b> {exc}")
            return
        self._geometry_summary.setText(
            f"Panels of <b>{spec.panel:g} {self._unit}</b>, depth/span "
            f"<b>1/{spec.span / spec.depth:.3g}</b>."
        )

    def _geometry_is_complete(self) -> bool:
        try:
            self._spec(material_id=1)
        except TrussError:
            return False
        return True

    # ── results ─────────────────────────────────────────────────────
    def material_choice(self) -> int | None:
        """The chosen material id; ``None`` means "create the default one"."""
        material = self._material.currentData()
        return None if material in (None, CREATE_DEFAULT) else int(material)

    def _spec(self, *, material_id: int) -> TrussSpec:
        _, pitched, closed = CHORD_CHOICES[self._chords.currentIndex()]
        end_depth = None
        if pitched:
            end_depth = 0.0 if closed else self._end_depth.value()
        return TrussSpec(
            span=self._span.value(),
            depth=self._depth.value(),
            n_panels=self._panels.value(),
            material_id=material_id,
            chord_area=self._chord_area.value(),
            web_area=self._web_area.value(),
            unit_weight=self._unit_weight.value(),
            truss_type=TRUSS_TYPE_LABELS[self._type.currentIndex()][1],
            end_depth=end_depth,
            plane=self._plane.currentData() or "XZ",
            origin=tuple(box.value() for box in self._origin),  # type: ignore[arg-type]
            restrain_out_of_plane=self._restrain_out_of_plane.isChecked() or self._ndm == 2,
        )

    def spec(self, *, material_id: int) -> TrussSpec:
        """The truss to build, with the material id the caller resolved.

        Raises:
            TrussError: if the fields do not describe a truss.
        """
        return self._spec(material_id=material_id)
