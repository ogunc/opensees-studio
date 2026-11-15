"""Assign Load dialog — apply nodal force/moment vector to selected nodes."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QComboBox,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.views.dialogs import load_target
from opensees_studio.views.float_field import FloatField
from opensees_studio.views.screen_fit import FittedDialog

# Sentinel the pattern combo's userData holds to mean "create a new one".
_NEW_PATTERN_SENTINEL = "__new__"


class AssignLoadDialog(FittedDialog):
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
        *,
        force_unit: str = "",
        length_unit: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Assign Nodal Load")
        self._existing_patterns = list(existing_patterns or [])
        self._force_unit = force_unit
        self._length_unit = length_unit
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
        # The pattern chosen last (any load dialog), else the first one, else "New".
        self._pattern_cb.setCurrentIndex(0)
        last = load_target.last_pattern_id()
        if last is not None and self._pattern_cb.findData(last) >= 0:
            self._pattern_cb.setCurrentIndex(self._pattern_cb.findData(last))
        self._pattern_cb.currentIndexChanged.connect(self._on_pattern_changed)
        pf.addRow("Load pattern:", self._pattern_cb)
        self._mode_cb = QComboBox()
        self._mode_cb.addItem("Add to existing loads", load_target.ADD)
        self._mode_cb.addItem("Replace existing loads", load_target.REPLACE)
        self._mode_cb.addItem("Delete existing loads", load_target.DELETE)
        self._mode_cb.setToolTip(
            "Add: summed with the joints' loads in this pattern. Replace: those loads "
            "are removed first. Delete: they are removed and nothing is added."
        )
        self._mode_cb.currentIndexChanged.connect(self._on_mode_changed)
        pf.addRow("Existing loads:", self._mode_cb)

        self._new_name_edit = QLineEdit("Pattern")
        self._new_name_edit.setPlaceholderText("Name for the new pattern (e.g. RefMoment)")
        pf.addRow("New name:", self._new_name_edit)

        # TimeSeries type selector — only used when creating a new
        # pattern. "Linear" ramps with pseudoTime (default), "Constant"
        # stays at factor 1 throughout (axial preloads, etc.).
        self._ts_type_cb = QComboBox()
        self._ts_type_cb.addItem("Linear (factor = pseudoTime)", "Linear")
        self._ts_type_cb.addItem("Constant (factor = 1)", "Constant")
        pf.addRow("New TimeSeries:", self._ts_type_cb)
        layout.addLayout(pf)

        # Show / hide the new-name field in line with the combo.
        self._on_pattern_changed(self._pattern_cb.currentIndex())

        # ── Force vector ──
        form = QFormLayout()
        self._spinboxes: dict[str, FloatField] = {}
        force = f" ({self._force_unit})" if self._force_unit else ""
        moment = (
            f" ({self._force_unit}·{self._length_unit})"
            if self._force_unit and self._length_unit
            else ""
        )
        for label in ("Fx", "Fy", "Fz", "Mx", "My", "Mz"):
            sb = FloatField()
            sb.setRange(-1e12, 1e12)
            sb.setSingleStep(1.0)
            sb.setValue(0.0)
            self._spinboxes[label] = sb
            form.addRow(f"{label}{force if label[0] == 'F' else moment}:", sb)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self._on_accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_accept(self) -> None:
        pid = self.selected_pattern_id()
        if pid is not None:
            load_target.remember_pattern(pid)
        self.accept()

    def _on_pattern_changed(self, _idx: int) -> None:
        data = self._pattern_cb.currentData()
        is_new = data == _NEW_PATTERN_SENTINEL
        self._new_name_edit.setEnabled(is_new)
        self._ts_type_cb.setEnabled(is_new)
        # A new pattern has no loads to replace or delete.
        if is_new:
            self._mode_cb.setCurrentIndex(0)
        self._mode_cb.setEnabled(not is_new)

    def _on_mode_changed(self, _idx: int) -> None:
        deleting = self.load_mode() == load_target.DELETE
        for sb in self._spinboxes.values():
            sb.setEnabled(not deleting)

    def load_mode(self) -> str:
        """``add``, ``replace`` or ``delete`` (see :mod:`load_target`)."""
        return str(self._mode_cb.currentData())

    def set_load_mode(self, mode: str) -> None:
        self._mode_cb.setCurrentIndex(self._mode_cb.findData(mode))

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

    def new_time_series_type(self) -> str:
        """Return "Linear" or "Constant" — the TimeSeries class to pair
        with a freshly created pattern. Ignored when reusing an
        existing pattern."""
        return self._ts_type_cb.currentData()
