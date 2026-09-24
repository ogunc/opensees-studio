"""Assign Bearing dialog: connect two joints with an isolator.

Same pattern as the Zero-Length Section dialog: the main window selects
two nodes, the dialog collects the bearing parameters and the axial and
moment materials, and ``build_element`` returns the validated core
element (``ElastomericBearingPlasticityElement``,
``ElastomericBearingBoucWenElement``, ``FlatSliderBearingElement`` or
``SingleFPBearingElement``). The nodes may be coincident (the runner
writes the orientation) or separated by the bearing height.

Read-only helpers: for the elastomeric bearings the yield displacement
``u_y = Qd / (Kinit (1 - alpha1))``, the yield force ``Qd / (1 - alpha1)``
and the secant stiffness of the backbone at a user-given displacement; for
the sliding bearings, under a user-given axial load ``W`` and the selected
friction model's zero-velocity coefficient, the slip displacement
``mu W / Kinit``, and for the pendulum the restoring stiffness ``W / Reff``
and the isolated period ``2 pi sqrt(Reff / g)`` in the project units.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError
from PySide6.QtCore import QLocale
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLabel,
    QVBoxLayout,
    QWidget,
)

from opensees_studio.core import (
    ElasticIsotropic,
    ElastomericBearingBoucWenElement,
    ElastomericBearingPlasticityElement,
    FlatSliderBearingElement,
    Project,
    SingleFPBearingElement,
    bearing_effective_stiffness,
    bearing_yield_displacement,
    bearing_yield_force,
    gravity,
    pendulum_period,
    pendulum_restoring_stiffness,
    sliding_yield_displacement,
)

BEARING_TYPES: tuple[tuple[str, str], ...] = (
    ("ElastomericBearingPlasticity", "elastomericBearingPlasticity (bilinear)"),
    ("ElastomericBearingBoucWen", "elastomericBearingBoucWen (smooth)"),
    ("FlatSliderBearing", "flatSliderBearing (friction, no restoring stiffness)"),
    ("SingleFPBearing", "singleFPBearing (single friction pendulum)"),
)
SLIDING_TYPES = ("FlatSliderBearing", "SingleFPBearing")


def _uniaxial_materials(project: Project) -> list[Any]:
    """Materials usable as the P, Mz, T and My responses (uniaxial only)."""
    return [m for m in project.materials if not isinstance(m, ElasticIsotropic)]


class AssignElastomericBearingDialog(QDialog):
    """Modal dialog: bearing type, parameters, materials, derived helpers."""

    def __init__(
        self, project: Project, node_ids: tuple[int, int], parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Assign Bearing")
        self._project = project
        self._node_ids = node_ids
        self._build_ui()
        self._on_type_changed()
        self._refresh_derived()

    # ---- UI --------------------------------------------------------------------
    @staticmethod
    def _spin(
        lo: float, hi: float, value: float, decimals: int = 4, step: float = 0.1
    ) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setLocale(QLocale(QLocale.Language.C))
        spin.setDecimals(decimals)
        spin.setRange(lo, hi)
        spin.setSingleStep(step)
        spin.setValue(value)
        return spin

    def _material_combo(self) -> QComboBox:
        cb = QComboBox()
        for m in _uniaxial_materials(self._project):
            cb.addItem(f"#{m.id}  {m.name or m.type}", m.id)
        if cb.count() == 0:
            cb.addItem("(no uniaxial materials defined)", None)
            cb.setEnabled(False)
        return cb

    def _friction_combo(self) -> QComboBox:
        cb = QComboBox()
        for fm in self._project.friction_models:
            cb.addItem(f"#{fm.id}  {fm.name or fm.type}  [{fm.type}]", fm.id)
        if cb.count() == 0:
            cb.addItem("(no friction models defined)", None)
            cb.setEnabled(False)
        return cb

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.addWidget(
            QLabel(
                f"Connect node <b>{self._node_ids[0]}</b> (bottom) and "
                f"<b>{self._node_ids[1]}</b> (top) with a bearing. "
                "Coincident nodes are allowed; the runner writes the orientation."
            )
        )

        form = QFormLayout()
        self._form = form
        self._type = QComboBox()
        for key, label in BEARING_TYPES:
            self._type.addItem(label, key)
        self._type.currentIndexChanged.connect(self._on_type_changed)
        form.addRow("Element:", self._type)

        self._k_init = self._spin(1e-9, 1e12, 1000.0, decimals=4, step=10.0)
        self._qd = self._spin(1e-9, 1e12, 10.0, decimals=4, step=1.0)
        self._alpha1 = self._spin(0.0, 1.0, 0.1, decimals=4, step=0.01)
        self._alpha2 = self._spin(0.0, 1.0, 0.0, decimals=4, step=0.01)
        self._mu = self._spin(1e-6, 100.0, 2.0, decimals=3, step=0.5)
        form.addRow("Kinit (initial stiffness):", self._k_init)
        form.addRow("Qd (characteristic strength):", self._qd)
        form.addRow("alpha1 (post-yield ratio, 0 <= alpha1 < 1):", self._alpha1)
        form.addRow("alpha2 (hardening ratio):", self._alpha2)
        form.addRow("mu (hardening exponent):", self._mu)

        self._eta = self._spin(1e-6, 1e3, 1.0, decimals=3, step=0.5)
        self._beta = self._spin(0.0, 10.0, 0.5, decimals=3, step=0.1)
        self._gamma = self._spin(0.0, 10.0, 0.5, decimals=3, step=0.1)
        form.addRow("eta (Bouc-Wen):", self._eta)
        form.addRow("beta (Bouc-Wen):", self._beta)
        form.addRow("gamma (Bouc-Wen):", self._gamma)

        self._friction = self._friction_combo()
        self._r_eff = self._spin(0.0, 1e9, 1.0, decimals=4, step=0.1)
        self._max_iter = self._spin(1.0, 1e4, 25.0, decimals=0, step=1.0)
        self._tol = self._spin(1e-15, 1.0, 1e-12, decimals=15, step=1e-12)
        form.addRow("Friction model:", self._friction)
        form.addRow("Reff (effective radius, single FP):", self._r_eff)
        form.addRow("-iter maximum iterations:", self._max_iter)
        form.addRow("-iter tolerance:", self._tol)

        self._p_mat = self._material_combo()
        self._mz_mat = self._material_combo()
        self._t_mat = self._material_combo()
        self._my_mat = self._material_combo()
        form.addRow("Axial P material:", self._p_mat)
        form.addRow("Moment Mz material:", self._mz_mat)
        self._t_label = QLabel("Torsion T material (3D):")
        self._my_label = QLabel("Moment My material (3D):")
        form.addRow(self._t_label, self._t_mat)
        form.addRow(self._my_label, self._my_mat)
        is_3d = self._project.ndm == 3
        for w in (self._t_label, self._t_mat, self._my_label, self._my_mat):
            w.setVisible(is_3d)

        self._shear_dist = self._spin(0.0, 1.0, 0.5, decimals=3, step=0.1)
        self._do_rayleigh = QCheckBox("Include in Rayleigh damping (-doRayleigh)")
        self._mass = self._spin(0.0, 1e12, 0.0, decimals=6, step=0.1)
        form.addRow("Shear distance ratio (-shearDist):", self._shear_dist)
        form.addRow("", self._do_rayleigh)
        form.addRow("Element mass (-mass):", self._mass)
        root.addLayout(form)

        helpers = QGroupBox("Derived (read-only)")
        hform = QFormLayout(helpers)
        self._hform = hform
        self._u_y_label = QLabel("")
        self._f_y_label = QLabel("")
        self._u_eff = self._spin(1e-9, 1e9, 0.1, decimals=4, step=0.01)
        self._k_eff_label = QLabel("")
        hform.addRow("Yield displacement u_y:", self._u_y_label)
        hform.addRow("Yield force F_y:", self._f_y_label)
        hform.addRow("Displacement for K_eff:", self._u_eff)
        hform.addRow("Effective (secant) stiffness K_eff:", self._k_eff_label)
        self._weight = self._spin(1e-9, 1e15, 100.0, decimals=4, step=10.0)
        self._slip_label = QLabel("")
        self._k_r_label = QLabel("")
        self._period_label = QLabel("")
        hform.addRow("Axial load W for the helpers:", self._weight)
        hform.addRow("Slip displacement mu W / Kinit:", self._slip_label)
        hform.addRow("Restoring stiffness W / Reff:", self._k_r_label)
        hform.addRow("Isolated period 2 pi sqrt(Reff / g):", self._period_label)
        root.addWidget(helpers)

        self._error = QLabel("")
        self._error.setStyleSheet("color: #c0392b;")
        self._error.setWordWrap(True)
        root.addWidget(self._error)

        for spin in (
            self._k_init,
            self._qd,
            self._alpha1,
            self._alpha2,
            self._mu,
            self._u_eff,
            self._r_eff,
            self._weight,
        ):
            spin.valueChanged.connect(self._refresh_derived)
        self._friction.currentIndexChanged.connect(self._refresh_derived)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    # ---- behaviour ---------------------------------------------------------------
    def bearing_type(self) -> str:
        return str(self._type.currentData())

    def is_sliding(self) -> bool:
        return self.bearing_type() in SLIDING_TYPES

    @staticmethod
    def _set_row_visible(form: QFormLayout, widget: QWidget, visible: bool) -> None:
        widget.setVisible(visible)
        label = form.labelForField(widget)
        if label is not None:
            label.setVisible(visible)

    def _on_type_changed(self) -> None:
        kind = self.bearing_type()
        sliding = self.is_sliding()
        bouc_wen = kind == "ElastomericBearingBoucWen"
        for w in (self._eta, self._beta, self._gamma):
            w.setEnabled(bouc_wen)
        for w in (
            self._qd,
            self._alpha1,
            self._alpha2,
            self._mu,
            self._eta,
            self._beta,
            self._gamma,
        ):
            self._set_row_visible(self._form, w, not sliding)
        for w in (self._friction, self._max_iter, self._tol):
            self._set_row_visible(self._form, w, sliding)
        self._set_row_visible(self._form, self._r_eff, kind == "SingleFPBearing")
        for w in (self._u_y_label, self._f_y_label, self._u_eff, self._k_eff_label):
            self._set_row_visible(self._hform, w, not sliding)
        for w in (self._weight, self._slip_label):
            self._set_row_visible(self._hform, w, sliding)
        for w in (self._k_r_label, self._period_label):
            self._set_row_visible(self._hform, w, kind == "SingleFPBearing")
        self._refresh_derived()

    def _selected_friction_model(self) -> Any | None:
        fid = self._friction.currentData()
        if fid is None:
            return None
        return self._project.friction_model(int(fid))

    def derived_text(self) -> str:
        if self.is_sliding():
            return (
                f"{self._slip_label.text()}; {self._k_r_label.text()}; {self._period_label.text()}"
            )
        return f"{self._u_y_label.text()}; {self._f_y_label.text()}; {self._k_eff_label.text()}"

    def _refresh_sliding_derived(self) -> None:
        k, w, r = self._k_init.value(), self._weight.value(), self._r_eff.value()
        fm = self._selected_friction_model()
        if fm is None:
            self._slip_label.setText("(no friction model)")
            self._k_r_label.setText("")
            self._period_label.setText("")
            return
        try:
            mu = fm.coefficient(0.0, w)
            self._slip_label.setText(
                f"{sliding_yield_displacement(mu, w, k):.6g} (mu = {mu:.4g} at zero velocity)"
            )
        except ValueError as exc:
            self._slip_label.setText(str(exc))
        if self.bearing_type() != "SingleFPBearing":
            self._k_r_label.setText("")
            self._period_label.setText("")
            return
        try:
            units = self._project.meta.units
            self._k_r_label.setText(f"{pendulum_restoring_stiffness(w, r):.6g}")
            self._period_label.setText(
                f"{pendulum_period(r, gravity(units)):.6g} s (g = {gravity(units):g}, {units.value})"
            )
        except ValueError as exc:
            self._k_r_label.setText(str(exc))
            self._period_label.setText("")

    def _refresh_derived(self) -> None:
        if self.is_sliding():
            self._refresh_sliding_derived()
            return
        k, qd, a1 = self._k_init.value(), self._qd.value(), self._alpha1.value()
        try:
            u_y = bearing_yield_displacement(k, qd, a1)
            f_y = bearing_yield_force(k, qd, a1)
            k_eff = bearing_effective_stiffness(
                k, qd, a1, self._u_eff.value(), self._alpha2.value(), self._mu.value()
            )
        except ValueError as exc:
            self._u_y_label.setText(str(exc))
            self._f_y_label.setText("")
            self._k_eff_label.setText("")
            return
        self._u_y_label.setText(f"{u_y:.6g}")
        self._f_y_label.setText(f"{f_y:.6g}")
        self._k_eff_label.setText(f"{k_eff:.6g} at u = {self._u_eff.value():g}")

    def error_text(self) -> str:
        return self._error.text()

    def build_element(self, element_id: int) -> Any:
        """The validated bearing element; raises ValueError with the reason."""
        if self._p_mat.currentData() is None or self._mz_mat.currentData() is None:
            raise ValueError("Define a uniaxial material first (Define > Material Library).")
        sliding = self.is_sliding()
        if sliding and self._friction.currentData() is None:
            raise ValueError("Define a friction model first (Define > Friction Models).")
        common: dict[str, Any] = dict(
            id=element_id,
            nodes=self._node_ids,
            k_init=self._k_init.value(),
            p_material_id=int(self._p_mat.currentData()),
            mz_material_id=int(self._mz_mat.currentData()),
            shear_dist=self._shear_dist.value(),
            do_rayleigh=self._do_rayleigh.isChecked(),
            mass=self._mass.value(),
        )
        if sliding:
            common.update(
                friction_model_id=int(self._friction.currentData()),
                max_iter=int(self._max_iter.value()),
                tol=self._tol.value(),
            )
        else:
            common.update(
                qd=self._qd.value(),
                alpha1=self._alpha1.value(),
                alpha2=self._alpha2.value(),
                mu=self._mu.value(),
            )
        if self._project.ndm == 3:
            common["t_material_id"] = (
                int(self._t_mat.currentData()) if self._t_mat.currentData() is not None else None
            )
            common["my_material_id"] = (
                int(self._my_mat.currentData()) if self._my_mat.currentData() is not None else None
            )
        try:
            kind = self.bearing_type()
            if kind == "SingleFPBearing":
                return SingleFPBearingElement(**common, r_eff=self._r_eff.value())
            if kind == "FlatSliderBearing":
                return FlatSliderBearingElement(**common)
            if kind == "ElastomericBearingBoucWen":
                return ElastomericBearingBoucWenElement(
                    **common,
                    eta=self._eta.value(),
                    beta=self._beta.value(),
                    gamma=self._gamma.value(),
                )
            return ElastomericBearingPlasticityElement(**common)
        except ValidationError as exc:
            lines = [
                f"{'.'.join(str(p) for p in e['loc']) or 'element'}: {e['msg']}"
                for e in exc.errors()
            ]
            raise ValueError("; ".join(lines)) from exc

    def accept(self) -> None:  # type: ignore[override]
        """Validate before closing; an invalid bearing keeps the dialog open."""
        try:
            self.build_element(999999)
        except ValueError as exc:
            self._error.setText(f"Bearing rejected: {exc}")
            return
        self._error.setText("")
        super().accept()
