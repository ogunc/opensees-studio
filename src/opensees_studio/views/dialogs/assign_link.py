"""Assign → Joint → Link: a ``twoNodeLink`` or a Triple Friction Pendulum between two joints.

twoNodeLink: tick the local directions that carry a material and pick one for
each (any uniaxial material: a damper, a gap, an IMK spring …); the local axes
are OpenSees' unless an orientation is typed (needed when the joints coincide).
Triple Friction Pendulum (3D): three friction models, a vertical and three
rotational materials, the radii and displacement limits of the three surfaces.
"""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QLabel,
    QLineEdit,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core import (
    Project,
    TripleFrictionPendulumElement,
    TwoNodeLinkElement,
)
from opensees_studio.core.materials.library import is_uniaxial
from opensees_studio.views.float_field import FloatField
from opensees_studio.views.screen_fit import FittedDialog, MessageArea

_DIR_LABELS = {
    2: ("1 axial (local x)", "2 shear (local y)", "3 rotation"),
    3: (
        "1 axial (local x)",
        "2 shear (local y)",
        "3 shear (local z)",
        "4 torsion",
        "5 rotation about y",
        "6 rotation about z",
    ),
}


def _float(value: float) -> FloatField:
    field = FloatField()
    field.setRange(-1e300, 1e300)
    field.setValue(value)
    return field


class AssignLinkDialog(FittedDialog):
    """Pick the link type and its properties for the two selected joints."""

    def __init__(
        self, project: Project, nodes: tuple[int, int], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Assign Link")
        self._project = project
        self._nodes = nodes
        self._materials = [m for m in project.materials if is_uniaxial(m)]
        root = QVBoxLayout(self)
        root.addWidget(QLabel(f"Between joints {nodes[0]} (i) and {nodes[1]} (j)."))
        top = QFormLayout()
        self.kind = QComboBox()
        self.kind.addItem("twoNodeLink (one material per direction)", "TwoNodeLink")
        if project.ndm == 3 and project.ndf == 6:
            self.kind.addItem("Triple Friction Pendulum isolator", "TripleFrictionPendulum")
        top.addRow("Type:", self.kind)
        root.addLayout(top)
        self.pages = QStackedWidget()
        self.pages.addWidget(self._link_page())
        self.pages.addWidget(self._tfp_page())
        root.addWidget(self.pages)
        self.kind.currentIndexChanged.connect(self.pages.setCurrentIndex)
        self.message = MessageArea()
        root.addWidget(self.message)
        if not self._materials:
            self.message.show_message(
                "Define a uniaxial material first (Material Library).", "warning"
            )
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _material_combo(self) -> QComboBox:
        combo = QComboBox()
        for m in self._materials:
            combo.addItem(f"#{m.id} {m.name or m.type} [{m.type}]", m.id)
        return combo

    # ── twoNodeLink ─────────────────────────────────────────────────
    def _link_page(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        box = QGroupBox("Directions")
        grid = QGridLayout(box)
        self.dir_checks: dict[int, QCheckBox] = {}
        self.dir_materials: dict[int, QComboBox] = {}
        labels = _DIR_LABELS[3 if self._project.ndm == 3 else 2]
        if self._project.ndf < len(labels):
            labels = labels[: self._project.ndf]
        for k, label in enumerate(labels, start=1):
            check = QCheckBox(label)
            check.setChecked(k == 1)
            combo = self._material_combo()
            grid.addWidget(check, k, 0)
            grid.addWidget(combo, k, 1)
            self.dir_checks[k] = check
            self.dir_materials[k] = combo
        layout.addWidget(box)
        form = QFormLayout()
        self.orient = QLineEdit()
        self.orient.setPlaceholderText("x1 x2 x3 y1 y2 y3  (empty: OpenSees' axes)")
        if self._coincident():
            self.orient.setText("0 0 1 1 0 0")
        form.addRow("Orientation:", self.orient)
        self.do_rayleigh = QCheckBox("Stiffness-proportional Rayleigh damping (-doRayleigh)")
        form.addRow(self.do_rayleigh)
        self.mass = _float(0.0)
        form.addRow("Element mass:", self.mass)
        layout.addLayout(form)
        return page

    def _coincident(self) -> bool:
        coords = {n.id: n.coords for n in self._project.nodes}
        a, b = (coords.get(n) for n in self._nodes)
        return (
            a is not None
            and b is not None
            and all(abs(x - y) < 1e-12 for x, y in zip(a, b, strict=True))
        )

    # ── Triple Friction Pendulum ────────────────────────────────────
    def _tfp_page(self) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        self.frictions: list[QComboBox] = []
        for k in (1, 2, 3):
            combo = QComboBox()
            for fm in self._project.friction_models:
                combo.addItem(f"#{fm.id} {fm.name or fm.type} [{fm.type}]", fm.id)
            form.addRow(f"Friction model, surface {k}:", combo)
            self.frictions.append(combo)
        self.tfp_materials: dict[str, QComboBox] = {}
        for key, label in (
            ("vertical_material_id", "Vertical material"),
            ("rot_z_material_id", "Torsion material"),
            ("rot_x_material_id", "Rotation X material"),
            ("rot_y_material_id", "Rotation Y material"),
        ):
            combo = self._material_combo()
            form.addRow(f"{label}:", combo)
            self.tfp_materials[key] = combo
        self.tfp_values: dict[str, FloatField] = {}
        for key, default in (
            ("L1", 0.36),
            ("L2", 2.1),
            ("L3", 2.1),
            ("d1", 0.05),
            ("d2", 0.4),
            ("d3", 0.4),
            ("W", 1e5),
            ("uy", 0.001),
            ("kvt", 1e10),
            ("min_fv", 0.1),
            ("tol", 1e-5),
        ):
            field = _float(default)
            info = TripleFrictionPendulumElement.model_fields[key]
            form.addRow(f"{key} — {info.description}:", field)
            self.tfp_values[key] = field
        form.addRow(
            QLabel(
                "<i>Run the gravity load as a case of its own first and use it as the "
                "preload of the dynamic case: the pendulum needs its axial load before "
                "it can slide.</i>"
            )
        )
        return page

    # ── result ─────────────────────────────────────────────────────
    def build_element(self, element_id: int) -> Any:
        """The element as typed (raises ``ValueError`` on a bad entry)."""
        if not self._materials:
            raise ValueError("Define a uniaxial material first.")
        if self.kind.currentData() == "TripleFrictionPendulum":
            if not self._project.friction_models:
                raise ValueError("Define three friction models first (Friction Models).")
            fields: dict[str, Any] = {
                k: int(c.currentData()) for k, c in self.tfp_materials.items()
            }
            fields.update({k: float(f.value()) for k, f in self.tfp_values.items()})
            frictions = [int(c.currentData()) for c in self.frictions]
            return TripleFrictionPendulumElement(
                id=element_id,
                nodes=self._nodes,
                friction_model_ids=(frictions[0], frictions[1], frictions[2]),
                **fields,
            )
        dirs = [k for k, check in self.dir_checks.items() if check.isChecked()]
        if not dirs:
            raise ValueError("Tick at least one direction.")
        text = self.orient.text().replace(",", " ").split()
        orient = None
        if text:
            try:
                values = [float(t) for t in text]
            except ValueError:
                raise ValueError("Orientation: six numbers, x1 x2 x3 y1 y2 y3.") from None
            if len(values) != 6:
                raise ValueError("Orientation: six numbers, x1 x2 x3 y1 y2 y3.")
            orient = (values[0], values[1], values[2], values[3], values[4], values[5])
        return TwoNodeLinkElement(
            id=element_id,
            nodes=self._nodes,
            material_ids=tuple(int(self.dir_materials[k].currentData()) for k in dirs),
            dirs=tuple(dirs),
            orient=orient,
            do_rayleigh=self.do_rayleigh.isChecked(),
            mass=float(self.mass.value()),
        )

    def accept(self) -> None:
        try:
            self.build_element(1)
        except ValueError as exc:
            self.message.show_message(str(exc), "error")
            return
        super().accept()
