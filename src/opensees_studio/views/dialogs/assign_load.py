"""Assign Load dialog — apply nodal force/moment vector to selected nodes."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

# Sentinel the pattern combo's userData holds to mean "create a new one".
_NEW_PATTERN_SENTINEL = "__new__"


class AssignLoadDialog(QDialog):
    """Modal dialog for entering a 6-component force vector + pattern pick.

    ``existing_patterns`` — list of ``(pattern_id, pattern_name)`` tuples.
    The dialog adds an extra ``<New pattern…>`` entry that lets the user
    name a brand-new Plain pattern on the fly. The host reads the result
    via :meth:`selected_pattern_id` (None ⇒ new) and
    :meth:`new_pattern_name` (the name to use when creating).
    """

    def __init__(
        self,
        n_selected: int,
        existing_patterns: list[tuple[int, str]] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Assign Nodal Load")
        self._existing_patterns = list(existing_patterns or [])
        self._build_ui(n_selected)

    def _build_ui(self, n_selected: int) -> None:
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Apply to <b>{n_selected}</b> selected node(s)."))

        # ── Load pattern picker ─────────────────────────────────────
        pf = QFormLayout()
        self._pattern_cb = QComboBox()
        for pid, pname in self._existing_patterns:
            display = f"#{pid}  {pname}" if pname else f"#{pid}"
            self._pattern_cb.addItem(display, pid)
        self._pattern_cb.addItem("<New pattern…>", _NEW_PATTERN_SENTINEL)
        # Default to an existing pattern if present, else "New".
        if self._existing_patterns:
            self._pattern_cb.setCurrentIndex(0)
        else:
            self._pattern_cb.setCurrentIndex(0)   # "<New pattern…>"
        self._pattern_cb.currentIndexChanged.connect(self._on_pattern_changed)
        pf.addRow("Load pattern:", self._pattern_cb)

        self._new_name_edit = QLineEdit("Pattern")
        self._new_name_edit.setPlaceholderText(
            "Name for the new pattern (e.g. RefMoment)"
        )
        pf.addRow("New name:", self._new_name_edit)
        layout.addLayout(pf)

        # Show / hide the new-name field in line with the combo.
        self._on_pattern_changed(self._pattern_cb.currentIndex())

        # ── Force vector ──
        form = QFormLayout()
        self._spinboxes: dict[str, QDoubleSpinBox] = {}
        for label in ("Fx", "Fy", "Fz", "Mx", "My", "Mz"):
            sb = QDoubleSpinBox()
            sb.setRange(-1e12, 1e12)
            sb.setDecimals(4)
            sb.setSingleStep(1.0)
            sb.setValue(0.0)
            self._spinboxes[label] = sb
            form.addRow(f"{label}:", sb)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_pattern_changed(self, _idx: int) -> None:
        data = self._pattern_cb.currentData()
        is_new = data == _NEW_PATTERN_SENTINEL
        self._new_name_edit.setEnabled(is_new)

    def forces(self) -> tuple[float, float, float, float, float, float]:
        return tuple(self._spinboxes[k].value() for k in ("Fx", "Fy", "Fz", "Mx", "My", "Mz"))  # type: ignore[return-value]

    def selected_pattern_id(self) -> int | None:
        """Return the chosen pattern id, or ``None`` if the user picked
        ``<New pattern…>`` (in which case :meth:`new_pattern_name` has
        the name the host should use for the freshly created pattern)."""
        data = self._pattern_cb.currentData()
        if data == _NEW_PATTERN_SENTINEL:
            return None
        return int(data)

    def new_pattern_name(self) -> str:
        """Return the name the user typed for a new pattern."""
        return self._new_name_edit.text().strip() or "Pattern"
