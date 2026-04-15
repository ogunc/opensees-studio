"""Grid System dialog — parametric node generator.

User specifies spacings along X, Y, Z (each as a comma-separated list
or a uniform "n@d" expression like ``"5@3.0"`` meaning 5 spaces of
3.0). The dialog produces a flat list of :class:`Node` objects at all
grid intersections, ready for an :class:`AddNodesCommand`.
"""

from __future__ import annotations

from itertools import product

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core import Node


class GridSystemDialog(QDialog):
    """Dialog for entering X/Y/Z grid spacings."""

    def __init__(self, next_node_id: int, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Grid System")
        self._next_id = next_node_id
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)

        info = QLabel(
            "Enter spacings (comma-separated or n@d).\n"
            "Examples: '3, 3, 3' → x=0, 3, 6, 9     '4@5' → x=0, 5, 10, 15, 20\n"
            "Leave blank for a single coordinate (0)."
        )
        info.setWordWrap(True)
        layout.addWidget(info)

        form = QFormLayout()
        self._x_edit = QLineEdit("3, 3")
        self._y_edit = QLineEdit("3, 3")
        self._z_edit = QLineEdit("3, 3")
        form.addRow("X spacings:", self._x_edit)
        form.addRow("Y spacings:", self._y_edit)
        form.addRow("Z spacings:", self._z_edit)
        layout.addLayout(form)

        self._preview = QLabel()
        self._preview.setWordWrap(True)
        layout.addWidget(self._preview)

        for w in (self._x_edit, self._y_edit, self._z_edit):
            w.textChanged.connect(self._update_preview)
        self._update_preview()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    # ── parsing ──────────────────────────────────────────────────────
    @staticmethod
    def _parse_spacings(text: str) -> list[float]:
        text = text.strip()
        if not text:
            return []
        # Support "n@d" syntax for uniform spacing.
        if "@" in text:
            n_str, d_str = text.split("@", 1)
            return [float(d_str)] * int(n_str)
        return [float(p) for p in text.replace(";", ",").split(",") if p.strip()]

    @staticmethod
    def _coordinates_from_spacings(spacings: list[float]) -> list[float]:
        coords = [0.0]
        for s in spacings:
            coords.append(coords[-1] + s)
        return coords

    # ── preview ──────────────────────────────────────────────────────
    def _update_preview(self) -> None:
        try:
            xs = self._coordinates_from_spacings(self._parse_spacings(self._x_edit.text()))
            ys = self._coordinates_from_spacings(self._parse_spacings(self._y_edit.text()))
            zs = self._coordinates_from_spacings(self._parse_spacings(self._z_edit.text()))
            n = len(xs) * len(ys) * len(zs)
            self._preview.setText(
                f"<b>{n}</b> nodes will be created — "
                f"({len(xs)} × {len(ys)} × {len(zs)} grid)."
            )
        except (ValueError, IndexError) as exc:
            self._preview.setText(f"<span style='color:red'>Parse error: {exc}</span>")

    # ── result ───────────────────────────────────────────────────────
    def generated_nodes(self) -> list[Node]:
        xs = self._coordinates_from_spacings(self._parse_spacings(self._x_edit.text()))
        ys = self._coordinates_from_spacings(self._parse_spacings(self._y_edit.text()))
        zs = self._coordinates_from_spacings(self._parse_spacings(self._z_edit.text()))
        nodes: list[Node] = []
        next_id = self._next_id
        for x, y, z in product(xs, ys, zs):
            nodes.append(Node(id=next_id, coords=(x, y, z)))
            next_id += 1
        return nodes
