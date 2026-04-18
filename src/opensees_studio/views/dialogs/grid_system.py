"""Grid System dialog — SAP2000-style visual grid definition.

The user enters X/Y/Z grid-line coordinates (three accepted syntaxes).
On accept, the dialog returns a :class:`GridSystem` that will be stored
on the project and rendered in the 3D canvas as reference lines.

An optional checkbox also generates :class:`Node` objects at every
grid intersection, for users who want the old one-click behaviour.
"""

from __future__ import annotations

from itertools import product

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core import Node
from opensees_studio.core.geometry import GridSystem


def _parse_spacings(text: str) -> list[float]:
    """Parse a spacings expression into a list of inter-line distances.

    Accepted forms:
    - blank             → []  (no grid lines on this axis)
    - single integer N  → [1.0]*(N-1)    (N lines at unit spacing)
    - "n@d"             → [d]*n          (n equal spacings of size d)
    - "a, b, c"         → [a, b, c]
    """
    text = text.strip()
    if not text:
        return []
    if "@" in text:
        n_str, d_str = text.split("@", 1)
        return [float(d_str)] * int(n_str)
    if "," not in text and ";" not in text and "." not in text:
        try:
            n = int(text)
            if n >= 1:
                return [1.0] * (n - 1)
        except ValueError:
            pass
    return [float(p) for p in text.replace(";", ",").split(",") if p.strip()]


def _coords_from_spacings(spacings: list[float], origin: float = 0.0) -> list[float]:
    """Convert a list of spacings into absolute grid-line coordinates."""
    coords = [origin]
    for s in spacings:
        coords.append(coords[-1] + s)
    return coords


class GridSystemDialog(QDialog):
    """Dialog for entering X/Y/Z grid-line coordinates."""

    def __init__(self, next_node_id: int,
                 existing: GridSystem | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Grid System")
        self._next_id = next_node_id
        self._existing = existing
        self._build_ui()
        if existing is not None:
            self._load_existing(existing)
        self._update_preview()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        info = QLabel(
            "Define grid lines per axis. Three accepted formats:<br>"
            "&bull; <b>Single integer</b> — number of lines at unit spacing "
            "(<code>5</code> → 0, 1, 2, 3, 4)<br>"
            "&bull; <b>n@d</b> — n equal spacings of size d "
            "(<code>4@1.5</code> → 0, 1.5, 3, 4.5, 6)<br>"
            "&bull; <b>Comma-separated spacings</b> "
            "(<code>3, 3, 4</code> → 0, 3, 6, 10)<br>"
            "Leave an axis blank for a 2D/1D grid."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        form = QFormLayout()
        self._x_edit = QLineEdit("5")
        self._y_edit = QLineEdit("5")
        self._z_edit = QLineEdit("5")
        form.addRow("X spacings:", self._x_edit)
        form.addRow("Y spacings:", self._y_edit)
        form.addRow("Z spacings:", self._z_edit)
        layout.addLayout(form)

        self._visible_cb = QCheckBox("Show grid in 3D view")
        self._visible_cb.setChecked(True)
        layout.addWidget(self._visible_cb)

        self._generate_nodes_cb = QCheckBox(
            "Also create nodes at every intersection"
        )
        self._generate_nodes_cb.setChecked(False)
        layout.addWidget(self._generate_nodes_cb)

        self._preview = QLabel()
        self._preview.setWordWrap(True)
        layout.addWidget(self._preview)

        for w in (self._x_edit, self._y_edit, self._z_edit):
            w.textChanged.connect(self._update_preview)
        self._generate_nodes_cb.toggled.connect(self._update_preview)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _load_existing(self, grid: GridSystem) -> None:
        """Pre-fill editors from an existing GridSystem (as spacings)."""
        def to_spacings_text(coords: list[float]) -> str:
            if not coords:
                return ""
            spacings = [coords[i + 1] - coords[i] for i in range(len(coords) - 1)]
            if not spacings:
                # Single line at nonzero origin — degenerate, show empty.
                return ""
            return ", ".join(f"{s:g}" for s in spacings)
        self._x_edit.setText(to_spacings_text(grid.x_lines))
        self._y_edit.setText(to_spacings_text(grid.y_lines))
        self._z_edit.setText(to_spacings_text(grid.z_lines))
        self._visible_cb.setChecked(grid.visible)

    def _update_preview(self) -> None:
        try:
            xs = _coords_from_spacings(_parse_spacings(self._x_edit.text()))
            ys = _coords_from_spacings(_parse_spacings(self._y_edit.text()))
            zs = _coords_from_spacings(_parse_spacings(self._z_edit.text()))
            if self._generate_nodes_cb.isChecked():
                n_nodes = len(xs) * len(ys) * len(zs)
                extra = f"<br>Will create <b>{n_nodes}</b> nodes at intersections."
            else:
                extra = "<br>Nodes will NOT be created automatically."
            self._preview.setText(
                f"Grid: <b>{len(xs)}</b> × <b>{len(ys)}</b> × <b>{len(zs)}</b> lines."
                f"{extra}"
            )
        except (ValueError, IndexError) as exc:
            self._preview.setText(f"<span style='color:red'>Parse error: {exc}</span>")

    # ── result accessors ─────────────────────────────────────────────
    def grid_system(self) -> GridSystem:
        """Return the GridSystem configured in the dialog."""
        return GridSystem(
            x_lines=_coords_from_spacings(_parse_spacings(self._x_edit.text())),
            y_lines=_coords_from_spacings(_parse_spacings(self._y_edit.text())),
            z_lines=_coords_from_spacings(_parse_spacings(self._z_edit.text())),
            visible=self._visible_cb.isChecked(),
        )

    def should_generate_nodes(self) -> bool:
        return self._generate_nodes_cb.isChecked()

    def generated_nodes(self) -> list[Node]:
        """Build nodes at every grid intersection (only if checkbox is on)."""
        if not self._generate_nodes_cb.isChecked():
            return []
        grid = self.grid_system()
        xs = grid.x_lines or [0.0]
        ys = grid.y_lines or [0.0]
        zs = grid.z_lines or [0.0]
        nodes: list[Node] = []
        next_id = self._next_id
        for x, y, z in product(xs, ys, zs):
            nodes.append(Node(id=next_id, coords=(x, y, z)))
            next_id += 1
        return nodes
