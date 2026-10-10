"""Portal frame wizard: a 2D frame from a few numbers.

Three pages, in the order the questions come up when someone sketches a
warehouse portal by hand: how big it is, what the members are made of, and how
it sits on the ground. The geometry itself lives in
:mod:`opensees_studio.core.frames`, so the wizard is only fields, a live
summary and the translation of the roof choice into a
:class:`~opensees_studio.core.frames.PortalFrameSpec`.

The section page reports :data:`CREATE_DEFAULT` when the project has no frame
section yet. The caller — not the wizard — creates it, inside the same undo
macro as the frame, so cancelling the wizard never leaves a section behind.
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

from opensees_studio.core import (
    PortalFrameError,
    PortalFrameSpec,
    RoofType,
    SupportCondition,
)
from opensees_studio.core.help import TOPIC_PROPERTY
from opensees_studio.views.float_field import FloatField
from opensees_studio.views.screen_fit import fit_to_available_screen

#: What the section combos report when the project has no frame section yet.
CREATE_DEFAULT = -1

#: (label, roof type, whether the slope applies) — "flat" is a mono-pitch at 0 %.
ROOF_CHOICES: list[tuple[str, RoofType, bool]] = [
    ("Two slopes (gable)", RoofType.GABLE, True),
    ("One slope (mono-pitch)", RoofType.MONO_PITCH, True),
    ("Flat (no slope)", RoofType.MONO_PITCH, False),
]

PLANE_CHOICES: list[tuple[str, str]] = [
    ("XZ — front elevation (Z up)", "XZ"),
    ("YZ — side elevation (Z up)", "YZ"),
    ("XY — plan (Z out of plane)", "XY"),
]

SUPPORT_CHOICES: list[tuple[str, SupportCondition]] = [
    ("Fixed (rotation restrained)", SupportCondition.FIXED),
    ("Pinned (rotation free)", SupportCondition.PINNED),
]


class _CompletablePage(QWizardPage):
    """A page whose Next button follows a callable the builder installs.

    Qt calls the virtual ``isComplete`` through the C++ vtable, so the check has
    to live on the class, not on the instance.
    """

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


class FrameWizard(QWizard):
    """Collects a :class:`PortalFrameSpec` (minus the section ids)."""

    def __init__(
        self,
        sections: list,  # type: ignore[type-arg]
        *,
        ndm: int,
        ndf: int,
        length_unit: str = "m",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._sections = sections
        self._ndm = ndm
        self._ndf = ndf
        self._unit = length_unit
        self.setWindowTitle("Portal Frame Wizard")
        self.setProperty(TOPIC_PROPERTY, "define.portal_frame")
        self.setWizardStyle(QWizard.WizardStyle.ModernStyle)
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)

        self._build_geometry_page()
        self._build_sections_page()
        self._build_support_page()
        self.setPage(0, self._page_geometry)
        self.setPage(1, self._page_sections)
        self.setPage(2, self._page_support)
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
        page.setSubTitle("Bay sizes, eave height and roof profile.")
        form = QFormLayout(page)

        self._n_bays = QSpinBox()
        self._n_bays.setRange(1, 20)
        self._n_bays.setValue(1)
        self._n_bays.setToolTip("Number of bays between columns (multi-span frames).")

        # Zero is allowed in the field so the summary can say why it is refused;
        # the spec, not a silently clamped minimum, does the rejecting.
        self._bay_width = _field(6.0, minimum=0.0, maximum=1e6, step=0.5, suffix=self._unit)
        self._eave_height = _field(4.0, minimum=0.0, maximum=1e6, step=0.5, suffix=self._unit)
        self._roof = QComboBox()
        for label, _, _ in ROOF_CHOICES:
            self._roof.addItem(label)
        self._slope = _field(10.0, minimum=0.0, maximum=99.0, step=1.0, suffix="%")

        form.addRow("Number of bays:", self._n_bays)
        form.addRow("Bay width:", self._bay_width)
        form.addRow("Eave height:", self._eave_height)
        form.addRow("Roof:", self._roof)
        form.addRow("Slope:", self._slope)

        self._geometry_summary = QLabel()
        self._geometry_summary.setWordWrap(True)
        form.addRow(self._geometry_summary)

        for signal in (
            self._n_bays.valueChanged,
            self._bay_width.valueChanged,
            self._eave_height.valueChanged,
            self._slope.valueChanged,
        ):
            signal.connect(self._refresh_summary)
        self._roof.currentIndexChanged.connect(self._refresh_summary)
        self._page_geometry = page

    def _build_sections_page(self) -> None:
        page = QWizardPage()
        page.setTitle("Sections")
        page.setSubTitle("One section for the columns, one for the rafters.")
        form = QFormLayout(page)

        self._column_section = QComboBox()
        self._rafter_section = QComboBox()
        for combo in (self._column_section, self._rafter_section):
            for section in self._sections:
                combo.addItem(f"#{section.id}  {section.name or '(unnamed)'}", userData=section.id)
            if not self._sections:
                combo.addItem("Default elastic section (will be created)", userData=CREATE_DEFAULT)
        form.addRow("Columns:", self._column_section)
        form.addRow("Rafters and beams:", self._rafter_section)
        if not self._sections:
            form.addRow(
                QLabel(
                    "<i>This project has no sections yet: a default elastic section "
                    "(200 GPa, A = 0.01 m², I = 8.33e-6 m⁴) will be created with the frame, "
                    "as one undoable step.</i>"
                )
            )
        self._page_sections = page

    def _build_support_page(self) -> None:
        page = QWizardPage()
        page.setTitle("Supports and position")
        page.setSubTitle("How the columns reach the ground, and where the frame starts.")
        form = QFormLayout(page)

        self._support = QComboBox()
        for label, _ in SUPPORT_CHOICES:
            self._support.addItem(label)

        self._plane = QComboBox()
        for label, code in PLANE_CHOICES:
            self._plane.addItem(label, userData=code)
        if self._ndm == 2:
            # A 2D model has no third axis: XY (X span, Y up) is the only plane.
            index = self._plane.findData("XY")
            self._plane.setCurrentIndex(index)
            self._plane.setEnabled(False)
            self._plane.setToolTip("A 2D project builds its frames in the XY plane.")

        self._origin = [
            _field(0.0, minimum=-1e9, maximum=1e9, step=1.0, suffix=self._unit) for _ in range(3)
        ]
        origin_row = QWidget()
        origin_layout = QFormLayout(origin_row)
        origin_layout.setContentsMargins(0, 0, 0, 0)
        for axis, box in zip("XYZ", self._origin, strict=True):
            origin_layout.addRow(f"{axis}₀:", box)

        self._restrain_out_of_plane = QCheckBox(
            "Restrain the out-of-plane degrees of freedom (a true 2D frame)"
        )
        self._restrain_out_of_plane.setChecked(True)
        self._restrain_out_of_plane.setToolTip(
            "Leave this on to analyse the frame on its own.\n"
            "Turn it off when the frame will be copied along the ridge direction and "
            "tied to its copies, because a restrained node cannot move out of plane."
        )
        if self._ndf != 6:
            self._restrain_out_of_plane.setChecked(False)
            self._restrain_out_of_plane.setEnabled(False)
            self._restrain_out_of_plane.setToolTip(
                "A 2D project has no out-of-plane degrees of freedom."
            )

        form.addRow("Column bases:", self._support)
        form.addRow("Plane:", self._plane)
        form.addRow("Origin:", origin_row)
        form.addRow(self._restrain_out_of_plane)

        self._support_summary = QLabel()
        self._support_summary.setWordWrap(True)
        form.addRow(self._support_summary)
        self._page_support = page

    # ── live summary ────────────────────────────────────────────────
    def _refresh_summary(self) -> None:
        try:
            spec = self._spec(column_section_id=1, rafter_section_id=1)
        except PortalFrameError as exc:
            self._geometry_summary.setText(f"<b>Check the numbers:</b> {exc}")
            return
        self._geometry_summary.setText(
            f"Total width <b>{spec.span:g} {self._unit}</b>, "
            f"ridge at <b>{spec.ridge_height:g} {self._unit}</b> "
            f"({spec.n_bays + 1} columns, "
            f"{spec.n_bays + int(spec.has_ridge_node)} rafters)."
        )
        if hasattr(self, "_support_summary"):
            self._support_summary.setText(
                f"The frame will have <b>{len(spec.column_heights()) * 2 + int(spec.has_ridge_node)}"
                f"</b> nodes and create <b>{spec.n_bays * 2 + 1 + int(spec.has_ridge_node)}</b> "
                "beam-column elements."
            )

    def _geometry_is_complete(self) -> bool:
        """Whether the geometry page holds numbers that describe a frame."""
        try:
            self._spec(column_section_id=1, rafter_section_id=1)
        except PortalFrameError:
            return False
        return True

    # ── results ─────────────────────────────────────────────────────
    def section_choice(self) -> tuple[int | None, int | None]:
        """The chosen section ids; ``None`` means "create the default one"."""
        column = self._column_section.currentData()
        rafter = self._rafter_section.currentData()
        return (
            None if column in (None, CREATE_DEFAULT) else int(column),
            None if rafter in (None, CREATE_DEFAULT) else int(rafter),
        )

    def _spec(self, *, column_section_id: int, rafter_section_id: int) -> PortalFrameSpec:
        _, roof, has_slope = ROOF_CHOICES[self._roof.currentIndex()]
        slope = self._slope.value() / 100.0 if has_slope else 0.0
        return PortalFrameSpec(
            bay_width=self._bay_width.value(),
            eave_height=self._eave_height.value(),
            column_section_id=column_section_id,
            rafter_section_id=rafter_section_id,
            roof=roof,
            slope=slope,
            n_bays=self._n_bays.value(),
            support=SUPPORT_CHOICES[self._support.currentIndex()][1],
            plane=self._plane.currentData() or "XZ",
            origin=tuple(box.value() for box in self._origin),  # type: ignore[arg-type]
            restrain_out_of_plane=self._restrain_out_of_plane.isChecked(),
        )

    def spec(self, *, column_section_id: int, rafter_section_id: int) -> PortalFrameSpec:
        """The frame to build, with the section ids the caller resolved.

        Raises:
            PortalFrameError: if the fields do not describe a frame.
        """
        return self._spec(
            column_section_id=column_section_id,
            rafter_section_id=rafter_section_id,
        )
