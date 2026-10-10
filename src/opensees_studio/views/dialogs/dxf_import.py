"""Import a bar layout from a DXF drawing.

The dialog's job is to make the three decisions the file cannot make for the
user visible before anything enters the model: which layers are structure, what
a drawing unit is worth, and which plane the (two-dimensional) drawing is. The
summary recomputes on every change, so "4 members" is read before OK, not after.

The drawing itself is read once; changing a layer or the scale only re-runs the
conversion.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core import ElasticMembranePlateSection, Project
from opensees_studio.core.help import TOPIC_PROPERTY
from opensees_studio.core.units import labels_for
from opensees_studio.services.dxf_import import (
    PLANE_CHOICES,
    DxfDrawing,
    DxfImportError,
    bars_from_drawing,
    merge_tolerance,
    read_drawing,
    select_layers,
    unit_scale,
)
from opensees_studio.views.dialogs.frame_wizard import CREATE_DEFAULT
from opensees_studio.views.float_field import FloatField
from opensees_studio.views.screen_fit import FittedDialog, MessageArea


class DxfImportDialog(FittedDialog):
    """Pick a drawing, say how to read it, and see what will be imported."""

    def __init__(
        self,
        project: Project,
        *,
        sections: list,  # type: ignore[type-arg]
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._project = project
        self._sections = sections
        self._drawing: DxfDrawing | None = None
        self._path: Path | None = None
        self.setWindowTitle("Import DXF")
        self.setProperty(TOPIC_PROPERTY, "file.import_dxf")
        self._build_ui()
        self._refresh()

    # ── ui ──────────────────────────────────────────────────────────
    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "Straight bars are read from <b>LINE</b> and <b>POLYLINE</b> entities. "
                "<i>Endpoints that land on the same point become one node, and everything "
                "else in the drawing — circles, text, hatches — is reported, never guessed at.</i>"
            )
        )

        file_row = QWidget()
        file_layout = QHBoxLayout(file_row)
        file_layout.setContentsMargins(0, 0, 0, 0)
        self._file = QLineEdit()
        self._file.setReadOnly(True)
        self._file.setPlaceholderText("No file chosen")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._on_browse)
        file_layout.addWidget(self._file)
        file_layout.addWidget(browse)
        layout.addWidget(file_row)

        form = QFormLayout()
        self._layers = QListWidget()
        self._layers.setMinimumHeight(90)
        self._layers.itemChanged.connect(self._refresh)
        form.addRow("Layers:", self._layers)

        self._units = QLabel()
        self._units.setWordWrap(True)
        form.addRow("Units:", self._units)

        self._scale = FloatField()
        self._scale.setRange(1e-12, 1e12)
        self._scale.setValue(1.0)
        self._scale.setToolTip(
            "Factor taking a length in the drawing to the project's own unit. "
            "Filled in from the file's own $INSUNITS; change it if the file lies."
        )
        self._scale.valueChanged.connect(self._refresh)
        form.addRow("Scale:", self._scale)

        self._plane = QComboBox()
        for label, code in PLANE_CHOICES:
            self._plane.addItem(label, userData=code)
        # Drawings of structures are elevations far more often than plans, and
        # XZ is the plane the rest of the application draws frames in (Z up).
        self._plane.setCurrentIndex(self._plane.findData("XY" if self._project.ndm == 2 else "XZ"))
        if self._project.ndm == 2:
            # A 2D model has one plane; anything else would collapse the drawing.
            self._plane.setEnabled(False)
            self._plane.setToolTip("A 2D project reads the drawing as its XY plane.")
        self._plane.currentIndexChanged.connect(self._refresh)
        form.addRow("Read the drawing as:", self._plane)

        self._level = FloatField()
        self._level.setRange(-1e9, 1e9)
        self._level.setSingleStep(1.0)
        self._level.valueChanged.connect(self._refresh)
        form.addRow("Plane level:", self._level)

        self._origin = [FloatField() for _ in range(3)]
        origin_row = QWidget()
        origin_layout = QHBoxLayout(origin_row)
        origin_layout.setContentsMargins(0, 0, 0, 0)
        for axis, box in zip("XYZ", self._origin, strict=True):
            box.setRange(-1e9, 1e9)
            box.setSingleStep(1.0)
            box.valueChanged.connect(self._refresh)
            origin_layout.addWidget(QLabel(f"{axis}₀:"))
            origin_layout.addWidget(box)
        form.addRow("Origin:", origin_row)

        self._tolerance = FloatField()
        self._tolerance.setRange(0.0, 1e9)
        self._tolerance.setToolTip("Endpoints closer than this become the same node.")
        self._tolerance.valueChanged.connect(self._refresh)
        form.addRow("Merge tolerance:", self._tolerance)

        self._section = QComboBox()
        for section in self._sections:
            self._section.addItem(f"#{section.id}  {section.name or '(unnamed)'}", section.id)
        if not self._sections:
            self._section.addItem("Default elastic section (will be created)", CREATE_DEFAULT)
        form.addRow("Member section:", self._section)
        layout.addLayout(form)

        self._summary = MessageArea()
        layout.addWidget(self._summary)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._ok.setText("Import")

    # ── the file ────────────────────────────────────────────────────
    def _on_browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import DXF", "", "DXF drawings (*.dxf);;All files (*)"
        )
        if path:
            self.load(Path(path))

    def load(self, path: str | Path) -> bool:
        """Read ``path`` and fill the controls in from it. False when it cannot be read."""
        try:
            drawing = read_drawing(path)
        except DxfImportError as exc:
            self._drawing = None
            self._path = None
            self._file.clear()
            self._layers.clear()
            self._summary.show_message(str(exc), level="error")
            self._ok.setEnabled(False)
            return False

        self._drawing = drawing
        self._path = Path(path)
        self._file.setText(str(path))

        self._layers.blockSignals(True)
        self._layers.clear()
        for layer in drawing.layers:
            item = QListWidgetItem(layer)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self._layers.addItem(item)
        self._layers.blockSignals(False)

        scale = unit_scale(drawing, self._project.meta.units)
        self._scale.blockSignals(True)
        self._scale.setValue(scale)
        self._scale.blockSignals(False)

        tolerance = merge_tolerance(drawing)
        self._tolerance.blockSignals(True)
        self._tolerance.setValue(tolerance)
        self._tolerance.blockSignals(False)

        unit = labels_for(self._project.meta.units).length
        if drawing.unit_in_metres is None:
            self._units.setText(
                f"<b>{drawing.unit_name}</b> (the file does not say): nothing is converted, "
                f"so one drawing unit is one {unit}. Set the scale if that is wrong."
            )
        else:
            self._units.setText(
                f"<b>{drawing.unit_name}</b> from the file: one drawing unit is {scale:g} {unit}."
            )
        self._refresh()
        return True

    # ── what the caller needs ───────────────────────────────────────
    def drawing(self) -> DxfDrawing | None:
        return self._drawing

    def source(self) -> Path | None:
        return self._path

    def chosen_layers(self) -> list[str] | None:
        """The layers ticked in the list, or None while nothing is loaded."""
        if self._drawing is None:
            return None
        layers = [
            self._layers.item(row).text()
            for row in range(self._layers.count())
            if self._layers.item(row).checkState() == Qt.CheckState.Checked
        ]
        return layers

    def plane(self) -> str:
        return self._plane.currentData() or "XY"

    def scale(self) -> float:
        return self._scale.value()

    def level(self) -> float:
        return self._level.value()

    def origin(self) -> tuple[float, float, float]:
        return (self._origin[0].value(), self._origin[1].value(), self._origin[2].value())

    def tolerance(self) -> float:
        return self._tolerance.value()

    def section_choice(self) -> int | None:
        """The section for the imported members; None means "create the default one"."""
        data = self._section.currentData()
        if data is None or int(data) == CREATE_DEFAULT:
            return None
        return int(data)

    def imported_bars(self, section_id: int):  # type: ignore[no-untyped-def]
        """The models this import would add, with the ids the project would give them."""
        if self._drawing is None:
            return None
        return bars_from_drawing(
            select_layers(self._drawing, self.chosen_layers()),
            section_id=section_id,
            plane=self.plane(),
            scale=self.scale(),
            level=self.level(),
            origin=self.origin(),
            tolerance=self.tolerance(),
            first_node_id=self._project.next_node_id(),
            first_element_id=self._project.next_element_id(),
        )

    # ── live summary ────────────────────────────────────────────────
    def _refresh(self) -> None:
        drawing = self._drawing
        if drawing is None:
            self._summary.clear_message()
            self._ok.setEnabled(False)
            return

        selected = select_layers(drawing, self.chosen_layers())
        bars = bars_from_drawing(
            selected,
            section_id=1,
            plane=self.plane(),
            scale=self.scale(),
            level=self.level(),
            origin=self.origin(),
            tolerance=self.tolerance(),
        )

        if bars.n_members == 0:
            self._summary.show_message(
                "Nothing to import: no straight bars on the chosen layers.", level="warning"
            )
            self._ok.setEnabled(False)
            return

        text = bars.summary()
        extra = selected.skipped_summary()
        if extra:
            text += f" {extra}"
        self._summary.show_message(text)
        self._ok.setEnabled(True)


def member_sections(project: Project) -> list:  # type: ignore[type-arg]
    """The project's sections a beam-column can take (a plate section cannot)."""
    return [s for s in project.sections if not isinstance(s, ElasticMembranePlateSection)]
