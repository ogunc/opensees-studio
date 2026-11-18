"""Assign line, edge and area springs: a stiffness, a direction, the medium's side, a behaviour.

One dialog for the three kinds (:mod:`opensees_studio.core.support_springs`):

- Assign → Area → Area Springs — per unit area, under the selected shells;
- Assign → Area → Edge Springs — per unit length, along the edges of the
  selected shells whose two joints are selected too;
- Assign → Frame → Line Springs — per unit length, along the selected frames.

The *side* says where the supporting medium is, which is what makes "compression
only" mean the structure pressing into it. OK replaces, adds to or deletes the
springs of the selected elements; the host applies the result in one undoable
command.
"""

from __future__ import annotations

from typing import Literal

from PySide6.QtWidgets import (
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core.help import TOPIC_PROPERTY
from opensees_studio.core.support_springs import BEHAVIOURS
from opensees_studio.views.float_field import FloatField
from opensees_studio.views.screen_fit import FittedDialog

Kind = Literal["area", "line", "edge"]

_DIRECTIONS: dict[Kind, list[tuple[str, str]]] = {
    "area": [
        ("Shell normal (local 3)", "normal"),
        ("Global Z", "Z"),
        ("Global X", "X"),
        ("Global Y", "Y"),
    ],
    "edge": [
        ("Global Z", "Z"),
        ("Global X", "X"),
        ("Global Y", "Y"),
        ("Shell normal (local 3)", "normal"),
    ],
    "line": [
        ("Global Z", "Z"),
        ("Global X", "X"),
        ("Global Y", "Y"),
        ("Local 1 (axial)", "1"),
        ("Local 2", "2"),
        ("Local 3", "3"),
    ],
}
_TITLES: dict[Kind, str] = {
    "area": "Area Springs",
    "edge": "Edge Springs",
    "line": "Line Springs",
}
_TOPICS: dict[Kind, str] = {
    "area": "assign.area_springs",
    "edge": "assign.edge_springs",
    "line": "assign.line_springs",
}
ACTIONS: tuple[tuple[str, str], ...] = (
    ("Replace the springs of the selection", "replace"),
    ("Add to the springs of the selection", "add"),
    ("Delete the springs of the selection", "delete"),
)


class SupportSpringDialog(FittedDialog):
    """A distributed spring: stiffness, direction, side of the medium, behaviour."""

    def __init__(
        self,
        kind: Kind,
        n_targets: int,
        *,
        length_unit: str = "length",
        force_unit: str = "force",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._kind = kind
        self.setWindowTitle(f"Assign {_TITLES[kind]}")
        self.setProperty(TOPIC_PROPERTY, _TOPICS[kind])
        layout = QVBoxLayout(self)
        what = {
            "area": f"{n_targets} shell(s): a stiffness per unit area, handed to the corners by "
            "tributary area (a Winkler bed).",
            "edge": f"{n_targets} shell edge(s): a stiffness per unit length, half to each end "
            "of the edge.",
            "line": f"{n_targets} frame member(s): a stiffness per unit length, half to each end "
            "(a beam on an elastic foundation).",
        }[kind]
        intro = QLabel(what + " Mesh finely: the support is lumped at the nodes.")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        form = QFormLayout()
        per = f"{force_unit}/{length_unit}³" if kind == "area" else f"{force_unit}/{length_unit}²"
        self.stiffness = FloatField()
        self.stiffness.setRange(0.0, 1e18)
        self.stiffness.setValue(1.0)
        form.addRow(f"Stiffness ({per}):", self.stiffness)
        self.direction = QComboBox()
        for label, key in _DIRECTIONS[kind]:
            self.direction.addItem(label, key)
        form.addRow("Direction:", self.direction)
        self.side = QComboBox()
        self.side.addItem("On the negative side (soil under a +Z spring)", "negative")
        self.side.addItem("On the positive side", "positive")
        self.side.setToolTip(
            "Where the supporting medium is, along the direction. Compression is the "
            "structure moving into it. For the shell normal, positive is the local 3 side "
            "(SAP2000's Top face)."
        )
        form.addRow("Supporting medium:", self.side)
        self.behaviour = QComboBox()
        for label, key in BEHAVIOURS:
            self.behaviour.addItem(label, key)
        form.addRow("Behaviour:", self.behaviour)
        self.action = QComboBox()
        for label, key in ACTIONS:
            self.action.addItem(label, key)
        form.addRow("Existing springs:", self.action)
        layout.addLayout(form)

        note = QLabel(
            "Compression-only and tension-only springs make the model nonlinear: the cases "
            "they take part in are solved by Newton iteration, and the log says which springs "
            "let go."
        )
        note.setWordWrap(True)
        layout.addWidget(note)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.action.currentIndexChanged.connect(self._action_changed)

    def _action_changed(self) -> None:
        editing = self.action.currentData() != "delete"
        for widget in (self.stiffness, self.direction, self.side, self.behaviour):
            widget.setEnabled(editing)

    def values(self) -> dict[str, object]:
        """The spring's fields (without ``element_id``/``edge``)."""
        return {
            "stiffness": self.stiffness.value(),
            "direction": str(self.direction.currentData()),
            "side": str(self.side.currentData()),
            "behaviour": str(self.behaviour.currentData()),
        }

    def mode(self) -> str:
        return str(self.action.currentData())
